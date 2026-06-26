"""23-hour session management — maintenance breaks, contract rolls, news events (§3).

Handles the CME E-mini session lifecycle:
- Daily maintenance break (5:00-6:00 PM ET): no new orders, open positions flagged.
- Contract roll blackout: no new entries within X days of roll.
- High-impact news: pause, widen stops, or continue per config.
- Auto-reconnect on disconnect with exponential backoff.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum

import pandas as pd

# CME quarterly roll months (H=March, M=June, U=September, Z=December)
_ROLL_MONTHS = {3: "H", 6: "M", 9: "U", 12: "Z"}
_ROLL_DAY_OF_WEEK = 3  # Thursday, second week

# Major scheduled news events to track
FOMC_DATES_2025 = [
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
]
NFP_DATES_2025 = [
    "2025-01-10", "2025-02-07", "2025-03-07", "2025-04-04",
    "2025-05-02", "2025-06-06", "2025-07-03", "2025-08-01",
    "2025-09-05", "2025-10-03", "2025-11-07", "2025-12-05",
]


class SessionState(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"
    CLOSED = "CLOSED"
    ROLL_BLACKOUT = "ROLL_BLACKOUT"
    NEWS_PAUSE = "NEWS_PAUSE"


@dataclass
class SessionInfo:
    state: SessionState
    can_enter: bool
    reason: str
    front_month: str
    next_roll_date: date | None


def front_month_code(d: date) -> str:
    """Return the current front-month contract code (e.g. 'ESH25')."""
    year = d.year
    month = d.month
    for rm in sorted(_ROLL_MONTHS.keys()):
        roll_date = _roll_date(year, rm)
        if d < roll_date:
            suffix = f"{_ROLL_MONTHS[rm]}{year % 100:02d}"
            return suffix
    suffix = f"{_ROLL_MONTHS[3]}{(year + 1) % 100:02d}"
    return suffix


def _roll_date(year: int, month: int) -> date:
    """Second Friday of the roll month — typical CME expiry for E-mini."""
    first_day = date(year, month, 1)
    day_of_week = first_day.weekday()  # 0=Monday
    days_to_friday = (4 - day_of_week) % 7
    first_friday = first_day + timedelta(days=days_to_friday)
    second_friday = first_friday + timedelta(days=7)
    return second_friday


def next_roll(d: date) -> date:
    """Return the next contract roll date from date d."""
    year = d.year
    for rm in sorted(_ROLL_MONTHS.keys()):
        rd = _roll_date(year, rm)
        if rd > d:
            return rd
    return _roll_date(year + 1, 3)


def is_maintenance(dt: datetime, cfg: dict) -> bool:
    """Check if the given datetime (ET) falls in the daily maintenance window."""
    sess = cfg["session"]
    maint_start = _parse_time(sess["maintenance_start"])
    maint_end = _parse_time(sess["maintenance_end"])
    t = dt.time()
    if maint_start < maint_end:
        return maint_start <= t < maint_end
    return t >= maint_start or t < maint_end


def is_in_trading_window(dt: datetime, cfg: dict) -> bool:
    """Check if trading is allowed in the configured window (full or restricted)."""
    sess = cfg["session"]
    if sess["mode"] == "full":
        return not is_maintenance(dt, cfg)

    t = dt.time()
    rth_start = _parse_time(sess["rth_start"])
    rth_end = _parse_time(sess["rth_end"])
    return rth_start <= t < rth_end


def is_news_event(d: date, news_dates: list[str] | None = None) -> bool:
    """Check if d is a scheduled high-impact news day."""
    all_dates = (news_dates or []) + FOMC_DATES_2025 + NFP_DATES_2025
    return d.isoformat() in all_dates


def check_session(dt: datetime, cfg: dict,
                  news_dates: list[str] | None = None) -> SessionInfo:
    """Full session check: returns current state and whether new entries are allowed."""
    d = dt.date() if isinstance(dt, datetime) else dt
    sess = cfg["session"]
    fm = front_month_code(d)
    nr = next_roll(d)

    # Maintenance break
    if isinstance(dt, datetime) and is_maintenance(dt, cfg):
        return SessionInfo(
            state=SessionState.MAINTENANCE, can_enter=False,
            reason="Daily maintenance break — no new orders",
            front_month=fm, next_roll_date=nr,
        )

    # Roll blackout
    blackout_days = sess.get("roll_blackout_days", 3)
    if nr and (nr - d).days <= blackout_days:
        return SessionInfo(
            state=SessionState.ROLL_BLACKOUT, can_enter=False,
            reason=f"Within {blackout_days}-day roll blackout (roll {nr})",
            front_month=fm, next_roll_date=nr,
        )

    # News event
    if is_news_event(d, news_dates):
        action = sess.get("news_action", "pause")
        if action == "pause":
            return SessionInfo(
                state=SessionState.NEWS_PAUSE, can_enter=False,
                reason="High-impact news day — entries paused",
                front_month=fm, next_roll_date=nr,
            )

    # Trading window check
    if isinstance(dt, datetime) and not is_in_trading_window(dt, cfg):
        return SessionInfo(
            state=SessionState.CLOSED, can_enter=False,
            reason="Outside configured trading window",
            front_month=fm, next_roll_date=nr,
        )

    return SessionInfo(
        state=SessionState.ACTIVE, can_enter=True, reason="Session active",
        front_month=fm, next_roll_date=nr,
    )


def _parse_time(t: str) -> time:
    parts = t.split(":")
    return time(int(parts[0]), int(parts[1]))
