"""Investable universe = S&P 500 ∪ Nasdaq-100 ∪ {TSM}, from Wikipedia (free, no key).

A mechanical, not-cherry-picked set (spec §4 approximation). CURRENT membership, so
survivorship bias remains (names dropped 2020-2026 are missing) — but it's index-committee
chosen, not hand-picked winners. The delisted.csv overlay adds back known removals; the
backtest banner still flags residual survivorship.
"""
from __future__ import annotations

import io

import pandas as pd
import requests

from ..config import DATA_DIR

_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
_NASDAQ100_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"
_UA = {"User-Agent": "Mozilla/5.0"}

SP500_CSV = DATA_DIR / "sp500_constituents.csv"     # kept for back-compat
MEMBERS_CSV = DATA_DIR / "universe_members.csv"     # the blended universe

# Explicitly-requested names outside the indices (e.g. TSM, a Taiwan ADR not in the S&P 500).
EXTRA_MEMBERS = [
    {"ticker": "TSM", "sector": "Technology", "industry": "Semiconductors", "index": "extra"},
]


def _clean_ticker(s: pd.Series) -> pd.Series:
    return s.astype(str).str.replace(".", "-", regex=False).str.strip().str.upper()


def fetch_sp500_from_wikipedia() -> pd.DataFrame:
    """[ticker, sector, industry] for current S&P 500 members. Dots -> dashes (yfinance form)."""
    r = requests.get(_SP500_URL, headers=_UA, timeout=30)
    r.raise_for_status()
    df = pd.read_html(io.StringIO(r.text))[0]
    out = pd.DataFrame({
        "ticker": _clean_ticker(df["Symbol"]),
        "sector": df["GICS Sector"].astype(str).str.strip(),
        "industry": df["GICS Sub-Industry"].astype(str).str.strip(),
    })
    return out.drop_duplicates(subset="ticker").reset_index(drop=True)


def fetch_nasdaq100_from_wikipedia() -> pd.DataFrame:
    """[ticker, sector, industry] for current Nasdaq-100 members. Robust to table ordering."""
    r = requests.get(_NASDAQ100_URL, headers=_UA, timeout=30)
    r.raise_for_status()
    for df in pd.read_html(io.StringIO(r.text)):
        cols = {str(c).lower(): c for c in df.columns}
        tcol = cols.get("ticker") or cols.get("symbol")
        if not tcol:
            continue
        out = pd.DataFrame({
            "ticker": _clean_ticker(df[tcol]),
            "sector": df[cols["gics sector"]].astype(str).str.strip() if "gics sector" in cols else "",
            "industry": df[cols["gics sub-industry"]].astype(str).str.strip() if "gics sub-industry" in cols else "",
        })
        out = out[out["ticker"].str.fullmatch(r"[A-Z][A-Z\-]{0,5}")]
        if len(out) > 50:
            return out.drop_duplicates(subset="ticker").reset_index(drop=True)
    return pd.DataFrame(columns=["ticker", "sector", "industry"])


def refresh_members_csv() -> pd.DataFrame:
    """Build the blended universe (S&P 500 ∪ Nasdaq-100 ∪ extras) and write universe_members.csv.
    Dedupes on ticker, keeping the first source's sector/industry (S&P 500 wins)."""
    sp = fetch_sp500_from_wikipedia().assign(index="sp500")
    try:
        nq = fetch_nasdaq100_from_wikipedia().assign(index="nasdaq100")
    except Exception:
        nq = pd.DataFrame(columns=["ticker", "sector", "industry", "index"])
    extra = pd.DataFrame(EXTRA_MEMBERS)
    members = pd.concat([sp, nq, extra], ignore_index=True)
    members = members.drop_duplicates(subset="ticker", keep="first").reset_index(drop=True)
    members.to_csv(MEMBERS_CSV, index=False)
    return members


def refresh_sp500_csv() -> pd.DataFrame:
    df = fetch_sp500_from_wikipedia()
    df.to_csv(SP500_CSV, index=False)
    return df
