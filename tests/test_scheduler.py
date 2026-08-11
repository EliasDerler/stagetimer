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


def test_empty_timetable():
    result = scheduler.resolve(at(9, 0), [])
    assert result.mode == "EMPTY"
    assert result.index is None


def test_before_first_event():
    result = scheduler.resolve(at(8, 45), EVENTS)
    assert result.mode == "BEFORE_FIRST"
    assert result.index == 0
    assert result.remaining_seconds == 15 * 60


def test_running_first_event():
    result = scheduler.resolve(at(9, 10), EVENTS)
    assert result.mode == "RUNNING"
    assert result.index == 0
    assert result.remaining_seconds == 20 * 60


def test_running_at_exact_start_boundary():
    result = scheduler.resolve(at(9, 30, 0), EVENTS)
    assert result.mode == "RUNNING"
    assert result.index == 1


def test_running_second_event():
    result = scheduler.resolve(at(10, 0), EVENTS)
    assert result.mode == "RUNNING"
    assert result.index == 1
    assert result.remaining_seconds == 15 * 60


def test_gap_between_events_treated_as_before_next():
    result = scheduler.resolve(at(10, 30), EVENTS)
    assert result.mode == "BEFORE_FIRST"
    assert result.index == 2
    assert result.remaining_seconds == 30 * 60


def test_running_last_event():
    result = scheduler.resolve(at(11, 30), EVENTS)
    assert result.mode == "RUNNING"
    assert result.index == 2


def test_after_last_event_at_exact_end():
    result = scheduler.resolve(at(12, 0, 0), EVENTS)
    assert result.mode == "AFTER_LAST"
    assert result.index == 2


def test_after_last_event_well_past_end():
    result = scheduler.resolve(at(23, 0), EVENTS)
    assert result.mode == "AFTER_LAST"
    assert result.index == 2


def test_single_event_before():
    single = [Event(name="Only", start_time=time(9, 0), duration_seconds=600)]
    result = scheduler.resolve(at(8, 0), single)
    assert result.mode == "BEFORE_FIRST"
    assert result.index == 0


def test_single_event_running():
    single = [Event(name="Only", start_time=time(9, 0), duration_seconds=600)]
    result = scheduler.resolve(at(9, 5), single)
    assert result.mode == "RUNNING"
    assert result.index == 0


def test_single_event_after():
    single = [Event(name="Only", start_time=time(9, 0), duration_seconds=600)]
    result = scheduler.resolve(at(9, 20), single)
    assert result.mode == "AFTER_LAST"
    assert result.index == 0


def test_no_events_have_start_time_awaiting_start():
    events = [
        Event(name="Welcome", start_time=None, duration_seconds=300),
        Event(name="Main Talk", start_time=None, duration_seconds=1800),
    ]
    result = scheduler.resolve(at(9, 0), events)
    assert result.mode == "AWAITING_START"
    assert result.index is None


def test_only_first_event_anchored_rest_chain():
    events = [
        Event(name="Welcome", start_time=time(9, 0, 0), duration_seconds=300),   # 9:00-9:05
        Event(name="Main Talk", start_time=None, duration_seconds=1800),         # chains: 9:05-9:35
        Event(name="Q&A", start_time=None, duration_seconds=600),                # chains: 9:35-9:45
    ]
    before = scheduler.resolve(at(8, 0), events)
    assert before.mode == "BEFORE_FIRST"
    assert before.index == 0
    assert before.remaining_seconds == 3600

    during_talk = scheduler.resolve(at(9, 10), events)
    assert during_talk.mode == "RUNNING"
    assert during_talk.index == 1
    assert during_talk.remaining_seconds == 25 * 60

    during_qa = scheduler.resolve(at(9, 40), events)
    assert during_qa.mode == "RUNNING"
    assert during_qa.index == 2

    after = scheduler.resolve(at(10, 0), events)
    assert after.mode == "AFTER_LAST"
    assert after.index == 2


def test_mid_list_anchor_resets_chain():
    events = [
        Event(name="A", start_time=time(9, 0, 0), duration_seconds=600),    # 9:00-9:10
        Event(name="B", start_time=None, duration_seconds=600),             # chains: 9:10-9:20
        Event(name="C", start_time=time(10, 0, 0), duration_seconds=600),   # anchor resets: 10:00-10:10
        Event(name="D", start_time=None, duration_seconds=600),             # chains off C: 10:10-10:20
    ]
    gap = scheduler.resolve(at(9, 30), events)
    assert gap.mode == "BEFORE_FIRST"
    assert gap.index == 2
    assert gap.remaining_seconds == 30 * 60

    during_d = scheduler.resolve(at(10, 15), events)
    assert during_d.mode == "RUNNING"
    assert during_d.index == 3
    assert during_d.remaining_seconds == 5 * 60


def test_leading_unanchored_events_are_unreachable_by_wallclock():
    events = [
        Event(name="Unreachable", start_time=None, duration_seconds=600),
        Event(name="Anchored", start_time=time(9, 0, 0), duration_seconds=600),
    ]
    result = scheduler.resolve(at(8, 0), events)
    assert result.mode == "BEFORE_FIRST"
    assert result.index == 1
