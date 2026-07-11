"""Sanity-lint config.yaml: type traps, sum constraints, ordering, window overlap.

Run:  python .claude/skills/allocator-diagnostics-and-tooling/scripts/config_lint.py
Exit 0 = clean; exit 1 = at least one FAIL. No keys, no network.
"""
from __future__ import annotations

import sys

from allocator.config import load_config

fails = 0


def check(ok: bool, msg: str) -> None:
    global fails
    print(("  OK   " if ok else "  FAIL ") + msg)
    if not ok:
        fails += 1


def main() -> None:
    cfg = load_config()

    print("type traps (PyYAML 1.5e9-as-string):")
    def walk(d, path=""):
        if isinstance(d, dict):
            for k, v in d.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(d, str) and any(c in d for c in "eE") and d[:1].isdigit():
            try:
                float(d)
                check(False, f"{path} = {d!r} is a STRING that looks numeric (use signed exponent, e.g. 1.5e+9)")
            except ValueError:
                pass
    walk(cfg)
    check(isinstance(cfg["universe"]["min_mktcap_usd"], (int, float)),
          f"universe.min_mktcap_usd is numeric ({cfg['universe']['min_mktcap_usd']!r})")

    print("weights:")
    w = cfg["weights"]
    check(abs(sum(w.values()) - 1.0) < 1e-9, f"base weights sum to 1.0 (got {sum(w.values())})")

    print("regime budgets:")
    for v, b in cfg["regime_budgets"].items():
        tot = b["anchor"] + b["satellite"] + b["cash"]
        check(abs(tot - 1.0) < 1e-9, f"{v} anchor+satellite+cash = 1.0 (got {tot})")

    print("cuts ordering:")
    c = cfg["cuts"]
    check(c["A_cut"] >= c["S_cut"], f"A_cut ({c['A_cut']}) >= S_cut ({c['S_cut']})")
    check(c["E_hi"] > c["E_lo"], f"E_hi ({c['E_hi']}) > E_lo ({c['E_lo']})")

    print("caps:")
    caps = cfg["caps"]
    check(0 < caps["anchor_max"] <= 1, f"anchor_max in (0,1] ({caps['anchor_max']})")
    check(caps["satellite_max"] <= caps["satellite_total_max"],
          "satellite_max <= satellite_total_max")

    print("backtest windows:")
    bt = cfg["backtest"]
    t0, t1 = bt["tune_window"]
    v0, v1 = bt["validate_window"]
    check(t1 < v0, f"tune ends ({t1}) before validate starts ({v0}) — no overlap")
    check(bt["start"] <= t0 and v1 <= bt["end"], "windows inside backtest start/end")

    print("exits:")
    ex = cfg["exits"]
    check(ex["stop_atr"] > 0 and ex["trail_atr"] > 0, "ATR multiples positive")
    check(ex["trim1_at"] < ex["trim2_at"], "trim ladder ordered")

    print(f"\n{'CLEAN' if fails == 0 else f'{fails} FAILURE(S)'}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
