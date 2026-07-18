"""Scrub raw coordinate prose from agent thought text (T11)."""
from __future__ import annotations

import re

# Decimal degree pairs: 37.7, -122.4 or (37.7749, -122.4194)
_DECIMAL_PAIR = re.compile(
    r"\(?\s*-?\d{1,3}\.\d+\s*,\s*-?\d{1,3}\.\d+\s*\)?"
)
# Compact N/S E/W numeric forms: 37.7N 122.4W
_NS_EW = re.compile(
    r"\b\d{1,3}(?:\.\d+)?\s*[NnSs]\s*[, ]\s*\d{1,3}(?:\.\d+)?\s*[EeWw]\b"
)


def scrub_coord_prose(text: str) -> str:
    """Remove lat/lng-style numeric coordinates from thought prose."""
    if not text:
        return text
    out = _DECIMAL_PAIR.sub("[coords omitted]", text)
    out = _NS_EW.sub("[coords omitted]", out)
    # Collapse leftover double spaces around omissions
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()
