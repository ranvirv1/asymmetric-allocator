"""Data layer (spec §4): free-first wrappers with disk caching.

  fred     — macro/rates/spreads (M2)            [needs FRED key]
  prices   — stooq EOD primary, yfinance backup  [no key]
  fmp      — analyst estimates, fundamentals      [needs FMP key]
  finnhub  — fundamentals + catalysts backup       [needs Finnhub key]

Every wrapper caches to data/cache so the backtest is reproducible and we stay within
free-tier rate limits.
"""
