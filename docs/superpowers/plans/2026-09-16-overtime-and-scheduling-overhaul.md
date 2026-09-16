# Overtime, Shrinkable Events & No-Auto-Start Scheduling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `TimerEngine`'s wall-clock-authoritative auto-start/auto-advance with a fully operator-driven model — nothing ever starts or advances on its own — add a visible, ticking overtime state instead of silent auto-advance, add shrinkable events that compress to absorb upstream delay, and add a cumulative whole-day schedule-delay readout with a manual reset.

**Architecture:** `scheduler.py` keeps its existing chained/anchored planned-time math (`compute_effective_start_times`) completely unchanged — it becomes the fixed "target" reference the whole delay system measures against — but its `resolve()`/`Resolution` (which decided "what should currently be showing" purely from the wall clock) is replaced by a narrower `resolve_pending()`/`PendingResolution`, used only while nothing has ever been manually started. `TimerEngine`'s tick loop stops re-deriving "what's current" every tick; `_current_index` only ever changes via explicit `start()`/`skip_next()`/`skip_prev()`, and whatever's current just ticks down unclamped (negative = overtime). Two new engine fields (`_delay_at_entry`, `_delay_reset_offset`) implement the delay/shrink formula from the spec. This is a genuine behavior change to a large fraction of the existing test suite, not just new coverage — **Task 2 and Task 3 both involve auditing and rewriting existing tests that assert the old auto-start behavior**, spelled out explicitly task-by-task below so there's no ambiguity about which tests to keep, rewrite, or remove.

**Tech Stack:** Python, PySide6 (Qt6), pytest (offscreen `QT_QPA_PLATFORM`) — same as the rest of the project. No new dependencies.

---

## File Structure

| File | Change |
|---|---|
| `src/stagetimer/core/models.py` | `Event` gains `shrinkable`/`min_duration_seconds` |
| `src/stagetimer/core/scheduler.py` | `resolve()`/`Resolution` removed; new `resolve_pending()`/`PendingResolution`; `_seconds_since_midnight` promoted to public `seconds_since_midnight` |
| `src/stagetimer/core/state_machine.py` | Core engine rewrite: no more wall-clock auto-advance, unclamped negative countdown, delay/shrink tracking, `reset_schedule()`, `ColorState.OVERTIME`, `DisplayState.schedule_delay_seconds` |
| `src/stagetimer/ui/display_widgets.py` | New `format_overtime()`; `ClockLabel` gets `OVERTIME` color mapping; new `ScheduleDelayLabel` widget |
| `src/stagetimer/ui/styles.py` | New `SCHEDULE_DELAY_BEHIND_QSS`/`SCHEDULE_DELAY_ONTIME_QSS` |
| `src/stagetimer/ui/main_display.py` | Wires `ScheduleDelayLabel` into the layout; switches to `format_overtime`; `BEFORE_FIRST` uses live color state instead of hardcoded `NORMAL` |
| `src/stagetimer/ui/shortcuts.py` | Main display shrinks to `Space` (→ `skip_next`) + `Ctrl+E` only |
| `src/stagetimer/ui/config_window.py` | `EventEditDialog` gets Shrinkable checkbox + floor spinner; Ctrl+E gets a "Reset Schedule" button |
| `tests/test_persistence.py`, `tests/test_scheduler.py`, `tests/test_state_machine.py`, `tests/test_display_widgets.py`, `tests/test_ui_smoke.py` | New/rewritten tests per task below |

**Task order and why it's sequential:** `models.py` (Task 1) is a pure additive dependency of everything else. `scheduler.py` (Task 2) must land before `state_machine.py` (Task 3) since the engine calls `resolve_pending`/`seconds_since_midnight`. `state_machine.py` must land before any UI task (4-7), since every UI change consumes `DisplayState.schedule_delay_seconds`/`ColorState.OVERTIME`/the new engine methods. `display_widgets.py` (Task 4) before `main_display.py` (Task 5), since main_display wires the new widget Task 4 creates. `shortcuts.py` (Task 6) and `config_window.py` (Task 7) are independent of each other but both depend on the engine (Task 3) already existing. Task 8 is verification only. Per subagent-driven-development's own rules, implementer subagents are never dispatched in parallel regardless of file overlap — so this plan is fully sequential end to end. Baseline before this plan: **141 passing tests**.

---

### Task 1: `Event` gains `shrinkable` and `min_duration_seconds`

**Files:**
- Modify: `src/stagetimer/core/models.py`
- Test: `tests/test_persistence.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_persistence.py`:

```python
def test_save_then_load_roundtrip_with_shrinkable(tmp_path: Path):
    path = tmp_path / "timetable.json"
    original = Timetable(
        events=[
            Event(
                name="Changeover",
                start_time=None,
                duration_seconds=300,
                shrinkable=True,
                min_duration_seconds=60,
            )
        ],
    )

    persistence.save(path, original)
    loaded = persistence.load(path)

    assert loaded.events[0].shrinkable is True
    assert loaded.events[0].min_duration_seconds == 60


def test_load_missing_shrinkable_fields_default_to_false_and_zero(tmp_path: Path):
    path = tmp_path / "timetable.json"
    path.write_text(
        '{"version": 1, "logo_path": null, "events": ['
        '{"id": "x", "name": "Legacy", "start_time": null, "duration_seconds": 60}'
        ']}',
        encoding="utf-8",
    )

    loaded = persistence.load(path)

    assert loaded.events[0].shrinkable is False
    assert loaded.events[0].min_duration_seconds == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Claude_Projekte\StageTimer && ./.venv/Scripts/python -m pytest tests/test_persistence.py -q`
Expected: the 2 new tests FAIL — `TypeError: Event.__init__() got an unexpected keyword argument 'shrinkable'`.

- [ ] **Step 3: Add the fields to `Event`**

In `src/stagetimer/core/models.py`, change:

```python
@dataclass
class Event:
    name: str
    start_time: time | None
    duration_seconds: int
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "start_time": self.start_time.strftime("%H:%M:%S") if self.start_time else None,
            "duration_seconds": self.duration_seconds,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Event":
        raw_start = data.get("start_time")
        if raw_start:
            hh, mm, ss = (int(part) for part in raw_start.split(":"))
            start_time = time(hh, mm, ss)
        else:
            start_time = None
        return cls(
            id=data["id"],
            name=data["name"],
            start_time=start_time,
            duration_seconds=int(data["duration_seconds"]),
            description=data.get("description", ""),
        )
```

to:

```python
@dataclass
class Event:
    name: str
    start_time: time | None
    duration_seconds: int
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: str = ""
    shrinkable: bool = False
    min_duration_seconds: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "start_time": self.start_time.strftime("%H:%M:%S") if self.start_time else None,
            "duration_seconds": self.duration_seconds,
            "description": self.description,
            "shrinkable": self.shrinkable,
            "min_duration_seconds": self.min_duration_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Event":
        raw_start = data.get("start_time")
        if raw_start:
            hh, mm, ss = (int(part) for part in raw_start.split(":"))
            start_time = time(hh, mm, ss)
        else:
            start_time = None
        return cls(
            id=data["id"],
            name=data["name"],
            start_time=start_time,
            duration_seconds=int(data["duration_seconds"]),
            description=data.get("description", ""),
            shrinkable=bool(data.get("shrinkable", False)),
            min_duration_seconds=int(data.get("min_duration_seconds", 0)),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Claude_Projekte\StageTimer && ./.venv/Scripts/python -m pytest tests/test_persistence.py -q`
Expected: `12 passed` (10 existing + 2 new).

- [ ] **Step 5: Run the full suite**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest -q`
Expected: `143 passed` (141 baseline + 2 new).

- [ ] **Step 6: Commit**

```bash
git add src/stagetimer/core/models.py tests/test_persistence.py
git commit -m "feat: add shrinkable and min_duration_seconds to Event"
```

---

### Task 2: `scheduler.py` — replace `resolve()` with `resolve_pending()`

**Files:**
- Modify: `src/stagetimer/core/scheduler.py`
- Modify: `tests/test_scheduler.py` (substantial rewrite, not just additions — see below)

**Context for the implementer:** `scheduler.resolve()` currently answers "what should be showing right now, purely from the wall clock" — including deciding when an event is `RUNNING` and when the day is `AFTER_LAST`, purely by comparing `now` to the plan. This is the actual auto-start mechanism this whole feature removes. Once `TimerEngine` (Task 3, not this task) stops asking "what should be current," `resolve()`'s `RUNNING`/`AFTER_LAST` branches become meaningless — nothing will ever call them expecting the old behavior, and leaving them in place would be actively misleading (the docstring would claim a behavior that no longer holds). This task removes `resolve()`/`Resolution` entirely and replaces them with a narrower `resolve_pending()`/`PendingResolution` that only answers "is there a target ahead of us, and how far away (possibly negative — already late) is it" — used only while nothing has ever been manually started. `compute_effective_start_times()` (and its tests) are **not** touched.

- [ ] **Step 1: Write the failing tests**

Replace the entire contents of `tests/test_scheduler.py` with:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Claude_Projekte\StageTimer && ./.venv/Scripts/python -m pytest tests/test_scheduler.py -q`
Expected: FAIL — `AttributeError: module 'stagetimer.core.scheduler' has no attribute 'resolve_pending'` (and `seconds_since_midnight`), for every test except the 3 `compute_effective_start_times` ones (which should already pass unchanged, since that function isn't touched yet).

- [ ] **Step 3: Replace `resolve()`/`Resolution` with `resolve_pending()`/`PendingResolution`, and promote `_seconds_since_midnight`**

In `src/stagetimer/core/scheduler.py`, change:

```python
def _seconds_since_midnight(dt: datetime) -> int:
    return dt.hour * 3600 + dt.minute * 60 + dt.second
```

to:

```python
def seconds_since_midnight(dt: datetime) -> int:
    return dt.hour * 3600 + dt.minute * 60 + dt.second
```

This function's only caller today is inside `resolve()`, which Step 3 below removes entirely and replaces with `resolve_pending()` (whose own body already calls the new public `seconds_since_midnight` name) — so no separate call-site rename is needed elsewhere in the file. `_compute_effective_times` never calls it. After this step, confirm via a quick search that the leading-underscore name `_seconds_since_midnight` no longer appears anywhere in `scheduler.py`.

Change:

```python
@dataclass(frozen=True)
class Resolution:
    """Result of resolving 'what should be on screen right now' from pure
    wall-clock math, with no knowledge of pause/skip/adjust overrides."""

    mode: str  # "EMPTY" | "AWAITING_START" | "BEFORE_FIRST" | "RUNNING" | "AFTER_LAST"
    index: int | None
    remaining_seconds: int
```

to:

```python
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
```

Change the full `resolve()` function (from `def resolve(now: datetime, events: list[Event]) -> Resolution:` to its closing `return Resolution(mode="AFTER_LAST", index=last.index, remaining_seconds=0)`) to:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Claude_Projekte\StageTimer && ./.venv/Scripts/python -m pytest tests/test_scheduler.py -q`
Expected: `12 passed`.

- [ ] **Step 5: Run the full suite**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest -q`
Expected: some tests in `test_state_machine.py` now FAIL — `AttributeError`/`ImportError` referencing `scheduler.resolve` — **this is expected and correct at this point in the plan**, since `state_machine.py` (Task 3, next) still calls the now-removed `resolve()`. Do not attempt to fix `state_machine.py` in this task. Report the exact failure count/names you observe, but do not treat them as a problem to solve here.

- [ ] **Step 6: Commit**

```bash
git add src/stagetimer/core/scheduler.py tests/test_scheduler.py
git commit -m "refactor: replace scheduler.resolve() with resolve_pending(), used only before anything starts"
```

(It's expected and fine for the full suite to be red after this commit — `state_machine.py` hasn't been updated yet. The next task fixes that.)

---

### Task 3: `state_machine.py` — the core engine rewrite

**Files:**
- Modify: `src/stagetimer/core/state_machine.py`
- Modify: `tests/test_state_machine.py` (**substantial rewrite — read the whole "Test audit" subsection below before touching this file**)

**Context for the implementer:** This is the task that actually removes auto-start/auto-advance. Read the design rationale in `docs/superpowers/specs/2026-09-16-overtime-and-scheduling-overhaul.md` (the "Architecture" section) if you want the full reasoning — this task gives you the exact resulting code, already worked out, so you shouldn't need to re-derive anything, but the spec explains *why* the formulas below are shaped the way they are.

#### Step 1: Replace the full contents of `src/stagetimer/core/state_machine.py`

Read the current file first to confirm nothing else has changed since this plan was written, then replace its entire contents with:

```python
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
        mode we're in right now — replaces (not accumulates onto) the
        persistent offset with whatever the display currently reads, so a
        deliberately-forgiven stretch (e.g. an intentionally-extended
        break) doesn't resurface at the next transition, the way a
        one-shot reset of `_delay_at_entry` alone would (that value gets
        wholesale replaced on every forward advance regardless). Must be
        `=`, not `+=`: this needs to be idempotent — pressing it twice in a
        row (nothing else having changed) must still leave the display at
        exactly 0, not drive it further from zero."""
        raw = self._raw_schedule_delay()
        if raw is not None:
            self._delay_reset_offset = raw

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
```

#### Step 2: Rewrite `tests/test_state_machine.py`

This is a full-file rewrite, not an append — most of the file's existing tests assert the exact auto-start/auto-advance behavior this task removes. Below is the complete replacement content. It preserves every test that's still valid unchanged (color thresholds, `compute_effective_start_times`-independent EMPTY/AWAITING_START checks, descriptions), rewrites every test that relied on wall-clock-only auto-start to instead call `engine.start()`/`skip_next()` explicitly first, replaces the two "auto-advance at zero" tests with their direct opposite ("stays put and goes negative"), and adds new coverage for delay tracking, shrinkable events, gap absorption, and `reset_schedule()` exactly matching the worked examples in the design spec.

Replace the entire contents of `tests/test_state_machine.py` with:

```python
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
```

Note that `skip_next()` in the Step 1 engine code above already accepts an optional `now` parameter (mirroring `start()`) specifically so the delay/shrink tests above can pin down exact, deterministic expected values instead of asserting loose ranges — every test that calls `skip_next(now=...)` is relying on that.

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd C:\Claude_Projekte\StageTimer && ./.venv/Scripts/python -m pytest tests/test_state_machine.py -q`
Expected: all pass. Report the exact count — it will differ from any number stated elsewhere in this plan, since this is a rewrite (some old tests removed, many new ones added); there is no single "right" number to match, only "every test in the file passes and each one asserts something true about the new design."

- [ ] **Step 3: Run the full suite**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest -q`
Expected: `tests/test_scheduler.py` and `tests/test_state_machine.py` fully green again (Task 2's expected red is now resolved). Other test files (`test_ui_smoke.py`, `test_display_widgets.py`, `test_persistence.py`) should be unaffected by this task — **if any of them newly fail**, read the failure carefully: `test_ui_smoke.py::test_main_display_shows_current_and_next_descriptions` and a couple of others construct a `TimerEngine` and call `engine.start()` directly (not through wall-clock ticking) — these should continue to work unchanged, since `start()`'s public signature is backward compatible (new `now` parameter is optional). If something in those files breaks, it's a real regression from this task's changes — fix `state_machine.py`, not the untouched test files, unless investigation shows the test itself was relying on removed behavior.

- [ ] **Step 4: Commit**

```bash
git add src/stagetimer/core/state_machine.py tests/test_state_machine.py
git commit -m "feat: remove wall-clock auto-start/auto-advance, add overtime and schedule-delay tracking"
```

---

### Task 4: `display_widgets.py` — overtime-aware formatting and the schedule-delay widget

**Files:**
- Modify: `src/stagetimer/ui/display_widgets.py`
- Modify: `src/stagetimer/ui/styles.py`
- Test: `tests/test_display_widgets.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_display_widgets.py`:

```python
def test_format_overtime_positive_same_as_format_remaining():
    from stagetimer.ui.display_widgets import format_overtime

    assert format_overtime(90) == "01:30"


def test_format_overtime_negative_gets_minus_prefix():
    from stagetimer.ui.display_widgets import format_overtime

    assert format_overtime(-90) == "-01:30"


def test_format_overtime_negative_hours():
    from stagetimer.ui.display_widgets import format_overtime

    assert format_overtime(-3661) == "-01:01:01"


def test_format_overtime_zero_is_unsigned():
    from stagetimer.ui.display_widgets import format_overtime

    assert format_overtime(0) == "00:00"


def test_schedule_delay_label_hidden_when_none(qapp):
    from stagetimer.ui.display_widgets import ScheduleDelayLabel

    label = ScheduleDelayLabel()
    assert label.isVisible() is False
    label.set_delay_seconds(None)
    assert label.isVisible() is False


def test_schedule_delay_label_shows_behind_text(qapp):
    from stagetimer.ui.display_widgets import ScheduleDelayLabel

    label = ScheduleDelayLabel()
    label.set_delay_seconds(225)
    assert label.isVisible() is True
    assert "03:45" in label.text()
    assert "BEHIND" in label.text()


def test_schedule_delay_label_shows_on_schedule_at_zero(qapp):
    from stagetimer.ui.display_widgets import ScheduleDelayLabel

    label = ScheduleDelayLabel()
    label.set_delay_seconds(0)
    assert label.isVisible() is True
    assert "ON SCHEDULE" in label.text()


def test_schedule_delay_label_shows_on_schedule_when_ahead(qapp):
    from stagetimer.ui.display_widgets import ScheduleDelayLabel

    label = ScheduleDelayLabel()
    label.set_delay_seconds(-300)  # running ahead — still reads as "on schedule", not alarming
    assert label.isVisible() is True
    assert "ON SCHEDULE" in label.text()


def test_schedule_delay_label_skips_redundant_update(qapp, monkeypatch):
    from stagetimer.ui.display_widgets import ScheduleDelayLabel

    label = ScheduleDelayLabel()
    label.set_delay_seconds(120)
    monkeypatch.setattr(label, "setText", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")))
    label.set_delay_seconds(120)  # identical value — must be a no-op
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_display_widgets.py -k "overtime or schedule_delay" -v`
Expected: FAIL — `ImportError`/`AttributeError` for `format_overtime` and `ScheduleDelayLabel`, which don't exist yet.

- [ ] **Step 3: Add `format_overtime()`**

In `src/stagetimer/ui/display_widgets.py`, right after the existing `format_remaining` function, add:

```python
def format_overtime(seconds: float) -> str:
    """Like `format_remaining`, but for values that can be negative
    (overtime) — rendered with a leading '-' and the magnitude, never
    clamped at zero. Used for the main clock (which can go negative once
    an event overruns) and the pre-start countdown (which can too, per the
    design spec); `format_remaining` stays used everywhere a value is
    always forward-looking and positive (the Next bar, the mini-timetable)."""
    sign = "-" if seconds < 0 else ""
    total = int(round(abs(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{sign}{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{sign}{minutes:02d}:{secs:02d}"
```

- [ ] **Step 4: Add the `OVERTIME` color mapping to `ClockLabel`**

In `src/stagetimer/ui/display_widgets.py`, change:

```python
        color_map = {
            ColorState.NORMAL: config.COLOR_NORMAL,
            ColorState.WARNING_YELLOW: config.COLOR_WARNING,
            ColorState.DANGER_RED: config.COLOR_DANGER,
        }
        self._fill_color = QColor(color_map[color_state])
```

to:

```python
        color_map = {
            ColorState.NORMAL: config.COLOR_NORMAL,
            ColorState.WARNING_YELLOW: config.COLOR_WARNING,
            ColorState.DANGER_RED: config.COLOR_DANGER,
            ColorState.OVERTIME: config.COLOR_DANGER,
        }
        self._fill_color = QColor(color_map[color_state])
```

(`OVERTIME` reuses the existing danger-red color — no new color constant needed. The `FLASH` special-case above this block, which alternates colors on its own timer, is untouched; `OVERTIME` is steady/non-flashing, matching the design spec's "static" requirement, simply by not being routed through that branch.)

- [ ] **Step 5: Add the `SCHEDULE_DELAY_*_QSS` styles**

In `src/stagetimer/ui/styles.py`, add after the existing `MINI_TIMETABLE_QSS` block:

```python
SCHEDULE_DELAY_BEHIND_QSS = (
    f"color: {config.COLOR_DANGER}; background: rgba(255,59,48,0.15); "
    "font-size: 20px; font-weight: bold; padding: 4px 14px; border-radius: 14px;"
)
SCHEDULE_DELAY_ONTIME_QSS = (
    f"color: {config.COLOR_SUCCESS_GREEN}; background: rgba(34,197,94,0.15); "
    "font-size: 20px; font-weight: bold; padding: 4px 14px; border-radius: 14px;"
)
```

- [ ] **Step 6: Add the `ScheduleDelayLabel` widget**

In `src/stagetimer/ui/display_widgets.py`, add after `MiniTimetable` (the last class in the file):

```python
class ScheduleDelayLabel(QLabel):
    """Small readout meant to sit directly under the main clock, showing
    cumulative schedule delay across the whole day — independent of the
    current event's own countdown (which the big clock already shows).
    Hidden entirely when there's nothing meaningful to report (EMPTY,
    AWAITING_START, AFTER_LAST)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._last_seconds: float | None = None
        self.setVisible(False)

    def set_delay_seconds(self, seconds: float | None) -> None:
        if seconds == self._last_seconds:
            return
        self._last_seconds = seconds
        if seconds is None:
            self.setVisible(False)
            return
        self.setVisible(True)
        if seconds <= 0:
            self.setText("ON SCHEDULE")
            self.setStyleSheet(styles.SCHEDULE_DELAY_ONTIME_QSS)
        else:
            self.setText(f"SCHEDULE {format_remaining(seconds)} BEHIND")
            self.setStyleSheet(styles.SCHEDULE_DELAY_BEHIND_QSS)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_display_widgets.py -q`
Expected: all pass — report the exact count (existing file count + 9 new).

- [ ] **Step 8: Run the full suite**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest -q`
Expected: all green.

- [ ] **Step 9: Commit**

```bash
git add src/stagetimer/ui/display_widgets.py src/stagetimer/ui/styles.py tests/test_display_widgets.py
git commit -m "feat: add overtime-aware formatting and the schedule-delay readout widget"
```

---

### Task 5: `main_display.py` — wire the schedule-delay readout in, switch to overtime-aware rendering

**Files:**
- Modify: `src/stagetimer/ui/main_display.py`
- Test: `tests/test_ui_smoke.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui_smoke.py`:

```python
def test_main_display_shows_overtime_in_red_when_event_overruns(qapp):
    from stagetimer.core.state_machine import ColorState

    timetable = Timetable(events=[Event(name="Keynote", start_time=None, duration_seconds=60)])
    engine = TimerEngine(timetable)
    engine.start()
    display = MainDisplay(engine, kiosk=False)
    engine._remaining_seconds = -45  # force overtime without waiting on real time (mode is already RUNNING from start())
    display._on_tick()
    assert display.clock._text == "-00:45"
    assert display.clock._last_color_state == ColorState.OVERTIME
    display.close()


def test_main_display_shows_schedule_delay_readout(qapp):
    timetable = Timetable(
        events=[
            Event(name="Keynote", start_time=None, duration_seconds=600),
            Event(name="Panel", start_time=None, duration_seconds=600),
        ]
    )
    engine = TimerEngine(timetable)
    engine.start()
    engine._delay_at_entry = 90  # simulate having entered 90s late
    display = MainDisplay(engine, kiosk=False)
    display._on_tick()
    assert display.schedule_delay.isVisible() is True
    assert "01:30" in display.schedule_delay.text()
    display.close()


def test_main_display_hides_schedule_delay_when_empty(qapp):
    engine = TimerEngine(Timetable(events=[]))
    display = MainDisplay(engine, kiosk=False)
    display._on_tick()
    assert display.schedule_delay.isVisible() is False
    display.close()
```

Note: reaching into `engine._remaining_seconds`/`engine._delay_at_entry` directly is a pragmatic shortcut for these two tests specifically, since driving the real overtime/delay conditions through wall-clock ticking would require either sleeping in the test or constructing elaborate `datetime` scenarios already covered thoroughly in `test_state_machine.py` — this file's tests exist to verify *wiring* (does `MainDisplay` correctly read `DisplayState` and drive the widgets), not to re-verify the engine's own math a second time.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_ui_smoke.py -k "overtime or schedule_delay" -v`
Expected: FAIL — `AttributeError: 'MainDisplay' object has no attribute 'schedule_delay'`.

- [ ] **Step 3: Update imports**

In `src/stagetimer/ui/main_display.py`, change:

```python
from stagetimer.ui.display_widgets import (
    ClockArea,
    CurrentBox,
    LogoBox,
    MiniTimetable,
    NextBar,
    format_remaining,
)
```

to:

```python
from stagetimer.ui.display_widgets import (
    ClockArea,
    CurrentBox,
    LogoBox,
    MiniTimetable,
    NextBar,
    ScheduleDelayLabel,
    format_overtime,
    format_remaining,
)
```

- [ ] **Step 4: Add the widget to `__init__`'s layout**

Change:

```python
        self.next_bar = NextBar()
        self.mini_timetable = MiniTimetable()
        self.mini_timetable.setMinimumWidth(320)
        self.mini_timetable.setFixedHeight(140)
```

to:

```python
        self.next_bar = NextBar()
        self.schedule_delay = ScheduleDelayLabel()
        self.mini_timetable = MiniTimetable()
        self.mini_timetable.setMinimumWidth(320)
        self.mini_timetable.setFixedHeight(140)
```

Change:

```python
        root = QVBoxLayout(self)
        root.addLayout(top_row)
        root.addWidget(self.clock_area, 1)
        root.addWidget(divider)
        root.addLayout(bottom_row)
```

to:

```python
        root = QVBoxLayout(self)
        root.addLayout(top_row)
        root.addWidget(self.clock_area, 1)
        root.addWidget(self.schedule_delay)
        root.addWidget(divider)
        root.addLayout(bottom_row)
```

- [ ] **Step 5: Rewrite `_on_tick` to use `format_overtime` and wire the schedule-delay readout**

Replace the full `_on_tick` method with:

```python
    def _on_tick(self) -> None:
        self.engine.tick(datetime.now())
        state = self.engine.get_display_state()

        if state.mode == Mode.EMPTY:
            self.current_box.set_name(NO_EVENTS_TEXT)
            self.current_box.set_description(None)
            self.clock.set_time_and_state(BLANK_CLOCK_TEXT, ColorState.NORMAL)
            self.next_bar.set_next(None, None)
        elif state.mode == Mode.AWAITING_START:
            self.current_box.set_name(AWAITING_START_TEXT)
            self.current_box.set_description(None)
            self.clock.set_time_and_state(BLANK_CLOCK_TEXT, ColorState.NORMAL)
            self.next_bar.set_next(state.next_name, state.next_duration_seconds, state.next_description)
        elif state.mode == Mode.BEFORE_FIRST:
            self.current_box.set_name(STANDBY_TEXT)
            self.current_box.set_description(None)
            self.clock.set_time_and_state(format_overtime(state.remaining_seconds), state.color_state)
            self.next_bar.set_next(state.next_name, state.next_duration_seconds, state.next_description)
        elif state.mode == Mode.AFTER_LAST:
            self.current_box.set_name(DAY_COMPLETE_TEXT)
            self.current_box.set_description(None)
            self.clock.set_time_and_state(BLANK_CLOCK_TEXT, ColorState.NORMAL)
            self.next_bar.set_next(None, None)
        else:  # RUNNING or PAUSED
            self.current_box.set_name(state.current_name)
            self.current_box.set_description(state.current_description)
            self.clock.set_time_and_state(format_overtime(state.remaining_seconds), state.color_state)
            self.next_bar.set_next(state.next_name, state.next_duration_seconds, state.next_description)

        self.schedule_delay.set_delay_seconds(state.schedule_delay_seconds)
        self.realtime_clock.setText(datetime.now().strftime("%H:%M:%S"))
        self.mini_timetable.set_rows(self.engine.get_schedule_overview())
```

Note the `BEFORE_FIRST` branch: it previously hardcoded `ColorState.NORMAL` and used `format_remaining`; it now uses `state.color_state` (the engine now computes this correctly, including `OVERTIME` once the pre-start countdown goes negative) and `format_overtime` (so it can actually render a negative value instead of having it silently clamped to `00:00`).

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_ui_smoke.py -q`
Expected: all pass.

- [ ] **Step 7: Run the full suite**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest -q`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add src/stagetimer/ui/main_display.py tests/test_ui_smoke.py
git commit -m "feat: wire overtime rendering and the schedule-delay readout into the main display"
```

---

### Task 6: `shortcuts.py` — main display shrinks to Space + Ctrl+E

**Files:**
- Modify: `src/stagetimer/ui/shortcuts.py`
- Test: `tests/test_ui_smoke.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui_smoke.py`:

```python
def test_main_display_shortcuts_are_only_space_and_ctrl_e(qapp, engine):
    display = MainDisplay(engine, kiosk=False)
    toggled = []
    shortcuts = register_main_display_shortcuts(display, engine, lambda: toggled.append(1))
    key_sequences = {s.key().toString() for s in shortcuts}
    assert key_sequences == {"Space", "Ctrl+E"}
    display.close()


def test_space_shortcut_calls_skip_next(qapp, engine):
    calls = []
    original_skip_next = engine.skip_next
    engine.skip_next = lambda *a, **k: calls.append(1)
    display = MainDisplay(engine, kiosk=False)
    shortcuts = register_main_display_shortcuts(display, engine, lambda: None)
    space_shortcut = next(s for s in shortcuts if s.key().toString() == "Space")
    space_shortcut.activated.emit()
    assert calls == [1]
    engine.skip_next = original_skip_next
    display.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_ui_smoke.py -k "shortcuts_are_only or space_shortcut" -v`
Expected: FAIL — the assertion on `key_sequences` fails (currently contains 10 shortcuts, not 2), and `Space` currently calls `pause_resume_toggle`, not `skip_next`.

- [ ] **Step 3: Replace the shortcut bindings**

Replace the full contents of `src/stagetimer/ui/shortcuts.py` with:

```python
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget

from stagetimer.core.state_machine import TimerEngine


def register_main_display_shortcuts(
    widget: QWidget, engine: TimerEngine, toggle_config_window: Callable[[], None]
) -> list[QShortcut]:
    """Register keyboard shortcuts scoped to `widget` (the fullscreen main
    display), so they don't fire while typing in the config window's text
    fields (which live in a separate top-level widget).

    Deliberately minimal: Space is the only playback action available on
    the main display — it always advances to the next event (same action
    as Skip Next), matching "space bar always required to start any
    event." Every other manual control (Pause/Resume/Skip Prev/Skip
    Next/Adjust) is reachable only through the Ctrl+E config window's Live
    Controls buttons, never from the main display's own keyboard."""

    bindings: list[tuple[str, Callable[[], None]]] = [
        ("Space", engine.skip_next),
        ("Ctrl+E", toggle_config_window),
    ]

    shortcuts: list[QShortcut] = []
    for key_sequence, handler in bindings:
        shortcut = QShortcut(QKeySequence(key_sequence), widget)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(handler)
        shortcuts.append(shortcut)
    return shortcuts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_ui_smoke.py -q`
Expected: all pass.

- [ ] **Step 5: Run the full suite**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/stagetimer/ui/shortcuts.py tests/test_ui_smoke.py
git commit -m "feat: shrink main display shortcuts to Space (advance) and Ctrl+E only"
```

---

### Task 7: `config_window.py` — Shrinkable checkbox, floor spinner, Reset Schedule button

**Files:**
- Modify: `src/stagetimer/ui/config_window.py`
- Test: `tests/test_ui_smoke.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui_smoke.py`:

```python
def test_event_edit_dialog_shrinkable_and_floor_round_trip(qapp):
    from stagetimer.ui.config_window import EventEditDialog

    dialog = EventEditDialog()
    dialog.name_edit.setText("Changeover")
    dialog.shrinkable_checkbox.setChecked(True)
    dialog.min_duration_minutes.setValue(2)
    dialog._on_accept()
    result = dialog.result_event()
    assert result.shrinkable is True
    assert result.min_duration_seconds == 120


def test_event_edit_dialog_prefills_shrinkable_from_existing_event(qapp):
    from stagetimer.ui.config_window import EventEditDialog

    event = Event(
        name="Changeover", start_time=None, duration_seconds=300,
        shrinkable=True, min_duration_seconds=60,
    )
    dialog = EventEditDialog(event=event)
    assert dialog.shrinkable_checkbox.isChecked() is True
    assert dialog.min_duration_minutes.value() == 1


def test_event_edit_dialog_floor_spinner_disabled_unless_shrinkable(qapp):
    from stagetimer.ui.config_window import EventEditDialog

    dialog = EventEditDialog()
    assert dialog.min_duration_minutes.isEnabled() is False
    dialog.shrinkable_checkbox.setChecked(True)
    assert dialog.min_duration_minutes.isEnabled() is True
    dialog.shrinkable_checkbox.setChecked(False)
    assert dialog.min_duration_minutes.isEnabled() is False


def test_event_edit_dialog_defaults_not_shrinkable(qapp):
    from stagetimer.ui.config_window import EventEditDialog

    dialog = EventEditDialog()
    dialog.name_edit.setText("Keynote")
    dialog._on_accept()
    result = dialog.result_event()
    assert result.shrinkable is False
    assert result.min_duration_seconds == 0


def test_config_window_reset_schedule_button_calls_engine(qapp, engine):
    calls = []
    engine.reset_schedule = lambda: calls.append(1)
    timetable = Timetable(events=[Event(name="Keynote", start_time=None, duration_seconds=600)])
    window = ConfigWindow(engine, timetable, lambda p: None)
    window._reset_schedule_btn.click()
    assert calls == [1]
    window.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_ui_smoke.py -k "shrinkable or reset_schedule" -v`
Expected: FAIL — `AttributeError: 'EventEditDialog' object has no attribute 'shrinkable_checkbox'`, `AttributeError: 'ConfigWindow' object has no attribute '_reset_schedule_btn'`.

- [ ] **Step 3: Add the Shrinkable checkbox and floor spinner to `EventEditDialog`**

Read the actual current `src/stagetimer/ui/config_window.py` first to confirm exact current line content (other tasks in earlier plans have already modified this file since this plan's snapshot). Find where `self.description_edit` is constructed and where `form.addRow("Description:", ...)` is called — insert the new fields between the existing Duration field and the Description field:

Change:

```python
        self.description_edit = QTextEdit()
        self.description_edit.setPlainText(event.description if event else "")
        self.description_edit.setFixedHeight(80)

        form = QFormLayout()
        form.addRow("Name:", self.name_edit)
        form.addRow("Start time:", start_row)
        form.addRow("Duration:", self.duration_minutes)
        form.addRow("Description:", self.description_edit)
```

to:

```python
        self.shrinkable_checkbox = QCheckBox("Shrinkable (can compress to absorb delay)")
        self.shrinkable_checkbox.setChecked(event.shrinkable if event else False)

        self.min_duration_minutes = QSpinBox()
        self.min_duration_minutes.setRange(0, 24 * 60)
        self.min_duration_minutes.setSuffix(" min")
        self.min_duration_minutes.setValue((event.min_duration_seconds // 60) if event else 0)
        self.min_duration_minutes.setEnabled(self.shrinkable_checkbox.isChecked())
        self.shrinkable_checkbox.toggled.connect(self.min_duration_minutes.setEnabled)

        self.description_edit = QTextEdit()
        self.description_edit.setPlainText(event.description if event else "")
        self.description_edit.setFixedHeight(80)

        form = QFormLayout()
        form.addRow("Name:", self.name_edit)
        form.addRow("Start time:", start_row)
        form.addRow("Duration:", self.duration_minutes)
        form.addRow("", self.shrinkable_checkbox)
        form.addRow("Shrink floor:", self.min_duration_minutes)
        form.addRow("Description:", self.description_edit)
```

(`QCheckBox` and `QSpinBox` are already imported in this file — used by `has_start_time`/`duration_minutes` respectively — no new imports needed for this step.)

- [ ] **Step 4: Include the new fields when building the result `Event`**

Find `_on_accept`'s `kwargs` construction (currently includes `name`, `start_time`, `duration_seconds`, `description`). Change:

```python
        kwargs = dict(name=name, start_time=start_time, duration_seconds=duration_seconds, description=description)
```

to:

```python
        kwargs = dict(
            name=name,
            start_time=start_time,
            duration_seconds=duration_seconds,
            description=description,
            shrinkable=self.shrinkable_checkbox.isChecked(),
            min_duration_seconds=self.min_duration_minutes.value() * 60,
        )
```

- [ ] **Step 5: Add the "Reset Schedule" button**

Find where the existing Live Controls buttons are built (`start_btn`, `pause_btn`, `resume_btn`, `prev_btn`, `next_btn`, `minus_btn`, `plus_btn`, all added to `controls_row`). Change:

```python
        start_btn = QPushButton("Start")
        pause_btn = QPushButton("Pause")
        resume_btn = QPushButton("Resume")
        prev_btn = QPushButton("« Skip Prev")
        next_btn = QPushButton("Skip Next »")
        minus_btn = QPushButton("-1 min")
        plus_btn = QPushButton("+1 min")
        start_btn.clicked.connect(self.engine.start)
        pause_btn.clicked.connect(self.engine.pause)
        resume_btn.clicked.connect(self.engine.resume)
        prev_btn.clicked.connect(self.engine.skip_prev)
        next_btn.clicked.connect(self.engine.skip_next)
        minus_btn.clicked.connect(lambda: self.engine.adjust(-60))
        plus_btn.clicked.connect(lambda: self.engine.adjust(60))

        controls_row = QHBoxLayout()
        for btn in (start_btn, prev_btn, pause_btn, resume_btn, next_btn, minus_btn, plus_btn):
            controls_row.addWidget(btn)
```

to:

```python
        start_btn = QPushButton("Start")
        pause_btn = QPushButton("Pause")
        resume_btn = QPushButton("Resume")
        prev_btn = QPushButton("« Skip Prev")
        next_btn = QPushButton("Skip Next »")
        minus_btn = QPushButton("-1 min")
        plus_btn = QPushButton("+1 min")
        self._reset_schedule_btn = QPushButton("Reset Schedule")
        start_btn.clicked.connect(self.engine.start)
        pause_btn.clicked.connect(self.engine.pause)
        resume_btn.clicked.connect(self.engine.resume)
        prev_btn.clicked.connect(self.engine.skip_prev)
        next_btn.clicked.connect(self.engine.skip_next)
        minus_btn.clicked.connect(lambda: self.engine.adjust(-60))
        plus_btn.clicked.connect(lambda: self.engine.adjust(60))
        self._reset_schedule_btn.clicked.connect(self.engine.reset_schedule)

        controls_row = QHBoxLayout()
        for btn in (start_btn, prev_btn, pause_btn, resume_btn, next_btn, minus_btn, plus_btn, self._reset_schedule_btn):
            controls_row.addWidget(btn)
```

Note: `start_btn.clicked.connect(self.engine.start)` already exists and works today despite `Qt`'s `clicked(bool)` signal and `start()`'s zero-required-args signature — `engine.start` now optionally accepts `now`, which doesn't change this call site's behavior (Qt still only passes what the connected callable's signature requires; this pattern is unchanged from how `pause_btn`/`resume_btn`/etc. already work). No lambda wrapper is needed here, matching the existing style for the other zero-argument-from-Qt's-perspective buttons.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_ui_smoke.py -q`
Expected: all pass.

- [ ] **Step 7: Run the full suite**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest -q`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add src/stagetimer/ui/config_window.py tests/test_ui_smoke.py
git commit -m "feat: add Shrinkable/floor fields to the event editor and a Reset Schedule button"
```

---

### Task 8: Full-suite verification and manual smoke test

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/ -q`
Expected: all passing, zero failures, zero errors. (No single magic total is given here, deliberately — Task 3 involved a substantial rewrite rather than pure addition, so the exact final count depends on choices made during that task's implementation. What matters is 100% green, not matching a specific number.)

- [ ] **Step 2: Manual smoke test in windowed dev mode**

Seed a day (via the app's existing day-management UI or by hand-editing the active day's JSON file under `~/.local/share/stagetimer/days/`) with at least: one event anchored a few minutes in the past (so its target has already passed), one plain chained event, and one shrinkable event (with a floor) chained after the anchored one.

Run: `cd C:\Claude_Projekte\StageTimer && ./.venv/Scripts/python -m stagetimer --windowed`

Verify manually:
- On launch, with the first event's target time already in the past, the main display shows "Standing by" with the big clock already negative and red (`-MM:SS`), *not* auto-started — confirms no-auto-start end to end.
- Pressing Space starts the first event; the clock begins counting down normally from its full duration.
- Let the first event's countdown reach zero without pressing anything — it goes negative and red, keeps counting, and does not auto-advance.
- Press Space — advances to the next event. If the next event is the shrinkable one, its initial countdown reflects the accumulated lateness (a visibly reduced starting number, respecting its floor), with no special "compressed" indicator — just a plain countdown.
- The small readout under the big clock shows "SCHEDULE `X` BEHIND" in red once there's real lateness, and "ON SCHEDULE" in green once it resolves (e.g., after the shrinkable event fully absorbs the delay).
- Open Ctrl+E: confirm Right/N/Left/P/Up/Down/+/- no longer do anything on the *main display* (click into the main display window, try them — nothing happens), while Pause/Resume/Skip Prev/Skip Next/-1 min/+1 min all still work from the Ctrl+E Live Controls row. Click "Reset Schedule" mid-overtime and confirm the small readout immediately shows "ON SCHEDULE" while the big clock's own overtime number is untouched.
- In the event editor (Ctrl+E → Add/Edit), confirm the Shrinkable checkbox and its floor spinner appear between Duration and Description, and the floor spinner is disabled unless Shrinkable is checked.
- Close the app afterward.

- [ ] **Step 3: Deploy, if currently on the Pi's network**

Run: `cd C:\Claude_Projekte\StageTimer && .\deploy\sync.ps1 -PiHost admin@raspberrypi.local`

If not currently reachable, skip this step — everything up to here is fully verified locally and ready to push whenever the Pi is back on the network. Verify over SSH if deployed:

Run: `ssh admin@raspberrypi.local "ps aux | grep -v grep | grep stagetimer"`
Expected: a running `python -m stagetimer` process with a recent start time.
