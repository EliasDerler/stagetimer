from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from stagetimer.core.models import Event


def _seconds_since_midnight(dt: datetime) -> int:
    return dt.hour * 3600 + dt.minute * 60 + dt.second


def _start_seconds(event: Event) -> int:
    t = event.start_time
    return t.hour * 3600 + t.minute * 60 + t.second


@dataclass(frozen=True)
class Resolution:
    """Result of resolving 'what should be on screen right now' from pure
    wall-clock math, with no knowledge of pause/skip/adjust overrides."""

    mode: str  # "EMPTY" | "BEFORE_FIRST" | "RUNNING" | "AFTER_LAST"
    index: int | None
    remaining_seconds: int


def resolve(now: datetime, events: list[Event]) -> Resolution:
    """Resolve the current/next event purely from wall-clock time.

    `events` must already be in chronological (start_time) order.

    - EMPTY: no events configured.
    - BEFORE_FIRST: `now` is before the next upcoming event's start (this
      covers both "before the first event of the day" and any gap between
      two scheduled events). `index` points at that upcoming event.
    - RUNNING: `now` falls within an event's [start, start+duration) range.
    - AFTER_LAST: `now` is at or past the end of the last event.
    """
    if not events:
        return Resolution(mode="EMPTY", index=None, remaining_seconds=0)

    now_s = _seconds_since_midnight(now)

    last = events[-1]
    if now_s >= last.end_time_seconds:
        return Resolution(mode="AFTER_LAST", index=len(events) - 1, remaining_seconds=0)

    for i, event in enumerate(events):
        start = _start_seconds(event)
        end = event.end_time_seconds
        if start <= now_s < end:
            return Resolution(mode="RUNNING", index=i, remaining_seconds=end - now_s)
        if now_s < start:
            return Resolution(mode="BEFORE_FIRST", index=i, remaining_seconds=start - now_s)

    # Unreachable given the AFTER_LAST check above, but keeps mypy/pyright happy.
    return Resolution(mode="AFTER_LAST", index=len(events) - 1, remaining_seconds=0)
