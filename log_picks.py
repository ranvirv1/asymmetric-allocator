#!/usr/bin/env python3
"""Log AI stock picks (Claude or ChatGPT) for forward tracking.

Usage:
    python log_picks.py --chatgpt NVDA AAPL MSFT AMZN LLY
    python log_picks.py --claude  GOOGL META AMZN AVGO CRM
    python log_picks.py --chatgpt NVDA:0.30 AAPL:0.25 MSFT:0.25 AMZN:0.20
    python log_picks.py --close 8
    python log_picks.py --show

Weekly workflow:
    1. Ask ChatGPT: "pick your top 5-10 S&P 500 stocks for the next month"
    2. Ask Claude the same prompt
    3. Log both:
         python log_picks.py --chatgpt NVDA AAPL MSFT AMZN LLY
         python log_picks.py --claude  GOOGL META AMZN AVGO CRM
    4. Dashboard tracks both vs each other and vs S&P in real time
    5. Next week: --close the old rounds, log fresh ones
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from allocator.gpt_benchmark import close_round, load_picks, log_picks


def _show():
    df = load_picks()
    if df.empty:
        print("No picks logged yet.")
        return

    models = {"claude": [], "chatgpt": []}
    for rid, group in df.groupby("round_id"):
        row = group.iloc[0]
        model = str(row.get("model", "chatgpt"))
        end = row["end_date"]
        live = " [LIVE]" if str(end) in ("", "NaT", "nan") or end != end else ""
        tickers = ", ".join(f'{r.ticker} ({r.weight:.0%})' for _, r in group.iterrows())
        tag = "C" if model == "claude" else "G"
        print(f"  #{rid:2d} [{tag}] {row['round_name']:35s}  {str(row['pub_date'])[:10]} -> "
              f"{str(end)[:10] if not live else 'today':10s}{live}")
        print(f"       {tickers}")
        models.setdefault(model, []).append(rid)

    print()
    live_count = sum(1 for _, g in df.groupby("round_id")
                     if str(g.iloc[0]["end_date"]) in ("", "NaT", "nan")
                     or g.iloc[0]["end_date"] != g.iloc[0]["end_date"])
    n_rounds = len(df.groupby("round_id"))
    n_claude = len([r for r in df.groupby("round_id") if r[1].iloc[0].get("model") == "claude"])
    n_gpt = n_rounds - n_claude
    print(f"  {n_rounds} rounds ({n_claude} Claude, {n_gpt} GPT), {live_count} live")


def main():
    parser = argparse.ArgumentParser(
        description="Log AI stock picks for Claude vs ChatGPT tracking")
    parser.add_argument("tickers", nargs="*",
                        help="Tickers (e.g. NVDA AAPL or NVDA:0.30 AAPL:0.70)")
    parser.add_argument("--claude", action="store_true", help="Log as Claude picks")
    parser.add_argument("--chatgpt", action="store_true", help="Log as ChatGPT picks")
    parser.add_argument("--name", help="Round label (default: auto)")
    parser.add_argument("--date", help="Pick date YYYY-MM-DD (default: today)")
    parser.add_argument("--close", type=int, metavar="ROUND_ID",
                        help="Close a live round (set end_date to today)")
    parser.add_argument("--close-date", help="End date for --close (default: today)")
    parser.add_argument("--show", action="store_true", help="Show all logged rounds")
    args = parser.parse_args()

    if args.show:
        _show()
        return

    if args.close:
        close_round(args.close, args.close_date)
        print(f"  Closed round #{args.close}")
        _show()
        return

    if not args.tickers:
        parser.print_help()
        return

    if not args.claude and not args.chatgpt:
        print("  Error: specify --claude or --chatgpt")
        print("  Example: python log_picks.py --chatgpt NVDA AAPL MSFT")
        return

    model = "claude" if args.claude else "chatgpt"

    tickers = []
    weights = []
    has_weights = ":" in args.tickers[0]
    for t in args.tickers:
        if ":" in t:
            sym, w = t.split(":", 1)
            tickers.append(sym)
            weights.append(float(w))
        else:
            tickers.append(t)

    result = log_picks(
        tickers=tickers,
        weights=weights if has_weights else None,
        model=model,
        name=args.name,
        pub_date=args.date,
    )

    label = result["model"].title()
    print(f"  Logged round #{result['round_id']}: {result['name']} [{label}]")
    print(f"  Date: {result['pub_date']}  |  Status: LIVE (end_date blank)")
    print(f"  Tickers: {', '.join(f'{t} ({w:.0%})' for t, w in zip(result['tickers'], result['weights']))}")
    print()
    print("  Dashboard will track returns vs the other model and S&P in real time.")
    print(f"  When done, close with: python log_picks.py --close {result['round_id']}")


if __name__ == "__main__":
    main()
