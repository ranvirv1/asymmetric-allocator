"""M4 — Signal scoring (the core, spec §3/§4). ERM + RS first (spec §8.3).

Two sub-scores, each a cross-sectional percentile rank (0-100) within universe[t]:

  RS  — Price / Relative Strength. 3/6/12-mo return vs index, distance from 52-wk high,
        above rising 50/200-dma. POINT-IN-TIME CLEAN (computed from raw prices).
  ERM — Estimate-Revision Momentum. Net analyst upgrades-vs-downgrades + grade-level change
        magnitude over trailing windows, from yfinance's DATED analyst actions (free, no
        daily cap). Point-in-time honest because each action is timestamped (filter <= as_of).

WinnerScore = Σ wᵢ·subscoreᵢ, with regime-modulated weights (spec §4): ERM stays anchored;
RS ×1.4 in RISK_ON, ×0.6 in COMPRESSION. FI/EXP/CAT/THM are added later (spec §8.5) only if
the ablation shows they help.

ERM coverage note: grade history thins for smaller names / older dates. Names with no
actions in the window get ERM = NaN and are scored on RS alone (per-name weight renormalise).
"""
from __future__ import annotations

import pandas as pd

from .config import load_config
from .data import estimates, prices

INDEX = "^SPX"

# Map analyst grade text -> ordinal (0 worst .. 4 best) for revision *magnitude*.
_GRADE_RANK = {
    "strong sell": 0, "sell": 1, "underweight": 1, "underperform": 1, "reduce": 1,
    "negative": 1, "sector underperform": 1,
    "hold": 2, "neutral": 2, "market perform": 2, "equal-weight": 2, "equalweight": 2,
    "in-line": 2, "inline": 2, "sector perform": 2, "peer perform": 2, "perform": 2,
    "buy": 3, "outperform": 3, "overweight": 3, "accumulate": 3, "positive": 3, "add": 3,
    "market outperform": 3, "sector outperform": 3, "speculative buy": 3,
    "strong buy": 4, "conviction buy": 4, "top pick": 4,
}


_RS_MEMO: dict[tuple, pd.Series] = {}   # (as_of, tickers) -> RS sub-score; same across strategies
_ERM_MEMO: dict[tuple, pd.Series] = {}  # ditto for ERM — computed once per date, not per strategy


def _pct_rank(s: pd.Series) -> pd.Series:
    """Cross-sectional percentile rank -> 0-100. NaNs stay NaN."""
    return s.rank(pct=True) * 100.0


def _grade_ord(g: str | None) -> float:
    if not g:
        return 2.0
    return float(_GRADE_RANK.get(g.strip().lower(), 2))


# ---------------------------------------------------------------------------
# RS — relative strength (point-in-time clean)
# ---------------------------------------------------------------------------

def _rs_features(ticker: str, as_of: pd.Timestamp, index_close: pd.Series) -> dict:
    df = prices.fetch_ohlcv(ticker, end=as_of.strftime("%Y-%m-%d"))
    if df.empty or len(df) < 60:
        return {}
    c = df["close"]
    f: dict[str, float] = {}
    for months, key in [(3, "ret_3m"), (6, "ret_6m"), (12, "ret_12m")]:
        stock_r = prices.trailing_return(c, months).iloc[-1]
        idx_r = prices.trailing_return(index_close, months).iloc[-1]
        f[f"{key}_ex"] = stock_r - idx_r  # excess return vs index
    f["dist_high"] = prices.pct_from_high(c).iloc[-1]  # closer to 0 = stronger
    sma50, sma200 = c.rolling(50).mean(), c.rolling(200).mean()
    last = c.iloc[-1]
    f["above_50"] = float(last > sma50.iloc[-1]) if pd.notna(sma50.iloc[-1]) else float("nan")
    f["above_200"] = float(last > sma200.iloc[-1]) if pd.notna(sma200.iloc[-1]) else float("nan")
    if len(sma50.dropna()) > 21:
        f["sma50_rising"] = float(sma50.iloc[-1] > sma50.iloc[-22])
    if len(sma200.dropna()) > 21:
        f["sma200_rising"] = float(sma200.iloc[-1] > sma200.iloc[-22])
    return f


def rs_subscore(tickers: list[str], as_of: pd.Timestamp) -> pd.Series:
    memo_key = (pd.Timestamp(as_of), tuple(tickers))
    if memo_key in _RS_MEMO:
        return _RS_MEMO[memo_key]
    idx_df = prices.fetch_ohlcv(INDEX, end=as_of.strftime("%Y-%m-%d"))
    idx_close = idx_df["close"] if not idx_df.empty else pd.Series(dtype=float)
    rows = {t: _rs_features(t, as_of, idx_close) for t in tickers}
    df = pd.DataFrame(rows).T
    if df.empty:
        return pd.Series(dtype=float)

    trend_cols = [c for c in ["above_50", "above_200", "sma50_rising", "sma200_rising"] if c in df]
    trend = df[trend_cols].mean(axis=1) if trend_cols else pd.Series(index=df.index, dtype=float)

    ranks = []
    for col in ["ret_3m_ex", "ret_6m_ex", "ret_12m_ex", "dist_high"]:
        if col in df:
            ranks.append(_pct_rank(df[col].astype(float)))
    ranks.append(_pct_rank(trend))
    rs_raw = pd.concat(ranks, axis=1).mean(axis=1)
    result = _pct_rank(rs_raw).rename("RS")
    _RS_MEMO[memo_key] = result
    return result


# ---------------------------------------------------------------------------
# ERM — estimate-revision momentum from DATED grade actions (point-in-time)
# ---------------------------------------------------------------------------

def _erm_features(ticker: str, as_of: pd.Timestamp, window_days: int = 90) -> dict:
    # Dated analyst actions from yfinance (free, no daily cap) — point-in-time via the
    # date filter below. Replaces FMP grades, which were rate-limited at 250/day.
    try:
        grades = estimates.dated_grades(ticker)
    except Exception:
        return {}
    if not grades:
        return {}
    cutoff = as_of - pd.Timedelta(days=window_days)
    ups = downs = n = 0
    mag = 0.0
    for g in grades:
        try:
            d = pd.Timestamp(g["date"])
        except (KeyError, ValueError):
            continue
        if d > as_of or d < cutoff:
            continue
        n += 1
        action = (g.get("action") or "").strip().lower()
        if action in ("upgrade", "up"):
            ups += 1
        elif action in ("downgrade", "down"):
            downs += 1
        mag += _grade_ord(g.get("newGrade")) - _grade_ord(g.get("previousGrade"))
    if n == 0:
        return {}  # no coverage in window -> ERM undefined for this name
    return {
        "erm_net": ups - downs,                 # net revision count
        "erm_breadth": (ups - downs) / n,       # up-vs-down breadth
        "erm_mag": mag,                          # cumulative grade-level change
        "erm_count": n,                          # coverage / conviction
    }


def erm_subscore(tickers: list[str], as_of: pd.Timestamp) -> pd.Series:
    memo_key = (pd.Timestamp(as_of), tuple(tickers))
    if memo_key in _ERM_MEMO:
        return _ERM_MEMO[memo_key]
    rows = {t: _erm_features(t, as_of) for t in tickers}
    df = pd.DataFrame(rows).T
    if df.empty or df.dropna(how="all").empty:
        result = pd.Series(dtype=float, name="ERM")
        _ERM_MEMO[memo_key] = result
        return result
    ranks = []
    for col in ["erm_net", "erm_breadth", "erm_mag"]:
        if col in df:
            ranks.append(_pct_rank(df[col].astype(float)))
    erm_raw = pd.concat(ranks, axis=1).mean(axis=1)
    result = _pct_rank(erm_raw).rename("ERM")
    _ERM_MEMO[memo_key] = result
    return result


# ---------------------------------------------------------------------------
# WinnerScore — regime-modulated blend
# ---------------------------------------------------------------------------

def regime_weights(cfg: dict, verdict: str, active: list[str]) -> dict[str, float]:
    """Base weights × regime modifier, restricted to `active` sub-scores, renormalised."""
    base = cfg["weights"]
    mod = cfg.get("regime_modifiers", {}).get(verdict, {})
    w = {k: base[k] * mod.get(k, 1.0) for k in active}
    total = sum(w.values()) or 1.0
    return {k: v / total for k, v in w.items()}


def score_universe(
    as_of: str | pd.Timestamp,
    tickers: list[str],
    regime_verdict: str = "MIXED",
    cfg: dict | None = None,
    active: tuple[str, ...] = ("ERM", "RS"),
) -> pd.DataFrame:
    """Return a per-name DataFrame: winner_score (0-100) + sub-scores + flags.

    `active` defaults to ERM+RS (spec §8.3 — the two robust signals first). Per-name weights
    are renormalised over whichever sub-scores are available, so an ERM-uncovered name is
    scored on RS alone rather than penalised to zero.
    """
    cfg = cfg or load_config()
    as_of = pd.Timestamp(as_of)

    subs: dict[str, pd.Series] = {}
    if "RS" in active:
        subs["RS"] = rs_subscore(tickers, as_of)
    if "ERM" in active:
        subs["ERM"] = erm_subscore(tickers, as_of)

    out = pd.DataFrame(index=pd.Index(tickers, name="ticker"))
    for k, s in subs.items():
        out[k] = s
    out = out.dropna(how="all")

    weights = regime_weights(cfg, regime_verdict, list(active))

    def _row_score(row: pd.Series) -> float:
        num = den = 0.0
        for k in active:
            v = row.get(k)
            if pd.notna(v):
                num += weights[k] * v
                den += weights[k]
        return num / den if den else float("nan")

    out["winner_score"] = out.apply(_row_score, axis=1)
    out["erm_covered"] = out["ERM"].notna() if "ERM" in out else False
    out = out.sort_values("winner_score", ascending=False)
    out.attrs["weights"] = weights
    out.attrs["regime"] = regime_verdict
    out.attrs["as_of"] = as_of
    return out
