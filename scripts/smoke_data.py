"""Smoke test for the M1 data layer (spec §8 milestone 1 test).

Proves the plumbing end-to-end:
  - stooq prices + indicators (no API key needed)
  - universe[t] for sample dates
  - FRED/FMP/Finnhub light calls IF keys are present in .env (skipped otherwise)

Run:  .venv\\Scripts\\python.exe scripts\\smoke_data.py
"""
from __future__ import annotations

import pandas as pd

from allocator.config import load_config, load_keys
from allocator.data import prices
from allocator import universe


def hr(title: str) -> None:
    print("\n" + "=" * 70 + f"\n{title}\n" + "=" * 70)


def main() -> None:
    cfg = load_config()
    keys = load_keys()

    hr("1. PRICES (stooq, no key) — NVDA daily OHLCV + indicators")
    df = prices.fetch_ohlcv("NVDA", start="2022-06-01", end="2023-12-31")
    if df.empty:
        print("  !! stooq returned no data (rate-limited?). yfinance fallback also empty.")
    else:
        df = df.assign(
            sma50=prices.sma(df["close"], 50),
            sma200=prices.sma(df["close"], 200),
            atr_pct=prices.atr_pct(df),
            ret_6m=prices.trailing_return(df["close"], 6),
        )
        last = df.dropna().iloc[-1]
        print(f"  rows: {len(df)}   span: {df.index.min().date()} -> {df.index.max().date()}")
        print(f"  last close: {last['close']:.2f}  sma50: {last['sma50']:.2f}  "
              f"sma200: {last['sma200']:.2f}")
        print(f"  ATR%: {last['atr_pct']*100:.1f}%   trailing 6m return: {last['ret_6m']*100:.1f}%")

    hr("2. RELATIVE STRENGTH — NVDA vs S&P 500 (^SPX), 6-month")
    spx = prices.fetch_ohlcv("^SPX", start="2022-06-01", end="2023-12-31")
    if not df.empty and not spx.empty:
        nvda_6m = prices.trailing_return(df["close"], 6).iloc[-1]
        spx_6m = prices.trailing_return(spx["close"], 6).iloc[-1]
        print(f"  NVDA 6m: {nvda_6m*100:+.1f}%   SPX 6m: {spx_6m*100:+.1f}%   "
              f"RS spread: {(nvda_6m - spx_6m)*100:+.1f} pts")
    else:
        print("  (index data unavailable)")

    hr("3. UNIVERSE[t] — point-in-time investable set (ADV filter, no key)")
    for as_of in ["2021-06-30", "2023-06-30", "2025-06-02"]:
        res = universe.build_universe(as_of, cfg, with_mktcap=False)
        m = res.members
        min_adv = float(cfg["universe"]["min_adv_usd"])
        print(f"\n  as of {as_of}: {len(m)} names pass ADV >= ${min_adv:,.0f}")
        if not m.empty:
            top = m.head(5)[["ticker", "sector", "adv"]]
            for _, r in top.iterrows():
                print(f"     {r['ticker']:<6} {r['sector']:<24} ADV ${r['adv']/1e6:,.0f}M")

    hr("4. API KEYS present in .env")
    for name in ("fred", "fmp", "finnhub"):
        print(f"  {name.upper():<8}: {'set ✓' if getattr(keys, name) else 'MISSING — add to .env'}")

    if keys.fred:
        hr("5. FRED (key present) — HY credit spread, latest")
        from allocator.data import fred
        s = fred.fetch_named("hy_spread", start="2024-01-01")
        if not s.empty:
            print(f"  BAMLH0A0HYM2 latest: {s.iloc[-1]:.2f}%  on {s.index[-1].date()}  ({len(s)} obs)")

    if keys.fmp:
        hr("6. FMP (key present) — NVDA profile + target consensus")
        from allocator.data import fmp
        prof = fmp.profile("NVDA")
        print(f"  sector: {prof.get('sector')}  industry: {prof.get('industry')}  "
              f"mktCap: {prof.get('marketCap')}")
        ptc = fmp.price_target_consensus("NVDA")
        print(f"  target consensus: {ptc.get('targetConsensus')}  high: {ptc.get('targetHigh')}")

    print("\n" + "=" * 70 + "\nSMOKE TEST COMPLETE\n" + "=" * 70)


if __name__ == "__main__":
    main()
