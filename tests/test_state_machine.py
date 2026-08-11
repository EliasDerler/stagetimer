from datetime import datetime, time

from stagetimer.core.models import Event, Timetable
from stagetimer.core.state_machine import ColorState, Mode, TimerEngine, color_state_for


def at(hh, mm, ss=0):
    return datetime(2026, 8, 11, hh, mm, ss)


def make_engine(events):
    return TimerEngine(Timetable(events=events))


TWO_EVENTS = [
    Event(name="Keynote", start_time=time(9, 0, 0), duration_seconds=1800),  # 09:00-09:30
    Event(name="Panel", start_time=time(9, 30, 0), duration_seconds=1200),   # 09:30-09:50
]


# --- color state thresholds -------------------------------------------------

def test_color_state_normal_above_5_min():
    assert color_state_for(301) == ColorState.NORMAL


def test_color_state_yellow_at_5_min():
    assert color_state_for(300) == ColorState.WARNING_YELLOW


def test_color_state_red_at_3_min():
    assert color_state_for(180) == ColorState.DANGER_RED


def test_color_state_flash_at_1_min():
    assert color_state_for(60) == ColorState.FLASH


def test_color_state_flash_at_zero():
    assert color_state_for(0) == ColorState.FLASH


# --- empty / before-first / after-last modes --------------------------------

def test_empty_timetable_mode():
    engine = make_engine([])
    engine.tick(at(9, 0))
    state = engine.get_display_state()
    assert state.mode == Mode.EMPTY
    assert state.current_name is None


def test_before_first_shows_countdown_to_start():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(8, 45))
    state = engine.get_display_state()
    assert state.mode == Mode.BEFORE_FIRST
    assert state.current_name is None
    assert state.next_name == "Keynote"
    assert state.remaining_seconds == 15 * 60


def test_after_last_no_wraparound():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(23, 0))
    state = engine.get_display_state()
    assert state.mode == Mode.AFTER_LAST
    assert state.current_name is None
    assert state.next_name is None


# --- wall-clock-driven running state ----------------------------------------

def test_running_reflects_wall_clock_when_not_overridden():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(9, 10))
    state = engine.get_display_state()
    assert state.mode == Mode.RUNNING
    assert state.current_name == "Keynote"
    assert state.remaining_seconds == 20 * 60
    assert state.next_name == "Panel"
    assert state.next_duration_seconds == 1200


def test_auto_advances_across_wallclock_boundary():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(9, 29, 59))
    assert engine.get_display_state().current_name == "Keynote"
    engine.tick(at(9, 30, 0))
    state = engine.get_display_state()
    assert state.current_name == "Panel"
    assert state.mode == Mode.RUNNING


# --- pause / resume ----------------------------------------------------------

def test_pause_freezes_remaining_time():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(9, 10, 0))
    engine.pause()
    state = engine.get_display_state()
    assert state.is_paused is True
    assert state.mode == Mode.PAUSED
    remaining_at_pause = state.remaining_seconds

    engine.tick(at(9, 15, 0))  # wall clock moves, but engine is paused
    state = engine.get_display_state()
    assert state.remaining_seconds == remaining_at_pause


def test_resume_continues_from_frozen_value():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(9, 10, 0))
    engine.pause()
    engine.tick(at(9, 15, 0))
    remaining_at_pause = engine.get_display_state().remaining_seconds

    engine.resume()
    engine.tick(at(9, 15, 0))
    engine.tick(at(9, 15, 10))
    state = engine.get_display_state()
    assert state.remaining_seconds == remaining_at_pause - 10
    assert state.is_paused is False


# --- skip next / prev --------------------------------------------------------

def test_skip_next_jumps_to_full_duration_of_next_event():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(9, 10, 0))
    engine.skip_next()
    state = engine.get_display_state()
    assert state.current_name == "Panel"
    assert state.remaining_seconds == 1200


def test_skip_next_at_last_event_goes_after_last():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(9, 40, 0))  # already in Panel (index 1, the last event)
    engine.skip_next()
    state = engine.get_display_state()
    assert state.mode == Mode.AFTER_LAST


def test_skip_prev_jumps_to_full_duration_of_previous_event():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(9, 40, 0))  # in Panel
    engine.skip_prev()
    state = engine.get_display_state()
    assert state.current_name == "Keynote"
    assert state.remaining_seconds == 1800


def test_skip_prev_at_first_event_stays_on_first():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(9, 10, 0))
    engine.skip_prev()
    state = engine.get_display_state()
    assert state.current_name == "Keynote"


def test_skipped_event_counts_down_independently_of_wallclock():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(9, 10, 0))
    engine.skip_next()  # now on Panel with full 1200s, regardless of wallclock
    engine.tick(at(9, 10, 5))
    state = engine.get_display_state()
    assert state.current_name == "Panel"
    assert state.remaining_seconds == 1200 - 5


# --- adjust +/- ---------------------------------------------------------------

def test_adjust_adds_time():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(9, 10, 0))
    before = engine.get_display_state().remaining_seconds
    engine.adjust(120)
    after = engine.get_display_state().remaining_seconds
    assert after == before + 120


def test_adjust_subtracts_time_clamped_at_zero():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(9, 10, 0))
    engine.adjust(-100000)
    state = engine.get_display_state()
    assert state.remaining_seconds == 0


def test_adjusted_event_ticks_down_independently():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(9, 10, 0))
    engine.adjust(60)
    remaining_after_adjust = engine.get_display_state().remaining_seconds
    engine.tick(at(9, 10, 10))
    state = engine.get_display_state()
    assert state.remaining_seconds == remaining_after_adjust - 10


# --- auto-advance on override reaching zero -----------------------------------

def test_overridden_countdown_auto_advances_at_zero():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(9, 10, 0))
    engine.adjust(-1195)  # remaining was 1200s (20 min); drop to 5s
    state = engine.get_display_state()
    assert state.remaining_seconds == 5

    engine.tick(at(9, 10, 10))  # 10s elapse, more than the 5s left -> advance
    state = engine.get_display_state()
    assert state.current_name == "Panel"
    assert state.mode == Mode.RUNNING


def test_overridden_countdown_auto_advances_past_last_to_after_last():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(9, 40, 0))  # in Panel (last event)
    engine.adjust(-1195)  # 1200 - 1195 = 5s left in Panel
    engine.tick(at(9, 40, 10))
    state = engine.get_display_state()
    assert state.mode == Mode.AFTER_LAST


# --- awaiting start / optional start times -----------------------------------

UNANCHORED_EVENTS = [
    Event(name="Welcome", start_time=None, duration_seconds=300),
    Event(name="Main Talk", start_time=None, duration_seconds=1800),
]


def test_awaiting_start_mode_with_no_anchors():
    engine = make_engine(UNANCHORED_EVENTS)
    engine.tick(at(9, 0))
    state = engine.get_display_state()
    assert state.mode == Mode.AWAITING_START
    assert state.current_name is None
    assert state.next_name == "Welcome"
    assert state.next_duration_seconds == 300


def test_start_jumps_to_first_event_with_full_duration():
    engine = make_engine(UNANCHORED_EVENTS)
    engine.tick(at(9, 0))
    engine.start()
    state = engine.get_display_state()
    assert state.mode == Mode.RUNNING
    assert state.current_name == "Welcome"
    assert state.remaining_seconds == 300


def test_started_event_ticks_down_and_auto_advances():
    engine = make_engine(UNANCHORED_EVENTS)
    engine.tick(at(9, 0))
    engine.start()
    engine.tick(at(9, 5, 1))  # 301s later, > 300s duration -> auto-advance
    state = engine.get_display_state()
    assert state.current_name == "Main Talk"
    assert state.mode == Mode.RUNNING


def test_start_does_nothing_on_empty_timetable():
    engine = make_engine([])
    engine.tick(at(9, 0))
    engine.start()
    state = engine.get_display_state()
    assert state.mode == Mode.EMPTY


def test_chained_events_without_start_time_resolve_via_wallclock():
    events = [
        Event(name="Welcome", start_time=time(9, 0, 0), duration_seconds=300),
        Event(name="Main Talk", start_time=None, duration_seconds=1800),
    ]
    engine = make_engine(events)
    engine.tick(at(9, 10))
    state = engine.get_display_state()
    assert state.mode == Mode.RUNNING
    assert state.current_name == "Main Talk"
    assert state.remaining_seconds == 25 * 60
