"""S&P 500 constituents — a mechanical, not-cherry-picked universe (spec §4 approximation).

Pulled from Wikipedia (free, no key) since FMP's constituent endpoint is gated on the free
tier. This is CURRENT membership, so survivorship bias remains (names dropped from the index
2020-2026 are missing) — but it is ~500 names chosen by an index committee, not 50 winners I
hand-picked knowing the outcome. The delisted.csv overlay adds back known removals. Honest
improvement, not a cure; the backtest banner still flags residual survivorship.
"""
from __future__ import annotations

import io

import pandas as pd
import requests

from ..config import DATA_DIR

_WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
SP500_CSV = DATA_DIR / "sp500_constituents.csv"


def fetch_sp500_from_wikipedia() -> pd.DataFrame:
    """[ticker, sector, industry] for current S&P 500 members. Dots -> dashes (yfinance form)."""
    r = requests.get(_WIKI_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    df = pd.read_html(io.StringIO(r.text))[0]
    out = pd.DataFrame({
        "ticker": df["Symbol"].astype(str).str.replace(".", "-", regex=False).str.strip().str.upper(),
        "sector": df["GICS Sector"].astype(str).str.strip(),
        "industry": df["GICS Sub-Industry"].astype(str).str.strip(),
    })
    return out.drop_duplicates(subset="ticker").reset_index(drop=True)


def refresh_sp500_csv() -> pd.DataFrame:
    df = fetch_sp500_from_wikipedia()
    df.to_csv(SP500_CSV, index=False)
    return df
