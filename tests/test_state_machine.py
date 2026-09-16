from datetime import datetime, time, timedelta

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


# --- color state thresholds --------------------------------------------------

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


def test_color_state_overtime_below_zero():
    assert color_state_for(-1) == ColorState.OVERTIME


def test_color_state_overtime_stays_overtime_far_negative():
    assert color_state_for(-600) == ColorState.OVERTIME


# --- empty / awaiting-start / before-first (all wall-clock only, no operator
# action — none of this changes under the new model) -------------------------

def test_empty_timetable_mode():
    engine = make_engine([])
    engine.tick(at(9, 0))
    state = engine.get_display_state()
    assert state.mode == Mode.EMPTY
    assert state.current_name is None
    assert state.schedule_delay_seconds is None


def test_before_first_shows_countdown_to_start():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(8, 45))
    state = engine.get_display_state()
    assert state.mode == Mode.BEFORE_FIRST
    assert state.current_name is None
    assert state.next_name == "Keynote"
    assert state.remaining_seconds == 15 * 60
    assert state.color_state == ColorState.NORMAL


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
    assert state.schedule_delay_seconds is None


# --- no auto-start, ever: this is the core behavior change -------------------

def test_ticking_past_a_target_time_never_starts_anything():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(9, 10))  # well past Keynote's 9:00 target — nothing was started
    state = engine.get_display_state()
    assert state.mode == Mode.BEFORE_FIRST
    assert state.current_name is None


def test_pending_countdown_goes_negative_past_target_with_nothing_started():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(9, 20, 0))
    state = engine.get_display_state()
    assert state.mode == Mode.BEFORE_FIRST
    assert state.remaining_seconds == -20 * 60
    assert state.color_state == ColorState.OVERTIME


def test_never_reaches_after_last_without_ever_starting():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(23, 0))
    state = engine.get_display_state()
    assert state.mode == Mode.BEFORE_FIRST
    assert state.next_name == "Keynote"


def test_ticking_does_not_start_even_a_fully_unanchored_timetable():
    engine = make_engine(UNANCHORED_EVENTS)
    engine.tick(at(9, 0))
    engine.tick(at(10, 0))
    state = engine.get_display_state()
    assert state.mode == Mode.AWAITING_START
    assert state.current_name is None


# --- start() / skip_next(): the only ways an event becomes current ----------

def test_start_jumps_to_first_event_with_full_duration():
    engine = make_engine(UNANCHORED_EVENTS)
    engine.tick(at(9, 0))
    engine.start(now=at(9, 0))
    state = engine.get_display_state()
    assert state.mode == Mode.RUNNING
    assert state.current_name == "Welcome"
    assert state.remaining_seconds == 300


def test_start_does_nothing_on_empty_timetable():
    engine = make_engine([])
    engine.tick(at(9, 0))
    engine.start()
    state = engine.get_display_state()
    assert state.mode == Mode.EMPTY


def test_started_event_ticks_down_and_does_not_auto_advance():
    """Direct opposite of the old auto-advance-at-zero behavior: once
    started, an event that runs past its own duration just goes negative
    and stays current — no auto-advance to the next event, ever."""
    engine = make_engine(UNANCHORED_EVENTS)
    engine.tick(at(9, 0))
    engine.start(now=at(9, 0))
    engine.tick(at(9, 5, 1))  # 301s later, 1s past the 300s duration
    state = engine.get_display_state()
    assert state.current_name == "Welcome"
    assert state.mode == Mode.RUNNING
    assert state.remaining_seconds == -1
    assert state.color_state == ColorState.OVERTIME


def test_overtime_keeps_counting_the_longer_it_runs():
    engine = make_engine(UNANCHORED_EVENTS)
    engine.tick(at(9, 0))
    engine.start(now=at(9, 0))
    engine.tick(at(9, 5, 1))
    engine.tick(at(9, 5, 11))  # 10 more seconds
    state = engine.get_display_state()
    assert state.remaining_seconds == -11


def test_skip_next_from_pending_starts_the_first_event():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(9, 10, 0))  # well past Keynote's target, but nothing started
    engine.skip_next()
    state = engine.get_display_state()
    assert state.current_name == "Keynote"
    assert state.remaining_seconds == 1800


def test_skip_next_advances_from_current_to_next():
    engine = make_engine(TWO_EVENTS)
    engine.start(now=at(9, 0))
    engine.skip_next()
    state = engine.get_display_state()
    assert state.current_name == "Panel"
    assert state.remaining_seconds == 1200


def test_skip_next_at_last_event_goes_after_last():
    engine = make_engine(TWO_EVENTS)
    engine.start(now=at(9, 0))
    engine.skip_next()  # now on Panel (the last event)
    engine.skip_next()
    state = engine.get_display_state()
    assert state.mode == Mode.AFTER_LAST
    assert state.schedule_delay_seconds is None


def test_after_last_is_a_terminal_state_not_undone_by_further_ticks():
    """Regression test: AFTER_LAST must not silently flip back to RUNNING
    on the next tick. Before this was guarded, tick()'s generic 'something
    is current, decrement it' path didn't check mode at all, so the very
    next tick after reaching AFTER_LAST would decrement remaining_seconds
    (0 -> negative) and unconditionally reset mode to RUNNING."""
    engine = make_engine(TWO_EVENTS)
    engine.start(now=at(9, 0))
    engine.skip_next()  # Panel
    engine.skip_next()  # AFTER_LAST
    engine.tick(at(23, 0))  # a tick long after, at a wildly different time
    state = engine.get_display_state()
    assert state.mode == Mode.AFTER_LAST
    assert state.remaining_seconds == 0


def test_skipped_event_counts_down_independently_of_wallclock():
    engine = make_engine(TWO_EVENTS)
    engine.start(now=at(9, 0))
    engine.skip_next(now=at(9, 40, 0))  # now on Panel with full 1200s, regardless of wallclock
    engine.tick(at(9, 40, 5))
    state = engine.get_display_state()
    assert state.current_name == "Panel"
    assert state.remaining_seconds == 1200 - 5


# --- skip_prev(): always full duration, never touches delay -----------------

def test_skip_prev_jumps_to_full_duration_of_previous_event():
    engine = make_engine(TWO_EVENTS)
    engine.start(now=at(9, 0))
    engine.skip_next()  # on Panel
    engine.skip_prev()
    state = engine.get_display_state()
    assert state.current_name == "Keynote"
    assert state.remaining_seconds == 1800


def test_skip_prev_at_first_event_stays_on_first():
    engine = make_engine(TWO_EVENTS)
    engine.start(now=at(9, 0))
    engine.skip_prev()
    state = engine.get_display_state()
    assert state.current_name == "Keynote"


def test_skip_prev_from_pending_goes_to_first_event():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(9, 10, 0))  # pending, nothing started
    engine.skip_prev()
    state = engine.get_display_state()
    assert state.current_name == "Keynote"
    assert state.remaining_seconds == 1800


def test_skip_prev_does_not_shrink_even_a_shrinkable_event():
    events = [
        Event(name="A", start_time=time(9, 0, 0), duration_seconds=600),
        Event(
            name="Changeover", start_time=None, duration_seconds=300,
            shrinkable=True, min_duration_seconds=60,
        ),
    ]
    engine = make_engine(events)
    engine.start(now=at(9, 0, 0))
    engine.skip_next(now=at(9, 15, 0))  # enters Changeover 5 min late (300s) — floor clamps the 300s shrink to 60s
    assert engine.get_display_state().remaining_seconds == 60  # confirms the shrink actually happened

    engine.skip_prev()  # back to A, full duration, no shrink logic involved
    assert engine.get_display_state().current_name == "A"
    assert engine.get_display_state().remaining_seconds == 600

    engine.skip_prev()  # skip_prev() past the first event stays on the first event
    assert engine.get_display_state().current_name == "A"


# --- pause / resume -----------------------------------------------------------

def test_pause_freezes_remaining_time():
    engine = make_engine(TWO_EVENTS)
    engine.start(now=at(9, 0))
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
    engine.start(now=at(9, 0))
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


# --- adjust +/- (no longer clamped at zero — overtime is a normal state) ----

def test_adjust_adds_time():
    engine = make_engine(TWO_EVENTS)
    engine.start(now=at(9, 0))
    before = engine.get_display_state().remaining_seconds
    engine.adjust(120)
    after = engine.get_display_state().remaining_seconds
    assert after == before + 120


def test_adjust_can_push_into_overtime():
    engine = make_engine(TWO_EVENTS)
    engine.start(now=at(9, 0))
    engine.adjust(-100000)
    state = engine.get_display_state()
    assert state.remaining_seconds < 0
    assert state.color_state == ColorState.OVERTIME


def test_adjusted_event_ticks_down_independently():
    engine = make_engine(TWO_EVENTS)
    engine.start(now=at(9, 0))
    engine.adjust(60)
    remaining_after_adjust = engine.get_display_state().remaining_seconds
    engine.tick(at(9, 0, 10))
    state = engine.get_display_state()
    assert state.remaining_seconds == remaining_after_adjust - 10


# --- schedule delay: on-time / late / carries forward / gap absorption ------

def test_entering_on_time_shows_zero_delay():
    engine = make_engine(TWO_EVENTS)
    engine.start(now=at(9, 0, 0))
    state = engine.get_display_state()
    assert state.schedule_delay_seconds == 0


def test_entering_late_shows_positive_delay():
    engine = make_engine(TWO_EVENTS)
    engine.start(now=at(9, 3, 0))  # 3 minutes late to the 9:00 target
    state = engine.get_display_state()
    assert state.schedule_delay_seconds == 180


def test_delay_stays_flat_while_current_event_is_within_budget():
    engine = make_engine(TWO_EVENTS)
    engine.start(now=at(9, 3, 0))  # 3 min late entering
    engine.tick(at(9, 10, 0))  # 7 minutes into Keynote's 30-minute budget — not overrun
    state = engine.get_display_state()
    assert state.schedule_delay_seconds == 180


def test_delay_grows_live_once_current_event_is_in_overtime():
    engine = make_engine(TWO_EVENTS)
    engine.start(now=at(9, 0, 0))  # on time
    engine.tick(at(9, 30, 20))  # 20s into Keynote's own overtime
    state = engine.get_display_state()
    assert state.remaining_seconds == -20
    assert state.schedule_delay_seconds == 20


def test_delay_carries_forward_unshrunk_across_a_normal_event():
    """Entering B 3 minutes late and running it exactly its full planned
    duration reproduces the same 3-minute lateness entering C — target
    times are fixed, so lateness propagates automatically with no
    incremental bookkeeping needed."""
    events = [
        Event(name="A", start_time=time(9, 0, 0), duration_seconds=300),   # 9:00-9:05
        Event(name="B", start_time=None, duration_seconds=600),           # chains: 9:05-9:15
        Event(name="C", start_time=None, duration_seconds=300),           # chains: 9:15-9:20
    ]
    engine = make_engine(events)
    engine.start(now=at(9, 3, 0))  # A entered 3 min late
    engine.skip_next(now=at(9, 3, 0) + timedelta(seconds=300))  # B entered exactly 300s (A's planned duration) after A — i.e. A ran its full planned length, no more, no less
    state = engine.get_display_state()
    assert state.current_name == "B"
    assert state.schedule_delay_seconds == 180


def test_shrinkable_event_absorbs_delay_and_resolves_it():
    """Worked example from the design spec: entering a shrinkable event 3
    minutes late, with a floor that comfortably allows absorbing the full
    3 minutes, produces exactly 0 minutes late entering the event after —
    but NOT while the shrinkable event itself is still being displayed:
    per the design, schedule_delay_seconds stays flat at the delay
    frozen on entry until the operator actually advances past it (see the
    "Live cumulative delay" section of the design spec) — it doesn't
    live-drain as the shrunk countdown ticks down."""
    events = [
        Event(name="A", start_time=time(9, 0, 0), duration_seconds=300),  # 9:00-9:05
        Event(
            name="Changeover", start_time=None, duration_seconds=300,     # chains: 9:05-9:10
            shrinkable=True, min_duration_seconds=60,
        ),
        Event(name="C", start_time=None, duration_seconds=300),
    ]
    engine = make_engine(events)
    engine.start(now=at(9, 3, 0))  # A entered 3 min late
    engine.skip_next(now=at(9, 8, 0))  # Changeover entered 3 min late (A's target end was 9:05)
    state = engine.get_display_state()
    assert state.current_name == "Changeover"
    assert state.remaining_seconds == 120  # 300s planned - 180s absorbed = 120s, well above the 60s floor
    assert state.schedule_delay_seconds == 180  # still flat at the delay frozen on entry — not yet "resolved"

    # Advance to C exactly when Changeover's shrunk countdown reaches zero
    # (9:08:00 + 120s = 9:10:00) — chaining always uses Changeover's PLANNED
    # duration (300s) for C's target, so C's target_start is 9:05:00 + 300s
    # = 9:10:00, exactly matching this advance moment: the 3 minutes of
    # delay is now fully resolved, with no separate "credit" bookkeeping.
    engine.skip_next(now=at(9, 10, 0))
    state = engine.get_display_state()
    assert state.current_name == "C"
    assert state.schedule_delay_seconds == 0


def test_shrinkable_event_never_shrinks_when_entered_on_time():
    events = [
        Event(name="A", start_time=time(9, 0, 0), duration_seconds=300),
        Event(
            name="Changeover", start_time=None, duration_seconds=300,
            shrinkable=True, min_duration_seconds=60,
        ),
    ]
    engine = make_engine(events)
    engine.start(now=at(9, 0, 0))
    engine.skip_next(now=at(9, 5, 0))  # arrives exactly on the chained target
    state = engine.get_display_state()
    assert state.current_name == "Changeover"
    assert state.remaining_seconds == 300


def test_shrinkable_event_clamps_at_its_floor_when_delay_exceeds_capacity():
    events = [
        Event(name="A", start_time=time(9, 0, 0), duration_seconds=300),
        Event(
            name="Changeover", start_time=None, duration_seconds=300,
            shrinkable=True, min_duration_seconds=200,
        ),
    ]
    engine = make_engine(events)
    engine.start(now=at(9, 0, 0))
    engine.skip_next(now=at(9, 15, 0))  # 10 minutes late — far more than the 100s this can absorb
    state = engine.get_display_state()
    assert state.current_name == "Changeover"
    assert state.remaining_seconds == 200  # floor, not further compressed


def test_gap_absorbs_overrun_before_it_counts_as_delay():
    """A's own chained continuation would be 9:25 (9:00 start + 1500s), but
    B is anchored at 9:30 — 5 minutes of deliberate slack. Releasing A well
    past its own 9:25 chained end, right up to (but not past) B's own 9:30
    anchor, still shows zero delay: delay is always measured against the
    event being *entered*'s own target (B's 9:30), never the previous
    event's chained continuation, so the gap absorbs the overrun for free."""
    events = [
        Event(name="A", start_time=time(9, 0, 0), duration_seconds=1500),   # 9:00-9:25 (chained continuation)
        Event(name="B", start_time=time(9, 30, 0), duration_seconds=300),   # anchored 5 min later than A's chained end
    ]
    engine = make_engine(events)
    engine.start(now=at(9, 0, 0))
    engine.skip_next(now=at(9, 30, 0))  # A released well past its own 9:25 chained end, but exactly at B's 9:30 anchor
    state = engine.get_display_state()
    assert state.current_name == "B"
    assert state.schedule_delay_seconds == 0


def test_reset_schedule_zeroes_delay_mid_overtime():
    """The bug caught during spec review: resetting must zero the readout
    even when the *current* event's own countdown is already negative,
    not just the frozen entry-delay component."""
    engine = make_engine(TWO_EVENTS)
    engine.start(now=at(9, 0, 0))
    engine.tick(at(9, 33, 0))  # 3 minutes into overtime on Keynote
    assert engine.get_display_state().schedule_delay_seconds == 180

    engine.reset_schedule()
    state = engine.get_display_state()
    assert state.schedule_delay_seconds == 0
    assert state.remaining_seconds == -180  # the big clock's own overtime is untouched by the reset


def test_reset_schedule_offset_persists_across_a_transition():
    engine = make_engine(TWO_EVENTS)
    engine.start(now=at(9, 5, 0))  # 5 min late
    engine.reset_schedule()
    assert engine.get_display_state().schedule_delay_seconds == 0

    # Advance to Panel at exactly its own on-time target (9:30) — since 5
    # minutes were forgiven via the offset above, this reads as 5 minutes
    # *ahead* at the engine level. The display layer (a later task) clamps
    # "ahead" to a neutral "ON SCHEDULE" state rather than showing a
    # negative number — that clamping is display-only and doesn't apply to
    # the engine's own raw value, which is what this test asserts.
    engine.skip_next(now=at(9, 30, 0))
    state = engine.get_display_state()
    assert state.current_name == "Panel"
    assert state.schedule_delay_seconds == -300


def test_reset_schedule_during_pending_before_anything_started():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(9, 4, 0))  # 4 minutes late, nothing started yet
    assert engine.get_display_state().schedule_delay_seconds == 240

    engine.reset_schedule()
    engine.tick(at(9, 4, 0))
    state = engine.get_display_state()
    assert state.schedule_delay_seconds == 0


def test_reset_schedule_noop_when_nothing_to_reset():
    engine = make_engine([])
    engine.tick(at(9, 0))
    engine.reset_schedule()  # must not raise
    assert engine.get_display_state().schedule_delay_seconds is None


# --- descriptions (unchanged behavior, updated to use start() explicitly) ---

DESCRIBED_EVENTS = [
    Event(name="Keynote", start_time=time(9, 0, 0), duration_seconds=1800, description="Opening remarks"),
    Event(name="Panel", start_time=time(9, 30, 0), duration_seconds=1200, description="Q&A session"),
]


def test_display_state_carries_current_and_next_description_while_running():
    engine = make_engine(DESCRIBED_EVENTS)
    engine.start(now=at(9, 0, 0))
    state = engine.get_display_state()
    assert state.current_description == "Opening remarks"
    assert state.next_description == "Q&A session"


def test_display_state_next_description_before_first():
    engine = make_engine(DESCRIBED_EVENTS)
    engine.tick(at(8, 45))
    state = engine.get_display_state()
    assert state.current_description is None
    assert state.next_description == "Opening remarks"


def test_display_state_no_description_when_empty():
    engine = make_engine([])
    engine.tick(at(9, 0))
    state = engine.get_display_state()
    assert state.current_description is None
    assert state.next_description is None


def test_display_state_next_description_still_shows_while_deeply_pending():
    """Replaces the old 'no description after last' test — under the new
    model, ticking far into the future without ever starting is still
    BEFORE_FIRST (deeply overdue), not AFTER_LAST, so next_description is
    still populated, not None."""
    engine = make_engine(DESCRIBED_EVENTS)
    engine.tick(at(23, 0))
    state = engine.get_display_state()
    assert state.mode == Mode.BEFORE_FIRST
    assert state.next_description == "Opening remarks"


def test_display_state_no_description_after_explicitly_reaching_after_last():
    engine = make_engine(DESCRIBED_EVENTS)
    engine.start(now=at(9, 0, 0))
    engine.skip_next()  # Panel
    engine.skip_next()  # AFTER_LAST
    state = engine.get_display_state()
    assert state.mode == Mode.AFTER_LAST
    assert state.current_description is None
    assert state.next_description is None


# --- schedule overview ---------------------------------------------------------

def test_schedule_overview_empty_timetable():
    engine = make_engine([])
    engine.tick(at(9, 0))
    assert engine.get_schedule_overview() == []


def test_schedule_overview_marks_current_row_while_running():
    engine = make_engine(TWO_EVENTS)
    engine.start(now=at(9, 0, 0))
    rows = engine.get_schedule_overview()
    assert [r.name for r in rows] == ["Keynote", "Panel"]
    assert rows[0].is_current is True
    assert rows[1].is_current is False
    assert rows[0].effective_start_seconds == 9 * 3600
    assert rows[0].duration_seconds == 1800


def test_schedule_overview_marks_current_row_while_paused():
    engine = make_engine(TWO_EVENTS)
    engine.start(now=at(9, 0, 0))
    engine.pause()
    rows = engine.get_schedule_overview()
    assert rows[0].is_current is True


def test_schedule_overview_shows_planned_duration_even_when_shrunk():
    """The overview is a reference view of the plan — it never reflects a
    live shrink applied to whichever event happens to be current."""
    events = [
        Event(name="A", start_time=time(9, 0, 0), duration_seconds=300),
        Event(
            name="Changeover", start_time=None, duration_seconds=300,
            shrinkable=True, min_duration_seconds=60,
        ),
    ]
    engine = make_engine(events)
    engine.start(now=at(9, 0, 0))
    engine.skip_next(now=at(9, 15, 0))  # forces a big shrink
    rows = engine.get_schedule_overview()
    changeover_row = rows[1]
    assert changeover_row.duration_seconds == 300  # planned, not the shrunk live value


def test_schedule_overview_no_current_row_before_anything_starts():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(8, 45))
    rows = engine.get_schedule_overview()
    assert all(not r.is_current for r in rows)


def test_schedule_overview_no_current_row_awaiting_start():
    engine = make_engine(UNANCHORED_EVENTS)
    engine.tick(at(9, 0))
    rows = engine.get_schedule_overview()
    assert all(not r.is_current for r in rows)
    assert rows[0].effective_start_seconds is None
