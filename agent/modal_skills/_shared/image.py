"""Shared Modal image for AIFS GRIB skills."""
from __future__ import annotations

import modal


def build_aifs_image(*, skill_dir: str, shared_dir: str) -> modal.Image:
    return (
        modal.Image.debian_slim(python_version="3.11")
        .apt_install("libeccodes-dev", "libeccodes0")
        .pip_install(
            "cfgrib==0.9.15.0",
            "eccodes==2.39.1",
            "xarray",
            "numpy",
            "scipy",
            "shapely",
            "psycopg[binary]",
            "httpx",
            "ecmwf-opendata",
        )
        .add_local_dir(skill_dir, remote_path="/root/skill")
        .add_local_dir(shared_dir, remote_path="/root/shared")
    )
