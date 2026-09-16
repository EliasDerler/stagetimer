from datetime import datetime, time

from stagetimer.core import scheduler
from stagetimer.core.models import Event

EVENTS = [
    Event(name="Keynote", start_time=time(9, 0, 0), duration_seconds=1800),   # 09:00-09:30
    Event(name="Panel", start_time=time(9, 30, 0), duration_seconds=2700),    # 09:30-10:15
    Event(name="Lunch", start_time=time(11, 0, 0), duration_seconds=3600),    # 11:00-12:00, gap 10:15-11:00
]


def at(hh, mm, ss=0):
    return datetime(2026, 8, 11, hh, mm, ss)


# --- resolve_pending: only ever targets the first anchor in the whole list,
# regardless of how much wall-clock time has passed (there is no "current
# event" here at all — this function only answers "what's the next thing on
# deck, and how far away is it" for the state before anything has ever been
# manually started) -----------------------------------------------------------

def test_resolve_pending_empty_timetable():
    result = scheduler.resolve_pending(at(9, 0), [])
    assert result.mode == "EMPTY"
    assert result.index is None


def test_resolve_pending_no_anchors_anywhere():
    events = [
        Event(name="Welcome", start_time=None, duration_seconds=300),
        Event(name="Main Talk", start_time=None, duration_seconds=1800),
    ]
    result = scheduler.resolve_pending(at(9, 0), events)
    assert result.mode == "AWAITING_START"
    assert result.index is None


def test_resolve_pending_before_target_is_positive():
    result = scheduler.resolve_pending(at(8, 45), EVENTS)
    assert result.mode == "PENDING"
    assert result.index == 0
    assert result.remaining_seconds == 15 * 60


def test_resolve_pending_at_exact_target_is_zero():
    result = scheduler.resolve_pending(at(9, 0, 0), EVENTS)
    assert result.mode == "PENDING"
    assert result.index == 0
    assert result.remaining_seconds == 0


def test_resolve_pending_past_target_goes_negative():
    """The whole point of this feature: if nothing was ever started, the
    target time passing doesn't change the mode or index at all — it just
    means remaining_seconds keeps going, unboundedly negative."""
    result = scheduler.resolve_pending(at(9, 20, 0), EVENTS)
    assert result.mode == "PENDING"
    assert result.index == 0
    assert result.remaining_seconds == -20 * 60


def test_resolve_pending_well_past_target_still_pending_not_after_last():
    """No auto-completion either — even at 11pm on a 9am timetable, with
    nothing ever manually started, this is still just a very overdue
    PENDING against the first anchor, never AFTER_LAST."""
    result = scheduler.resolve_pending(at(23, 0), EVENTS)
    assert result.mode == "PENDING"
    assert result.index == 0


def test_resolve_pending_leading_unanchored_events_targets_first_real_anchor():
    events = [
        Event(name="Unreachable", start_time=None, duration_seconds=600),
        Event(name="Anchored", start_time=time(9, 0, 0), duration_seconds=600),
    ]
    result = scheduler.resolve_pending(at(8, 0), events)
    assert result.mode == "PENDING"
    assert result.index == 1
    assert result.remaining_seconds == 3600


def test_resolve_pending_single_event():
    single = [Event(name="Only", start_time=time(9, 0), duration_seconds=600)]
    result = scheduler.resolve_pending(at(8, 30), single)
    assert result.mode == "PENDING"
    assert result.index == 0
    assert result.remaining_seconds == 1800


# --- compute_effective_start_times: unchanged behavior, unchanged tests -----

def test_compute_effective_start_times_all_anchored():
    events = [
        Event(name="A", start_time=time(9, 0, 0), duration_seconds=600),
        Event(name="B", start_time=time(9, 30, 0), duration_seconds=600),
    ]
    assert scheduler.compute_effective_start_times(events) == [9 * 3600, 9 * 3600 + 30 * 60]


def test_compute_effective_start_times_chained():
    events = [
        Event(name="Welcome", start_time=time(9, 0, 0), duration_seconds=300),
        Event(name="Main Talk", start_time=None, duration_seconds=1800),
    ]
    assert scheduler.compute_effective_start_times(events) == [9 * 3600, 9 * 3600 + 300]


def test_compute_effective_start_times_unreachable_is_none():
    events = [
        Event(name="Unreachable", start_time=None, duration_seconds=600),
        Event(name="Anchored", start_time=time(9, 0, 0), duration_seconds=600),
    ]
    assert scheduler.compute_effective_start_times(events) == [None, 9 * 3600]


# --- seconds_since_midnight: newly-public helper, needed by state_machine.py

def test_seconds_since_midnight():
    assert scheduler.seconds_since_midnight(at(9, 30, 15)) == 9 * 3600 + 30 * 60 + 15
