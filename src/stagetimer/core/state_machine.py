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


def color_state_for(remaining_seconds: float) -> ColorState:
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


@dataclass(frozen=True)
class ScheduleRow:
    name: str
    duration_seconds: int
    effective_start_seconds: int | None
    is_current: bool


class TimerEngine:
    """Owns the live playback state for the currently-showing event.

    Wall-clock-authoritative until the operator manually intervenes (pause,
    skip, adjust), at which point the current event's countdown becomes
    self-ticking ("overridden") until it ends, after which auto-advance
    re-syncs the new current event back to the wall-clock plan.
    """

    def __init__(self, timetable: Timetable):
        self._events: list[Event] = []
        self._current_index: int | None = None
        self._remaining_seconds: float = 0.0
        self._overridden: bool = False
        self._is_paused: bool = False
        self._mode: Mode = Mode.EMPTY
        self._last_tick: datetime | None = None
        self.set_timetable(timetable)

    def set_timetable(self, timetable: Timetable) -> None:
        self.timetable = timetable
        self._events = timetable.sorted_events()
        self._current_index = None
        self._remaining_seconds = 0.0
        self._overridden = False
        self._is_paused = False
        self._mode = Mode.EMPTY
        self._last_tick = None

    def tick(self, now: datetime) -> None:
        if not self._events:
            self._mode = Mode.EMPTY
            self._current_index = None
            self._last_tick = now
            return

        if self._is_paused:
            self._last_tick = now
            return

        if self._overridden:
            self._tick_overridden(now)
            return

        self._tick_from_wallclock(now)

    def _tick_from_wallclock(self, now: datetime) -> None:
        resolution = scheduler.resolve(now, self._events)
        self._last_tick = now
        self._current_index = resolution.index

        if resolution.mode == "EMPTY":
            self._mode = Mode.EMPTY
        elif resolution.mode == "AWAITING_START":
            self._mode = Mode.AWAITING_START
        elif resolution.mode == "BEFORE_FIRST":
            self._mode = Mode.BEFORE_FIRST
            self._remaining_seconds = resolution.remaining_seconds
        elif resolution.mode == "RUNNING":
            self._mode = Mode.RUNNING
            self._remaining_seconds = resolution.remaining_seconds
        elif resolution.mode == "AFTER_LAST":
            self._mode = Mode.AFTER_LAST
            self._remaining_seconds = 0

    def _tick_overridden(self, now: datetime) -> None:
        if self._last_tick is not None:
            elapsed = (now - self._last_tick).total_seconds()
            self._remaining_seconds -= elapsed
        self._last_tick = now

        if self._remaining_seconds <= 0:
            self._advance_to_next(now)
        else:
            self._mode = Mode.RUNNING

    def _advance_to_next(self, now: datetime) -> None:
        if self._current_index is None:
            return
        next_index = self._current_index + 1
        if next_index >= len(self._events):
            self._current_index = len(self._events) - 1
            self._mode = Mode.AFTER_LAST
            self._remaining_seconds = 0
            self._overridden = False
            return

        self._current_index = next_index
        self._overridden = False
        # Try to re-sync the new current event to the wall-clock plan; if the
        # clock doesn't actually consider it current yet (we're running ahead
        # of schedule due to a prior override), keep it self-ticking from its
        # full duration instead.
        resolution = scheduler.resolve(now, self._events)
        if resolution.mode == "RUNNING" and resolution.index == self._current_index:
            self._remaining_seconds = resolution.remaining_seconds
            self._mode = Mode.RUNNING
        else:
            self._overridden = True
            self._remaining_seconds = self._events[self._current_index].duration_seconds
            self._mode = Mode.RUNNING
        self._last_tick = now

    def pause(self) -> None:
        if self._mode != Mode.RUNNING:
            return
        self._is_paused = True
        self._overridden = True
        self._mode = Mode.PAUSED

    def resume(self) -> None:
        if not self._is_paused:
            return
        self._is_paused = False
        self._mode = Mode.RUNNING

    def start(self) -> None:
        """Jump straight to the first event and begin playing it, ignoring
        wall-clock scheduling entirely. Intended for use when nothing is
        currently running (EMPTY/AWAITING_START/AFTER_LAST) — callers such
        as the config window gate the button on that, but this method
        itself will happily override whatever is playing if called anytime,
        exactly like skip_next()/skip_prev() already do."""
        if not self._events:
            return
        self._jump_to(0)

    def skip_next(self) -> None:
        if not self._events:
            return
        target = 0 if self._current_index is None else self._current_index + 1
        if target >= len(self._events):
            self._current_index = len(self._events) - 1
            self._mode = Mode.AFTER_LAST
            self._overridden = False
            self._is_paused = False
            self._remaining_seconds = 0
            return
        self._jump_to(target)

    def skip_prev(self) -> None:
        if not self._events:
            return
        target = 0 if self._current_index is None else max(self._current_index - 1, 0)
        self._jump_to(target)

    def _jump_to(self, index: int) -> None:
        self._current_index = index
        self._overridden = True
        self._is_paused = False
        self._remaining_seconds = self._events[index].duration_seconds
        self._mode = Mode.RUNNING

    def adjust(self, delta_seconds: int) -> None:
        if self._mode not in (Mode.RUNNING, Mode.PAUSED):
            return
        self._overridden = True
        self._remaining_seconds = max(0.0, self._remaining_seconds + delta_seconds)

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
            )

        if self._current_index is None:
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
            )

        if self._mode == Mode.BEFORE_FIRST:
            upcoming = self._events[self._current_index]
            return DisplayState(
                mode=self._mode,
                current_name=None,
                remaining_seconds=self._remaining_seconds,
                next_name=upcoming.name,
                next_duration_seconds=upcoming.duration_seconds,
                color_state=ColorState.NORMAL,
                is_paused=False,
                current_description=None,
                next_description=upcoming.description,
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
            )

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
