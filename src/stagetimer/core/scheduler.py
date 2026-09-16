from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

from stagetimer.core.models import Event


def seconds_since_midnight(dt: datetime) -> int:
    return dt.hour * 3600 + dt.minute * 60 + dt.second


def _time_to_seconds(t: time) -> int:
    return t.hour * 3600 + t.minute * 60 + t.second


@dataclass(frozen=True)
class PendingResolution:
    """Result of resolving 'is there a target ahead, and how far away is
    it' while nothing has ever been manually started (TimerEngine's
    `_current_index is None`). Unlike the old `resolve()` this replaced,
    `remaining_seconds` can go negative — the target time passing implies
    nothing automatically; it's purely informational, always relative to
    the *first* anchored event in the whole list (there is no notion of
    "current" here at all)."""

    mode: str  # "EMPTY" | "AWAITING_START" | "PENDING"
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


def compute_effective_start_times(events: list[Event]) -> list[int | None]:
    """Public wrapper around `_compute_effective_times` exposing just the
    effective start (seconds since midnight, or None if unreachable by wall
    clock) for each event, aligned by index with `events`. Used by the UI to
    show a clock time for every row in a full-timetable overview, including
    events that chain off a previous event's end rather than having their
    own `start_time`."""
    return [e.start for e in _compute_effective_times(events)]


def resolve_pending(now: datetime, events: list[Event]) -> PendingResolution:
    """Resolve 'what's next, and how far away' purely from wall-clock time,
    for use only while nothing has ever been manually started.

    - EMPTY: no events configured.
    - AWAITING_START: events exist but none has an effective start (no event
      anywhere in the list has a `start_time`, directly or via chaining).
    - PENDING: the first anchored event in the list is the target; `index`
      points at it and `remaining_seconds` is `target_start - now`, which
      can be negative if `now` has already passed it — this function never
      reports anything other than PENDING once any anchor exists, no matter
      how far past it `now` is, since nothing here decides what's "current"
      or "done" — only `TimerEngine`'s own operator-driven state does that.
    """
    if not events:
        return PendingResolution(mode="EMPTY", index=None, remaining_seconds=0)

    effective = _compute_effective_times(events)
    anchored = [e for e in effective if e.start is not None]
    if not anchored:
        return PendingResolution(mode="AWAITING_START", index=None, remaining_seconds=0)

    now_s = seconds_since_midnight(now)
    first = anchored[0]
    return PendingResolution(mode="PENDING", index=first.index, remaining_seconds=first.start - now_s)
