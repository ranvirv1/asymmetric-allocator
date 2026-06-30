"""Price data — stooq EOD primary, yfinance secondary (spec §4).

stooq is cleaner / ToS-safer for EOD; yfinance is unofficial — used only as a research
fallback, never productionised. Prices are POINT-IN-TIME clean (raw OHLCV), which is why
the RS signal and the momentum-only backtest can be honest with free data today.
"""
from __future__ import annotations

import io
import time

import numpy as np
import pandas as pd
import requests

from . import cache

_STOOQ_URL = "https://stooq.com/q/d/l/"
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "Mozilla/5.0 (asymmetric-allocator research)"})

# Index proxies for relative-strength (spec §2, §4). stooq symbol on the left.
INDEX_SYMBOLS = {"SPX": "^spx", "NDX": "^ndx", "RUT": "^rut"}


def stooq_symbol(ticker: str) -> str:
    """Map a US ticker to its stooq symbol (e.g. AAPL -> aapl.us, ^SPX -> ^spx)."""
    t = ticker.strip().lower()
    if t.startswith("^"):
        return t
    return f"{t}.us"


def _parse_stooq_csv(text: str) -> pd.DataFrame:
    if not text or text.lstrip().lower().startswith("<"):  # HTML error page / rate limit
        return pd.DataFrame()
    df = pd.read_csv(io.StringIO(text))
    if df.empty or "Date" not in df.columns:
        return pd.DataFrame()
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date").sort_index()
    df.columns = [c.lower() for c in df.columns]
    return df


_last_request = 0.0
_MIN_INTERVAL = 0.25  # polite throttle — stooq rate-limits bursts


def _throttle() -> None:
    global _last_request
    gap = time.time() - _last_request
    if gap < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - gap)
    _last_request = time.time()


_NEG_TTL = 6 * 3600  # remember "no data" for 6h so transient failures don't poison results
_stooq_blocked = False  # set True once stooq serves its JS challenge — skip it thereafter


def _is_challenge(text: str) -> bool:
    return text.lstrip().lower().startswith("<")  # HTML interstitial, not CSV


def _from_stooq(ticker: str, retries: int = 1) -> pd.DataFrame:
    """Full history from stooq. Returns empty if stooq serves its JS anti-bot challenge
    (an HTML page `requests` can't solve) or the symbol is unknown. Once challenged, the
    whole session skips stooq so we don't pay the retry cost on every name."""
    global _stooq_blocked
    if _stooq_blocked:
        return pd.DataFrame()
    for attempt in range(retries + 1):
        _throttle()
        try:
            r = _SESSION.get(_STOOQ_URL, params={"s": stooq_symbol(ticker), "i": "d"}, timeout=30)
            if r.ok:
                if _is_challenge(r.text):
                    _stooq_blocked = True
                    return pd.DataFrame()
                df = _parse_stooq_csv(r.text)
                if not df.empty:
                    return df
        except requests.RequestException:
            pass
        time.sleep(0.4 * (attempt + 1))
    return pd.DataFrame()


def _from_fmp(ticker: str) -> pd.DataFrame:
    """Full history from FMP — robust primary when a key is present (no bot challenge)."""
    from ..config import load_keys

    if not load_keys().fmp or ticker.startswith("^"):
        return pd.DataFrame()
    try:
        from . import fmp

        return fmp.historical_prices(ticker)
    except Exception:
        return pd.DataFrame()


_MEM_PRICES: dict[str, pd.DataFrame] = {}  # in-memory cache — keeps a backtest fast


def history(ticker: str, use_cache: bool = True) -> pd.DataFrame:
    """FULL daily OHLCV history for a ticker — fetched once, cached permanently (prices
    are point-in-time clean). Every as-of computation slices from this single frame, so a
    backtest over many dates costs one request per ticker, not one per (ticker, date).

    Source order: FMP (if key) -> stooq -> yfinance. Empty results are negative-cached for
    a short TTL so genuinely-absent names (pre-IPO/delisted) aren't re-fetched every run,
    while a transient failure recovers after the TTL expires.
    """
    ident = f"{ticker}|full"
    if use_cache:
        if ticker in _MEM_PRICES:
            return _MEM_PRICES[ticker]
        cached = cache.get_df("prices", ident)
        if cached is not None:
            _MEM_PRICES[ticker] = cached
            return cached
        if cache.get_json("prices_neg", ident, max_age_sec=_NEG_TTL) is not None:
            return pd.DataFrame()

    df = _from_fmp(ticker)
    if df.empty:
        df = _from_stooq(ticker)
    if df.empty:
        df = _fetch_yfinance(ticker)

    if df.empty:
        if use_cache:
            cache.put_json("prices_neg", ident, True)
        return df
    if use_cache:
        cache.put_df("prices", ident, df)
        _MEM_PRICES[ticker] = df
    return df


def fetch_ohlcv(
    ticker: str,
    start: str | None = None,
    end: str | None = None,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Daily OHLCV sliced to [start, end]. Thin wrapper over `history()` so all price
    access shares one cached full-history fetch per ticker.
    """
    df = history(ticker, use_cache=use_cache)
    if df.empty:
        return df
    if start is not None:
        df = df[df.index >= pd.Timestamp(start)]
    if end is not None:
        df = df[df.index <= pd.Timestamp(end)]
    return df


def reset_memory() -> None:
    """Drop the in-memory price cache (a fresh weekly run wants today's data, not last run's)."""
    _MEM_PRICES.clear()


def prefetch(tickers: list[str], chunk: int = 40, force: bool = False) -> dict[str, int]:
    """Bulk-fill the price cache via yfinance batch download (one request per `chunk`
    tickers, not per ticker) — far gentler on Yahoo's rate limit for a ~500-name universe.
    Skips names already cached unless `force` (force re-pulls fresh full history — used by the
    weekly run to refresh recent days). Returns {"ok", "miss", "cached"}.
    """
    try:
        import logging

        import yfinance as yf

        logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    except ImportError:
        return {"ok": 0, "miss": 0, "cached": 0}

    if force:
        # NON-DESTRUCTIVE: re-attempt all and OVERWRITE on success, but keep existing data on
        # failure. (Deleting first then failing — e.g. yfinance rate-limited — wipes the cache.)
        for t in tickers:
            _MEM_PRICES.pop(t, None)
            cache.invalidate("prices_neg", f"{t}|full")   # clear stale "no data" so retry can fill
        todo = list(tickers)
    else:
        todo = [t for t in tickers if t not in _MEM_PRICES and cache.get_df("prices", f"{t}|full") is None]
    skipped = len(tickers) - len(todo)
    ok = miss = 0
    for i in range(0, len(todo), chunk):
        batch = todo[i:i + chunk]
        _throttle()
        try:
            raw = yf.download(batch, period="max", progress=False, auto_adjust=False,
                              threads=True, group_by="ticker")
        except Exception:
            raw = None
        for t in batch:
            df = pd.DataFrame()
            try:
                sub = raw[t] if (raw is not None and t in raw.columns.get_level_values(0)) else None
                if sub is not None and not sub.dropna(how="all").empty:
                    sub = sub.rename(columns=str.lower).dropna(how="all")
                    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in sub.columns]
                    df = sub[keep].sort_index()
                    df.index.name = "Date"
            except Exception:
                df = pd.DataFrame()
            if not df.empty:
                cache.put_df("prices", f"{t}|full", df)
                _MEM_PRICES[t] = df
                ok += 1
            else:
                miss += 1
    return {"ok": ok, "miss": miss, "cached": skipped}


_QUOTE_TTL = 300  # 5 min — keep live quotes fresh without hammering yfinance


def live_quote(ticker: str, max_age: float = _QUOTE_TTL) -> float | None:
    """Latest (real-time / ~15-min-delayed) market price via yfinance fast_info. Cached.
    Returns None on failure (caller falls back to the last close). When the market is closed
    this returns the last close, which is correct."""
    ident = f"{ticker}|quote"
    cached = cache.get_json("quote", ident, max_age_sec=max_age)
    if cached is not None:
        return cached.get("price")
    price = None
    try:
        import logging

        import yfinance as yf

        logging.getLogger("yfinance").setLevel(logging.CRITICAL)
        _throttle()
        fi = yf.Ticker(ticker).fast_info
        for key in ("last_price", "lastPrice"):
            try:
                v = fi[key]
            except Exception:
                v = getattr(fi, key, None)
            if v:
                price = float(v)
                break
    except Exception:
        price = None
    if price:
        cache.put_json("quote", ident, {"price": price})
    return price


def live_quotes(tickers: list[str], max_age: float = _QUOTE_TTL) -> dict[str, float]:
    """Live quotes for several names; missing ones are simply absent from the dict."""
    out = {}
    for t in tickers:
        q = live_quote(t, max_age=max_age)
        if q is not None:
            out[t] = q
    return out


def _fetch_yfinance(ticker: str) -> pd.DataFrame:
    """Full-history research fallback (spec §4: don't productionise). Throttled, with
    yfinance's own noisy logging silenced — absent names print nothing."""
    if ticker.startswith("^"):
        ticker = {"^SPX": "^GSPC", "^NDX": "^NDX", "^RUT": "^RUT"}.get(ticker, ticker)
    try:
        import logging

        import yfinance as yf

        logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    except ImportError:
        return pd.DataFrame()
    _throttle()
    try:
        raw = yf.download(
            ticker, period="max", progress=False, auto_adjust=False, threads=False
        )
    except Exception:
        return pd.DataFrame()
    if raw is None or raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw = raw.rename(columns=str.lower)
    raw.index.name = "Date"
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in raw.columns]
    return raw[keep].sort_index()


# ---------------------------------------------------------------------------
# Indicators (spec §2 trend/breadth, §4 RS/ATR/vol, §7 stops). All point-in-time:
# every value at row t uses only data up to and including t.
# ---------------------------------------------------------------------------

def sma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window, min_periods=window).mean()


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Average True Range (Wilder). Needs high/low/close columns."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()


def atr_pct(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """ATR as a fraction of close — the vol input for satellite sizing (spec §6)."""
    return atr(df, window) / df["close"]


def trailing_return(close: pd.Series, months: int) -> pd.Series:
    periods = int(round(months * 21))  # ~21 trading days / month
    return close / close.shift(periods) - 1.0


def pct_from_high(close: pd.Series, lookback_days: int = 252) -> pd.Series:
    """Distance below the rolling 52-wk high (0 = at high, negative = below)."""
    roll_high = close.rolling(lookback_days, min_periods=1).max()
    return close / roll_high - 1.0


def annualised_vol(close: pd.Series, window: int = 63) -> pd.Series:
    return close.pct_change().rolling(window, min_periods=window).std() * np.sqrt(252)
