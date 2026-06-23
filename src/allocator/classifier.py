"""M5 — Obvious vs Non-obvious classifier (spec §3/§5).

Splits high-scorers into two return profiles:
  ANCHOR    ("biggest / obvious")    — high WinnerScore AND high Extension (confirmed leader,
                                        larger, liquid, already trending). Lower variance.
  SATELLITE ("monster / non-obvious")— high WinnerScore AND LOW Extension, driven by ERM/FI/CAT
                                        (early, cheap, smaller, bottleneck). Higher variance —
                                        where the 10-baggers live.
  WATCH     — everything else.

Extension = mean(RS pctile, valuation pctile, size pctile). With FMP quota-blocked, valuation
is dropped and Extension degrades to RS + size(ADV proxy) — flagged in the rationale.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .config import load_config


@dataclass
class Buckets:
    anchors: pd.DataFrame
    satellites: pd.DataFrame
    watch: pd.DataFrame
    extension: pd.Series
    notes: list[str] = field(default_factory=list)


def compute_extension(scored: pd.DataFrame, members: pd.DataFrame) -> tuple[pd.Series, list[str]]:
    """Extension 0-100 = how 'extended'/obvious a name is. High = leader, low = early."""
    notes: list[str] = []
    parts = []
    if "RS" in scored:
        parts.append(scored["RS"].astype(float))  # already a 0-100 percentile
    size = members.set_index("ticker")["adv"].reindex(scored.index)
    if size.notna().any():
        parts.append(size.rank(pct=True) * 100.0)   # ADV as a size/liquidity proxy
    # valuation percentile would go here (FMP P/E or P/S) — omitted when FMP unavailable
    notes.append("Extension = RS + size(ADV proxy); valuation pctile omitted (needs FMP).")
    ext = pd.concat(parts, axis=1).mean(axis=1) if parts else pd.Series(index=scored.index, dtype=float)
    return ext.rename("extension"), notes


def classify(scored: pd.DataFrame, members: pd.DataFrame, cfg: dict | None = None) -> Buckets:
    cfg = cfg or load_config()
    cuts = cfg["cuts"]
    a_cut, s_cut = cuts["A_cut"], cuts["S_cut"]
    e_hi, e_lo = cuts["E_hi"], cuts["E_lo"]

    ext, notes = compute_extension(scored, members)
    df = scored.copy()
    df["extension"] = ext
    ws = df["winner_score"]

    # ERM strength gate for satellites (the non-obvious driver). If ERM absent, fall back to a
    # high WinnerScore alone so the bucket still populates rather than going empty.
    erm = df["ERM"] if "ERM" in df else pd.Series(index=df.index, dtype=float)
    erm_strong = erm.fillna(df["winner_score"]) >= 60

    is_anchor = (ws >= a_cut) & (df["extension"] >= e_hi)
    is_sat = (ws >= s_cut) & (df["extension"] <= e_lo) & erm_strong & (~is_anchor)

    max_a = int(cuts.get("max_anchors", 12))
    max_s = int(cuts.get("max_satellites", 6))
    anchors_all = df[is_anchor].sort_values("winner_score", ascending=False)
    sats_all = df[is_sat].sort_values("winner_score", ascending=False)
    anchors = anchors_all.head(max_a).copy()   # concentrate (spec §1.4 power-law)
    satellites = sats_all.head(max_s).copy()
    chosen = set(anchors.index) | set(satellites.index)
    watch = df[~df.index.isin(chosen)].sort_values("winner_score", ascending=False).copy()
    if len(anchors_all) > max_a:
        notes.append(f"{len(anchors_all)} names cleared the anchor bar; held the top {max_a} for concentration.")

    anchors["rationale"] = [
        f"Leader: score {r.winner_score:.0f}, extension {r.extension:.0f} (high) — confirmed, liquid, trending."
        for r in anchors.itertuples()
    ]
    satellites["rationale"] = [
        f"Early: score {r.winner_score:.0f}, extension {r.extension:.0f} (low) — under-extended, momentum building."
        for r in satellites.itertuples()
    ]
    return Buckets(anchors=anchors, satellites=satellites, watch=watch, extension=ext, notes=notes)
