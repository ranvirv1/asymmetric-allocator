"""M1 — Universe builder (spec §3).

Defines the point-in-time investable set. Must include names later delisted, or the
backtest is survivorship-poisoned. Free-data reality (§4): true point-in-time Russell
membership isn't free, so we approximate with a seed list + a maintained delisted overlay
and FLAG the residual survivorship bias on every backtest (§6, §7).

Output: a DataFrame for date t with [ticker, sector, industry, mktcap, adv, source].
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import pandas as pd

from .config import DATA_DIR, load_config, load_keys
from .data import prices


@dataclass
class UniverseResult:
    as_of: pd.Timestamp
    members: pd.DataFrame
    survivorship_flagged: bool = True
    notes: list[str] = field(default_factory=list)


@lru_cache(maxsize=1)
def _seed() -> pd.DataFrame:
    """Candidate name list. config universe.source = 'sp500' uses the mechanical S&P 500
    constituent list (data/sp500_constituents.csv) if present; else the dev seed list."""
    source = load_config().get("universe", {}).get("source", "seed")
    path = DATA_DIR / "sp500_constituents.csv"
    if source != "sp500" or not path.exists():
        path = DATA_DIR / "universe_seed.csv"
    df = pd.read_csv(path, comment="#")
    df["ticker"] = df["ticker"].str.strip().str.upper()
    for col in ("sector", "industry"):
        if col not in df.columns:
            df[col] = ""
    return df


@lru_cache(maxsize=1)
def _delisted() -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / "delisted.csv", comment="#")
    df["ticker"] = df["ticker"].str.strip().str.upper()
    df["delist_date"] = pd.to_datetime(df["delist_date"])
    return df


def candidate_set(as_of: pd.Timestamp) -> pd.DataFrame:
    """Seed names + delisted names that were still alive at `as_of`."""
    seed = _seed()[["ticker", "sector", "industry"]].copy()
    seed["source"] = "seed"

    dead = _delisted()
    alive_dead = dead[dead["delist_date"] >= as_of][["ticker", "sector", "industry"]].copy()
    alive_dead["source"] = "delisted_overlay"

    out = pd.concat([seed, alive_dead], ignore_index=True)
    return out.drop_duplicates(subset="ticker", keep="first").reset_index(drop=True)


def _adv_usd(ticker: str, as_of: pd.Timestamp, window: int = 20) -> float:
    """20-day average dollar volume as of t (close * volume). 0 if no data."""
    start = (as_of - pd.Timedelta(days=120)).strftime("%Y-%m-%d")
    df = prices.fetch_ohlcv(ticker, start=start, end=as_of.strftime("%Y-%m-%d"))
    if df.empty or "volume" not in df.columns:
        return 0.0
    df = df[df.index <= as_of].tail(window)
    if df.empty:
        return 0.0
    return float((df["close"] * df["volume"]).mean())


def _mktcap_usd(ticker: str, as_of: pd.Timestamp) -> float:
    """As-of market cap ≈ current shares outstanding × close[t] (point-in-time price,
    current share count — an approximation flagged in the notes). NaN if unavailable."""
    keys = load_keys()
    if not keys.fmp:
        return float("nan")
    try:
        from .data import fmp

        prof = fmp.profile(ticker)
        shares = prof.get("sharesOutstanding") or prof.get("shareOutstanding")
        if not shares:
            mcap = prof.get("marketCap") or prof.get("mktCap")
            return float(mcap) if mcap else float("nan")
        px = prices.fetch_ohlcv(ticker, end=as_of.strftime("%Y-%m-%d"))
        if px.empty:
            return float("nan")
        close = px[px.index <= as_of]["close"]
        if close.empty:
            return float("nan")
        return float(shares) * float(close.iloc[-1])
    except Exception:
        return float("nan")


def build_universe(
    as_of: str | pd.Timestamp,
    cfg: dict | None = None,
    with_mktcap: bool = False,
) -> UniverseResult:
    """Build universe[t]. ADV is computed from free price data (always on); market-cap
    filtering only applies when `with_mktcap` and an FMP key are present.
    """
    cfg = cfg or load_config()
    as_of = pd.Timestamp(as_of)
    ucfg = cfg["universe"]
    min_adv = float(ucfg["min_adv_usd"])
    min_mktcap = float(ucfg["min_mktcap_usd"])
    notes: list[str] = []

    cand = candidate_set(as_of)
    cand["adv"] = [_adv_usd(t, as_of) for t in cand["ticker"]]

    has_data = cand["adv"] > 0
    if (~has_data).any():
        notes.append(
            f"{int((~has_data).sum())} names had no price data as of {as_of.date()} "
            f"(pre-IPO/delisted/symbol miss) and were dropped."
        )
    kept = cand[has_data & (cand["adv"] >= min_adv)].copy()

    if with_mktcap and load_keys().fmp:
        kept["mktcap"] = [_mktcap_usd(t, as_of) for t in kept["ticker"]]
        notes.append("market-cap = current shares × point-in-time price (approximation).")
        mc = kept["mktcap"]
        kept = kept[(mc.isna()) | (mc >= min_mktcap)].copy()
    else:
        kept["mktcap"] = float("nan")
        notes.append("market-cap filter skipped (no FMP key / with_mktcap=False).")

    notes.append(
        "SURVIVORSHIP: universe approximated from seed + delisted overlay, not true "
        "point-in-time Russell membership — treat backtest results as an upper bound (§6)."
    )
    kept = kept.sort_values("adv", ascending=False).reset_index(drop=True)
    return UniverseResult(as_of=as_of, members=kept, notes=notes)
