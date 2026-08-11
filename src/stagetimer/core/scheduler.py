from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

from stagetimer.core.models import Event


def _seconds_since_midnight(dt: datetime) -> int:
    return dt.hour * 3600 + dt.minute * 60 + dt.second


def _time_to_seconds(t: time) -> int:
    return t.hour * 3600 + t.minute * 60 + t.second


@dataclass(frozen=True)
class Resolution:
    """Result of resolving 'what should be on screen right now' from pure
    wall-clock math, with no knowledge of pause/skip/adjust overrides."""

    mode: str  # "EMPTY" | "AWAITING_START" | "BEFORE_FIRST" | "RUNNING" | "AFTER_LAST"
    index: int | None
    remaining_seconds: int


@dataclass(frozen=True)
class _Effective:
    index: int
    start: int | None
    end: int | None


def _compute_effective_times(events: list[Event]) -> list[_Effective]:
    """Compute each event's effective (start, end) in seconds-since-midnight.

    An event with an explicit `start_time` anchors the clock at that time.
    An event with no `start_time` inherits its start from the previous
    event's effective end (chained). An event has no effective start at all
    if it has no `start_time` of its own and nothing before it in the list
    established an anchor yet.
    """
    effective: list[_Effective] = []
    cursor: int | None = None
    for i, event in enumerate(events):
        if event.start_time is not None:
            cursor = _time_to_seconds(event.start_time)
        start = cursor
        if start is None:
            end = None
        else:
            end = start + event.duration_seconds
            cursor = end
        effective.append(_Effective(index=i, start=start, end=end))
    return effective


def resolve(now: datetime, events: list[Event]) -> Resolution:
    """Resolve the current/next event purely from wall-clock time.

    `events` is read in list order; events without an explicit `start_time`
    chain off the effective end of the event before them (see
    `_compute_effective_times`).

    - EMPTY: no events configured.
    - AWAITING_START: events exist but none has an effective start (no event
      anywhere in the list has a `start_time`, directly or via chaining) —
      only the Start button or Skip Next/Prev can begin playback.
    - BEFORE_FIRST: `now` is before the next anchored event's effective
      start (covers both "before the first event of the day" and any gap
      between two scheduled events). `index` points at that upcoming event.
    - RUNNING: `now` falls within an anchored event's
      [effective_start, effective_end) range.
    - AFTER_LAST: `now` is at or past the effective end of the last anchored
      event in the chain.
    """
    if not events:
        return Resolution(mode="EMPTY", index=None, remaining_seconds=0)

    effective = _compute_effective_times(events)
    anchored = [e for e in effective if e.start is not None]
    if not anchored:
        return Resolution(mode="AWAITING_START", index=None, remaining_seconds=0)

    now_s = _seconds_since_midnight(now)

    last = anchored[-1]
    if now_s >= last.end:
        return Resolution(mode="AFTER_LAST", index=last.index, remaining_seconds=0)

    for e in anchored:
        if e.start <= now_s < e.end:
            return Resolution(mode="RUNNING", index=e.index, remaining_seconds=e.end - now_s)
        if now_s < e.start:
            return Resolution(mode="BEFORE_FIRST", index=e.index, remaining_seconds=e.start - now_s)

    # Unreachable given the AFTER_LAST check above, but keeps mypy/pyright happy.
    return Resolution(mode="AFTER_LAST", index=last.index, remaining_seconds=0)
