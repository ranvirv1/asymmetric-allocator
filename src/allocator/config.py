"""Config + secrets loading (spec §5, §9).

All tunable thresholds live in config.yaml so the backtester can sweep them and every
run is auditable. API keys live in .env (gitignored) — never in code or config.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Project root = two levels up from this file (src/allocator/config.py -> stock/)
ROOT = Path(__file__).resolve().parents[2]
# Data/report dirs default under the project, but can be redirected to a mounted
# persistent disk in cloud deploys (e.g. DATA_DIR=/var/data) so cache + the latest
# report survive container restarts. See DEPLOY.md.
DATA_DIR = Path(os.getenv("DATA_DIR") or ROOT / "data")
CACHE_DIR = DATA_DIR / "cache"
REPORTS_DIR = Path(os.getenv("REPORTS_DIR") or ROOT / "reports")


@lru_cache(maxsize=1)
def load_config(path: str | None = None) -> dict[str, Any]:
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass(frozen=True)
class Keys:
    fred: str | None
    fmp: str | None
    finnhub: str | None

    def require(self, name: str) -> str:
        val = getattr(self, name)
        if not val:
            raise RuntimeError(
                f"Missing {name.upper()}_API_KEY. Copy .env.example -> .env and fill it in. "
                f"This signal/source can't run without it."
            )
        return val


@lru_cache(maxsize=1)
def load_keys() -> Keys:
    load_dotenv(ROOT / ".env")
    return Keys(
        fred=os.getenv("FRED_API_KEY") or None,
        fmp=os.getenv("FMP_API_KEY") or None,
        finnhub=os.getenv("FINNHUB_API_KEY") or None,
    )
