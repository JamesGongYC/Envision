"""Grid cell polygons and connected-component aggregation."""
from __future__ import annotations

import os
from collections.abc import Callable

import numpy as np
from scipy import ndimage
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union
from shapely.validation import make_valid

CELL_SIZE = 0.25
MIN_CLUSTER_CELLS = int(os.environ.get("AIFS_MIN_CLUSTER_CELLS", "4"))
MAX_POLYGONS = int(os.environ.get("AIFS_MAX_POLYGONS", "200"))


def cell_polygon(lon: float, lat: float, half: float = CELL_SIZE / 2) -> Polygon:
    return Polygon(
        [
            (lon - half, lat - half),
            (lon + half, lat - half),
            (lon + half, lat + half),
            (lon - half, lat + half),
            (lon - half, lat - half),
        ]
    )


def approx_area_km2(geom: Polygon) -> float:
    centroid = geom.centroid
    lat_rad = np.radians(centroid.y)
    km_per_deg_lat = 111.0
    km_per_deg_lon = 111.0 * max(np.cos(lat_rad), 0.01)
    bounds = geom.bounds
    width_km = (bounds[2] - bounds[0]) * km_per_deg_lon
    height_km = (bounds[3] - bounds[1]) * km_per_deg_lat
    return max(width_km * height_km, 0.0)


def polygons_from_mask(
    mask: np.ndarray,
    lats: np.ndarray,
    lons: np.ndarray,
    *,
    skill_id: str,
    payload_for_cells: Callable[[list[tuple[int, int]]], dict],
) -> list[tuple[Polygon, dict]]:
    labeled, n_labels = ndimage.label(mask)
    if n_labels == 0:
        return []

    half = CELL_SIZE / 2
    results: list[tuple[Polygon, dict]] = []
    for label_id in range(1, n_labels + 1):
        ys, xs = np.where(labeled == label_id)
        cells = list(zip(ys.tolist(), xs.tolist()))
        if len(cells) < MIN_CLUSTER_CELLS:
            continue
        polys = [cell_polygon(float(lons[x]), float(lats[y]), half) for y, x in cells]
        merged = make_valid(unary_union(polys))
        if merged.is_empty:
            continue
        parts = list(merged.geoms) if isinstance(merged, MultiPolygon) else [merged]
        base_payload = payload_for_cells(cells)
        for part in parts:
            if part.is_empty:
                continue
            payload = {**base_payload, "area_km2": round(approx_area_km2(part), 1)}
            results.append((part, payload))

    results.sort(key=lambda item: item[1].get("area_km2", 0), reverse=True)
    if len(results) > MAX_POLYGONS:
        print(f"[{skill_id}] capping polygons {len(results)} -> {MAX_POLYGONS}")
        results = results[:MAX_POLYGONS]
    return results
