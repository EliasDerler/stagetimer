from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from stagetimer.core import scheduler
from stagetimer.core.models import Event, Timetable

YELLOW_THRESHOLD_SECONDS = 5 * 60
RED_THRESHOLD_SECONDS = 3 * 60
FLASH_THRESHOLD_SECONDS = 1 * 60


class Mode(Enum):
    EMPTY = "EMPTY"
    AWAITING_START = "AWAITING_START"
    BEFORE_FIRST = "BEFORE_FIRST"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    AFTER_LAST = "AFTER_LAST"


class ColorState(Enum):
    NORMAL = "NORMAL"
    WARNING_YELLOW = "WARNING_YELLOW"
    DANGER_RED = "DANGER_RED"
    FLASH = "FLASH"
    OVERTIME = "OVERTIME"


def color_state_for(remaining_seconds: float) -> ColorState:
    if remaining_seconds < 0:
        return ColorState.OVERTIME
    if remaining_seconds <= FLASH_THRESHOLD_SECONDS:
        return ColorState.FLASH
    if remaining_seconds <= RED_THRESHOLD_SECONDS:
        return ColorState.DANGER_RED
    if remaining_seconds <= YELLOW_THRESHOLD_SECONDS:
        return ColorState.WARNING_YELLOW
    return ColorState.NORMAL


@dataclass(frozen=True)
class DisplayState:
    mode: Mode
    current_name: str | None
    remaining_seconds: float
    next_name: str | None
    next_duration_seconds: int | None
    color_state: ColorState
    is_paused: bool
    current_description: str | None = None
    next_description: str | None = None
    schedule_delay_seconds: float | None = None


@dataclass(frozen=True)
class ScheduleRow:
    name: str
    duration_seconds: int
    effective_start_seconds: int | None
    is_current: bool


class TimerEngine:
    """Owns the live playback state for the currently-showing event.

    Fully operator-driven: nothing ever starts or advances automatically.
    `_current_index` only changes via `start()`/`skip_next()`/`skip_prev()`.
    Every tick just decrements whatever's current by elapsed wall-clock
    time, unclamped — an event that isn't manually advanced past zero goes
    negative (overtime) and stays there until the operator acts.

    Before anything has ever been started (`_current_index is None`), the
    engine still surfaces a live, wall-clock-derived countdown to the first
    anchored event via `scheduler.resolve_pending()` — but that countdown
    never itself triggers a transition into RUNNING; it can go negative too.
    """

    def __init__(self, timetable: Timetable):
        self._events: list[Event] = []
        self._current_index: int | None = None
        self._pending_index: int | None = None
        self._remaining_seconds: float = 0.0
        self._is_paused: bool = False
        self._mode: Mode = Mode.EMPTY
        self._last_tick: datetime | None = None
        self._delay_at_entry: float = 0.0
        self._delay_reset_offset: float = 0.0
        self.set_timetable(timetable)

    def set_timetable(self, timetable: Timetable) -> None:
        self.timetable = timetable
        self._events = timetable.sorted_events()
        self._current_index = None
        self._pending_index = None
        self._remaining_seconds = 0.0
        self._is_paused = False
        self._mode = Mode.EMPTY
        self._last_tick = None
        self._delay_at_entry = 0.0
        self._delay_reset_offset = 0.0

    def tick(self, now: datetime) -> None:
        if not self._events:
            self._mode = Mode.EMPTY
            self._current_index = None
            self._pending_index = None
            self._last_tick = now
            return

        if self._current_index is None:
            self._tick_pending(now)
            return

        if self._mode == Mode.AFTER_LAST:
            # Terminal state, reached only by an explicit skip_next() past
            # the last event (never by ticking alone). Without this guard,
            # the very next tick would fall through to the generic
            # "something is current" path below, decrement _remaining_seconds
            # (which is 0, so it'd go negative), and unconditionally set
            # mode back to RUNNING — silently undoing AFTER_LAST almost
            # immediately (the main display ticks every 200ms). Just keep
            # _last_tick fresh so a later skip_prev() out of this state
            # doesn't inherit a large stale gap.
            self._last_tick = now
            return

        if self._is_paused:
            self._last_tick = now
            return

        if self._last_tick is not None:
            elapsed = (now - self._last_tick).total_seconds()
            self._remaining_seconds -= elapsed
        self._last_tick = now
        self._mode = Mode.RUNNING

    def _tick_pending(self, now: datetime) -> None:
        resolution = scheduler.resolve_pending(now, self._events)
        self._last_tick = now
        self._pending_index = resolution.index
        if resolution.mode == "EMPTY":
            self._mode = Mode.EMPTY
        elif resolution.mode == "AWAITING_START":
            self._mode = Mode.AWAITING_START
        else:  # "PENDING"
            self._mode = Mode.BEFORE_FIRST
            self._remaining_seconds = resolution.remaining_seconds

    def start(self, now: datetime | None = None) -> None:
        """Jump straight to the first event and begin playing it — the
        only way the very first event of the day ever becomes current,
        since nothing does this automatically. `now` is exposed only for
        deterministic testing; real callers (buttons, shortcuts) omit it."""
        if not self._events:
            return
        self._advance_to(0, now)

    def skip_next(self, now: datetime | None = None) -> None:
        """`now` is exposed only for deterministic testing, same as
        `start()` — real callers (buttons, shortcuts) omit it."""
        if not self._events:
            return
        target = 0 if self._current_index is None else self._current_index + 1
        if target >= len(self._events):
            self._current_index = len(self._events) - 1
            self._pending_index = None
            self._mode = Mode.AFTER_LAST
            self._is_paused = False
            self._remaining_seconds = 0
            return
        self._advance_to(target, now)

    def skip_prev(self, now: datetime | None = None) -> None:
        """`now` doesn't affect *what* skip_prev does (no delay/shrink
        logic applies going backward, per the design spec) — it's only
        used to anchor `_last_tick` (see the comment below), so it's
        exposed for the same test-determinism reason as `start()`/
        `skip_next()`'s `now` parameter, not because skip_prev's own
        behavior depends on timing."""
        if not self._events:
            return
        target = 0 if self._current_index is None else max(self._current_index - 1, 0)
        self._current_index = target
        self._pending_index = None
        self._is_paused = False
        self._remaining_seconds = self._events[target].duration_seconds
        self._mode = Mode.RUNNING
        # Anchor the ticking reference point to right now (or the given
        # `now`, in tests), so the *next* regular tick() computes elapsed
        # time from this moment rather than from however long ago the last
        # tick happened to be — otherwise a tick() call using a fixed test
        # `datetime` far from real wall-clock time would compute a huge,
        # nonsensical elapsed value against a stale `_last_tick`.
        # `_advance_to` anchors the same way with its own `moment`.
        self._last_tick = now if now is not None else datetime.now()

    def _advance_to(self, index: int, now: datetime | None = None) -> None:
        """Move forward into event `index` — the only path that computes a
        (possibly shrunk) effective duration and updates the schedule-delay
        tracker. Used by `start()` and `skip_next()`; never by `skip_prev()`
        (going backward isn't "arriving via the normal flow")."""
        moment = now if now is not None else datetime.now()
        event = self._events[index]
        target_start = scheduler.compute_effective_start_times(self._events)[index]
        if target_start is None:
            self._delay_at_entry = 0.0
        else:
            self._delay_at_entry = scheduler.seconds_since_midnight(moment) - target_start

        if event.shrinkable:
            effective_delay = max(0.0, self._delay_at_entry - self._delay_reset_offset)
            effective_duration = max(event.min_duration_seconds, event.duration_seconds - effective_delay)
        else:
            effective_duration = event.duration_seconds

        self._current_index = index
        self._pending_index = None
        self._is_paused = False
        self._remaining_seconds = effective_duration
        self._mode = Mode.RUNNING
        # Anchor the ticking reference point to the actual advance moment —
        # see the matching comment in `skip_prev()` for why this matters.
        self._last_tick = moment

    def pause(self) -> None:
        if self._mode != Mode.RUNNING:
            return
        self._is_paused = True
        self._mode = Mode.PAUSED

    def resume(self) -> None:
        if not self._is_paused:
            return
        self._is_paused = False
        self._mode = Mode.RUNNING

    def adjust(self, delta_seconds: int) -> None:
        if self._mode not in (Mode.RUNNING, Mode.PAUSED):
            return
        # No floor at zero: overtime is now a normal, meaningful state, so
        # there's no reason to stop an operator from deliberately nudging a
        # countdown negative, the same way it can go negative on its own.
        self._remaining_seconds += delta_seconds

    def reset_schedule(self) -> None:
        """Zero out the schedule-delay readout immediately, from whatever
        mode we're in right now — folds the current raw delay into a
        persistent offset, so a deliberately-forgiven stretch (e.g. an
        intentionally-extended break) doesn't resurface at the next
        transition, the way a one-shot reset of `_delay_at_entry` alone
        would (that value gets wholesale replaced on every forward
        advance regardless)."""
        raw = self._raw_schedule_delay()
        if raw is not None:
            self._delay_reset_offset += raw

    def _raw_schedule_delay(self) -> float | None:
        if self._mode in (Mode.EMPTY, Mode.AWAITING_START, Mode.AFTER_LAST):
            return None
        if self._mode == Mode.BEFORE_FIRST:
            return max(0.0, -self._remaining_seconds)
        # RUNNING or PAUSED
        return self._delay_at_entry + max(0.0, -self._remaining_seconds)

    def _display_schedule_delay(self) -> float | None:
        raw = self._raw_schedule_delay()
        if raw is None:
            return None
        return raw - self._delay_reset_offset

    def get_display_state(self) -> DisplayState:
        if self._mode == Mode.EMPTY:
            return DisplayState(
                mode=self._mode,
                current_name=None,
                remaining_seconds=0,
                next_name=None,
                next_duration_seconds=None,
                color_state=ColorState.NORMAL,
                is_paused=False,
                current_description=None,
                next_description=None,
                schedule_delay_seconds=None,
            )

        if self._mode == Mode.AWAITING_START:
            first = self._events[0] if self._events else None
            return DisplayState(
                mode=self._mode,
                current_name=None,
                remaining_seconds=0,
                next_name=first.name if first else None,
                next_duration_seconds=first.duration_seconds if first else None,
                color_state=ColorState.NORMAL,
                is_paused=False,
                current_description=None,
                next_description=first.description if first else None,
                schedule_delay_seconds=None,
            )

        if self._mode == Mode.BEFORE_FIRST:
            upcoming = self._events[self._pending_index]
            return DisplayState(
                mode=self._mode,
                current_name=None,
                remaining_seconds=self._remaining_seconds,
                next_name=upcoming.name,
                next_duration_seconds=upcoming.duration_seconds,
                color_state=color_state_for(self._remaining_seconds),
                is_paused=False,
                current_description=None,
                next_description=upcoming.description,
                schedule_delay_seconds=self._display_schedule_delay(),
            )

        if self._mode == Mode.AFTER_LAST:
            return DisplayState(
                mode=self._mode,
                current_name=None,
                remaining_seconds=0,
                next_name=None,
                next_duration_seconds=None,
                color_state=ColorState.NORMAL,
                is_paused=False,
                current_description=None,
                next_description=None,
                schedule_delay_seconds=None,
            )

        # RUNNING or PAUSED
        current_event = self._events[self._current_index]
        next_index = self._current_index + 1
        next_event = self._events[next_index] if next_index < len(self._events) else None
        return DisplayState(
            mode=self._mode,
            current_name=current_event.name,
            remaining_seconds=self._remaining_seconds,
            next_name=next_event.name if next_event else None,
            next_duration_seconds=next_event.duration_seconds if next_event else None,
            color_state=color_state_for(self._remaining_seconds),
            is_paused=self._is_paused,
            current_description=current_event.description,
            next_description=next_event.description if next_event else None,
            schedule_delay_seconds=self._display_schedule_delay(),
        )

    def get_schedule_overview(self) -> list[ScheduleRow]:
        starts = scheduler.compute_effective_start_times(self._events)
        is_live = self._mode in (Mode.RUNNING, Mode.PAUSED)
        return [
            ScheduleRow(
                name=event.name,
                duration_seconds=event.duration_seconds,
                effective_start_seconds=start,
                is_current=is_live and i == self._current_index,
            )
            for i, (event, start) in enumerate(zip(self._events, starts))
        ]
