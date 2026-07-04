#!/usr/bin/env python3
"""Log and track AI stock pick showdown rounds (Claude vs ChatGPT vs S&P 500)."""

import argparse
import csv
import os
import sys
from datetime import datetime, date

CSV_PATH = os.path.join(os.path.dirname(__file__), "data", "ai_picks.csv")
FIELDNAMES = ["round_id", "start_date", "end_date", "source", "ticker", "weight", "reason"]


def _read_rows():
    if not os.path.exists(CSV_PATH):
        return []
    with open(CSV_PATH, newline="") as f:
        return list(csv.DictReader(f))


def _write_rows(rows):
    with open(CSV_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(rows)


def _next_round_id(rows):
    ids = [int(r["round_id"]) for r in rows if r["round_id"].isdigit()]
    return max(ids, default=0) + 1


def _live_rounds(rows):
    live = {}
    for r in rows:
        if not r["end_date"]:
            live.setdefault(r["round_id"], []).append(r)
    return live


def show(rows):
    live = _live_rounds(rows)
    if not live:
        print("No live rounds. Start a new one with --claude or --chatgpt.")
        return
    for rid, picks in sorted(live.items()):
        sources = {}
        for p in picks:
            sources.setdefault(p["source"], []).append(p)
        start = picks[0]["start_date"]
        print(f"\n=== Round {rid} (started {start}) ===")
        for src in ("claude", "chatgpt"):
            sp = sources.get(src, [])
            if sp:
                print(f"  {src.upper()}:")
                for p in sp:
                    print(f"    {p['ticker']:6s} ({float(p['weight']):.0%})  {p['reason']}")
            else:
                print(f"  {src.upper()}: not yet logged")
    print()


def log_picks(rows, source, tickers):
    rid = _next_round_id(rows)
    today = date.today().isoformat()
    weight = round(1.0 / len(tickers), 4)
    new_rows = []
    for t in tickers:
        new_rows.append({
            "round_id": str(rid),
            "start_date": today,
            "end_date": "",
            "source": source,
            "ticker": t.upper(),
            "weight": str(weight),
            "reason": "",
        })
    rows.extend(new_rows)
    _write_rows(rows)
    print(f"Logged {source} picks for round {rid}: {', '.join(t.upper() for t in tickers)}")


def close_round(rows, rid):
    today = date.today().isoformat()
    found = False
    for r in rows:
        if r["round_id"] == str(rid) and not r["end_date"]:
            r["end_date"] = today
            found = True
    if not found:
        print(f"No open round {rid} found.")
        return
    _write_rows(rows)
    print(f"Closed round {rid} (end_date = {today}).")


def main():
    parser = argparse.ArgumentParser(description="AI Stock Pick Showdown logger")
    parser.add_argument("--show", action="store_true", help="Show live rounds")
    parser.add_argument("--claude", nargs="+", metavar="TICKER", help="Log Claude's picks")
    parser.add_argument("--chatgpt", nargs="+", metavar="TICKER", help="Log ChatGPT's picks")
    parser.add_argument("--close", type=int, metavar="ROUND_ID", help="Close a round")
    args = parser.parse_args()

    if not any([args.show, args.claude, args.chatgpt, args.close is not None]):
        parser.print_help()
        sys.exit(1)

    rows = _read_rows()

    if args.show:
        show(rows)
    if args.close is not None:
        close_round(rows, args.close)
        rows = _read_rows()
    if args.claude:
        log_picks(rows, "claude", args.claude)
        rows = _read_rows()
    if args.chatgpt:
        log_picks(rows, "chatgpt", args.chatgpt)


if __name__ == "__main__":
    main()
