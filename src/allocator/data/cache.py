"""Disk cache for API responses and price frames (spec §4: caching).

Point-in-time data (historical prices, dated FRED vintages) never changes, so it is
cached permanently. Live-ish data (current consensus, profiles) takes a TTL.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import CACHE_DIR


def _slug(namespace: str, ident: str) -> str:
    h = hashlib.sha1(ident.encode("utf-8")).hexdigest()[:16]
    safe_ns = "".join(c if c.isalnum() else "_" for c in namespace)
    return f"{safe_ns}__{h}"


def _path(namespace: str, ident: str, ext: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{_slug(namespace, ident)}.{ext}"


def get_json(namespace: str, ident: str, max_age_sec: float | None = None) -> Any | None:
    p = _path(namespace, ident, "json")
    if not p.exists():
        return None
    if max_age_sec is not None and (time.time() - p.stat().st_mtime) > max_age_sec:
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def put_json(namespace: str, ident: str, obj: Any) -> Any:
    p = _path(namespace, ident, "json")
    p.write_text(json.dumps(obj), encoding="utf-8")
    return obj


def get_df(namespace: str, ident: str, max_age_sec: float | None = None) -> pd.DataFrame | None:
    p = _path(namespace, ident, "csv")
    if not p.exists():
        return None
    if max_age_sec is not None and (time.time() - p.stat().st_mtime) > max_age_sec:
        return None
    try:
        return pd.read_csv(p, index_col=0, parse_dates=True)
    except (OSError, ValueError):
        return None


def put_df(namespace: str, ident: str, df: pd.DataFrame) -> pd.DataFrame:
    p = _path(namespace, ident, "csv")
    df.to_csv(p)
    return df


def invalidate(namespace: str, ident: str) -> None:
    """Delete one cached entry (both json + csv forms) so the next read re-fetches."""
    for ext in ("json", "csv"):
        p = _path(namespace, ident, ext)
        if p.exists():
            p.unlink()


def clear(namespace: str) -> int:
    """Delete all cached files for a namespace (e.g. 'fred' before a fresh weekly run)."""
    if not CACHE_DIR.exists():
        return 0
    safe_ns = "".join(c if c.isalnum() else "_" for c in namespace)
    n = 0
    for p in CACHE_DIR.glob(f"{safe_ns}__*"):
        p.unlink()
        n += 1
    return n
