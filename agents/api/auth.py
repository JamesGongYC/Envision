"""Operator Bearer auth for write-capable agent fire routes."""
from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException


def require_operator(authorization: str | None = Header(default=None)) -> None:
    """Require Authorization: Bearer <ENVISION_OPERATOR_TOKEN>.

    Missing header → 401. Wrong token → 403. Never creates a run.
    """
    expected = os.environ.get("ENVISION_OPERATOR_TOKEN") or ""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing operator token")
    token = authorization[len("Bearer ") :].strip()
    if not expected or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="invalid operator token")
