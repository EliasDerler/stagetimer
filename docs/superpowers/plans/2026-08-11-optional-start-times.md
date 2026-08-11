# Optional Event Start Times + Start Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `Event.start_time` optional, generalize the scheduler so unanchored events chain off the previous event's end, add a `TimerEngine.start()` that jumps straight to event 1, and expose both in the UI (a checkbox in the event editor, a Start button in the config window's Live Controls).

**Architecture:** One rule drives everything: each event's *effective* start is its own `start_time` if set, otherwise the previous event's effective end (chained). Events with no effective start at all (no anchor anywhere before them) are invisible to wall-clock resolution — only `TimerEngine.start()` / `skip_next()` / `skip_prev()` can reach them. This lives entirely in `core/scheduler.py`'s `resolve()`; `core/state_machine.py` gets one new `Mode.AWAITING_START` and a thin `start()` wrapper around the existing `_jump_to()` machinery. UI changes are additive: a checkbox toggling a `QTimeEdit`, and a button gated on engine mode via a small polling timer (the codebase has no engine-change signal yet, so this task adds a lightweight local `QTimer` in `ConfigWindow` rather than inventing a pub/sub system).

**Tech Stack:** Python, PySide6 (Qt6), pytest (offscreen `QT_QPA_PLATFORM` for UI tests) — same as the rest of the project. No new dependencies.

---

## File Structure

| File | Change |
|---|---|
| `src/stagetimer/core/models.py` | `Event.start_time: time \| None`; `to_dict`/`from_dict` handle `None`; drop unused `end_time_seconds` property; `Timetable.sorted_events()` stops sorting, returns list order |
| `src/stagetimer/core/scheduler.py` | Full rewrite of `resolve()` around a new effective-time computation; new `"AWAITING_START"` resolution mode |
| `src/stagetimer/core/state_machine.py` | New `Mode.AWAITING_START`; new `TimerEngine.start()`; `get_display_state()` gets an `AWAITING_START` branch |
| `src/stagetimer/ui/config_window.py` | `EventEditDialog` gets a "Has start time" checkbox; `ConfigWindow` gets a Start button + a 250ms polling timer to keep it enabled/disabled correctly |
| `src/stagetimer/ui/event_table_model.py` | Start Time column blank for untimed events; `set_events()` stops sorting |
| `src/stagetimer/ui/main_display.py` | New `Mode.AWAITING_START` branch, distinct "press Start" text |
| `tests/test_persistence.py` | Update the now-incorrect sort test; add a `start_time=None` round-trip test |
| `tests/test_scheduler.py` | New tests for the effective-time chaining rule |
| `tests/test_state_machine.py` | New tests for `AWAITING_START` and `start()` |
| `tests/test_ui_smoke.py` | New tests for the checkbox and the Start button's enabled state |

Task order: models → scheduler → state_machine → UI layers → final full-suite run. Each task leaves the test suite green.

---

### Task 1: Make `Event.start_time` optional in the data model

**Files:**
- Modify: `src/stagetimer/core/models.py`
- Modify: `tests/test_persistence.py`
- Test: `tests/test_persistence.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_persistence.py`, replace the existing `test_save_sorts_events_by_start_time` (it asserts behavior this change removes — persistence no longer re-sorts) with a list-order test, and add a new round-trip test for `start_time=None`:

```python
def test_save_preserves_list_order(tmp_path: Path):
    path = tmp_path / "timetable.json"
    unsorted = Timetable(
        events=[
            Event(name="Second", start_time=time(10, 0, 0), duration_seconds=600),
            Event(name="First", start_time=time(9, 0, 0), duration_seconds=600),
        ]
    )

    persistence.save(path, unsorted)
    loaded = persistence.load(path)

    assert [e.name for e in loaded.events] == ["Second", "First"]


def test_save_then_load_roundtrip_with_no_start_time(tmp_path: Path):
    path = tmp_path / "timetable.json"
    original = Timetable(
        events=[Event(name="Freeform", start_time=None, duration_seconds=300)],
    )

    persistence.save(path, original)
    loaded = persistence.load(path)

    assert loaded.events[0].start_time is None
    assert loaded.events[0].duration_seconds == 300
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Claude_Projekte\StageTimer && ./.venv/Scripts/python -m pytest tests/test_persistence.py -q`
Expected: `test_save_preserves_list_order` FAILs (current code sorts, so order comes back `["First", "Second"]` not `["Second", "First"]`). `test_save_then_load_roundtrip_with_no_start_time` FAILs with an `AttributeError` (`Event(..., start_time=None, ...)` then `.strftime` on `None` inside `to_dict()`).

- [ ] **Step 3: Rewrite `Event` and `Timetable` in models.py**

Replace the full contents of `src/stagetimer/core/models.py` with:

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import time


@dataclass
class Event:
    name: str
    start_time: time | None
    duration_seconds: int
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "start_time": self.start_time.strftime("%H:%M:%S") if self.start_time else None,
            "duration_seconds": self.duration_seconds,
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
        )


@dataclass
class Timetable:
    events: list[Event] = field(default_factory=list)
    logo_path: str | None = None
    version: int = 1

    def sorted_events(self) -> list[Event]:
        """Returns events in list order (the order they'll play in) — despite
        the name, this no longer sorts by start_time, since start_time can be
        None. List order is the source of truth for playback order; the
        config window's Move Up/Move Down buttons are how operators reorder
        it."""
        return list(self.events)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "logo_path": self.logo_path,
            "events": [e.to_dict() for e in self.sorted_events()],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Timetable":
        events = [Event.from_dict(e) for e in data.get("events", [])]
        return cls(
            events=events,
            logo_path=data.get("logo_path"),
            version=data.get("version", 1),
        )
```

Note: this drops the `end_time_seconds` property entirely — it's only used by `scheduler.py`, which Task 2 rewrites to compute effective end times itself instead.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Claude_Projekte\StageTimer && ./.venv/Scripts/python -m pytest tests/test_persistence.py -q`
Expected: `6 passed` (the file had 5 tests; this step renames one in place and adds one new one, for a net +1).

- [ ] **Step 5: Commit**

```bash
git add src/stagetimer/core/models.py tests/test_persistence.py
git commit -m "feat: make Event.start_time optional, drop start-time sorting"
```

---

### Task 2: Rewrite the scheduler around effective-time chaining

**Files:**
- Modify: `src/stagetimer/core/scheduler.py`
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: Write the failing tests**

Append these to `tests/test_scheduler.py` (keep the existing `EVENTS`, `at()`, and all existing tests as-is — they exercise fully-anchored timetables and must keep passing unchanged):

```python
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
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `cd C:\Claude_Projekte\StageTimer && ./.venv/Scripts/python -m pytest tests/test_scheduler.py -q`
Expected: the 4 new tests FAIL (current `resolve()` calls `event.end_time_seconds`, which no longer exists after Task 1 — `AttributeError`), 12 existing tests still pass or also error out the same way since `EVENTS` fixtures still use `end_time_seconds` internally via the old `resolve()`.

- [ ] **Step 3: Rewrite scheduler.py**

Replace the full contents of `src/stagetimer/core/scheduler.py` with:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Claude_Projekte\StageTimer && ./.venv/Scripts/python -m pytest tests/test_scheduler.py -q`
Expected: `16 passed` (12 existing + 4 new).

- [ ] **Step 5: Commit**

```bash
git add src/stagetimer/core/scheduler.py tests/test_scheduler.py
git commit -m "feat: chain unanchored events off the previous event's effective end"
```

---

### Task 3: Add `Mode.AWAITING_START` and `TimerEngine.start()`

**Files:**
- Modify: `src/stagetimer/core/state_machine.py`
- Test: `tests/test_state_machine.py`

- [ ] **Step 1: Write the failing tests**

Append these to `tests/test_state_machine.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Claude_Projekte\StageTimer && ./.venv/Scripts/python -m pytest tests/test_state_machine.py -q`
Expected: the 5 new tests FAIL — `Mode.AWAITING_START` doesn't exist yet (`AttributeError`), and `engine.start()` doesn't exist (`AttributeError`).

- [ ] **Step 3: Add `Mode.AWAITING_START`**

In `src/stagetimer/core/state_machine.py`, change:

```python
class Mode(Enum):
    EMPTY = "EMPTY"
    BEFORE_FIRST = "BEFORE_FIRST"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    AFTER_LAST = "AFTER_LAST"
```

to:

```python
class Mode(Enum):
    EMPTY = "EMPTY"
    AWAITING_START = "AWAITING_START"
    BEFORE_FIRST = "BEFORE_FIRST"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    AFTER_LAST = "AFTER_LAST"
```

- [ ] **Step 4: Handle the new resolution mode in `_tick_from_wallclock`**

Change:

```python
        if resolution.mode == "EMPTY":
            self._mode = Mode.EMPTY
        elif resolution.mode == "BEFORE_FIRST":
```

to:

```python
        if resolution.mode == "EMPTY":
            self._mode = Mode.EMPTY
        elif resolution.mode == "AWAITING_START":
            self._mode = Mode.AWAITING_START
        elif resolution.mode == "BEFORE_FIRST":
```

- [ ] **Step 5: Add `start()`**

In `src/stagetimer/core/state_machine.py`, add this method right after `resume()` (before `skip_next()`):

```python
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
```

- [ ] **Step 6: Handle `AWAITING_START` in `get_display_state()`**

Change:

```python
    def get_display_state(self) -> DisplayState:
        if self._mode == Mode.EMPTY or self._current_index is None:
            return DisplayState(
                mode=self._mode,
                current_name=None,
                remaining_seconds=0,
                next_name=None,
                next_duration_seconds=None,
                color_state=ColorState.NORMAL,
                is_paused=False,
            )

        if self._mode == Mode.BEFORE_FIRST:
```

to:

```python
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
            )

        if self._mode == Mode.BEFORE_FIRST:
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd C:\Claude_Projekte\StageTimer && ./.venv/Scripts/python -m pytest tests/test_state_machine.py -q`
Expected: `27 passed` (22 existing + 5 new).

- [ ] **Step 8: Commit**

```bash
git add src/stagetimer/core/state_machine.py tests/test_state_machine.py
git commit -m "feat: add AWAITING_START mode and TimerEngine.start()"
```

---

### Task 4: Blank Start Time column + stop sorting in the table model

**Files:**
- Modify: `src/stagetimer/ui/event_table_model.py`
- Test: `tests/test_ui_smoke.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ui_smoke.py`:

```python
def test_event_table_model_blank_start_time_for_untimed_event(qapp):
    from stagetimer.ui.event_table_model import EventTableModel

    model = EventTableModel([Event(name="Freeform", start_time=None, duration_seconds=300)])
    index = model.index(0, 1)
    assert model.data(index, Qt.ItemDataRole.DisplayRole) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_ui_smoke.py::test_event_table_model_blank_start_time_for_untimed_event -v`
Expected: FAIL with `AttributeError: 'NoneType' object has no attribute 'strftime'`.

- [ ] **Step 3: Update `data()` and `set_events()`**

In `src/stagetimer/ui/event_table_model.py`, change:

```python
        if column == 1:
            return event.start_time.strftime("%H:%M")
```

to:

```python
        if column == 1:
            return event.start_time.strftime("%H:%M") if event.start_time else ""
```

And change:

```python
    def set_events(self, events: list[Event]) -> None:
        self.beginResetModel()
        self._events = sorted(events, key=lambda e: e.start_time)
        self.endResetModel()
```

to:

```python
    def set_events(self, events: list[Event]) -> None:
        self.beginResetModel()
        self._events = list(events)
        self.endResetModel()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_ui_smoke.py -q`
Expected: `7 passed` (6 existing + 1 new).

- [ ] **Step 5: Commit**

```bash
git add src/stagetimer/ui/event_table_model.py tests/test_ui_smoke.py
git commit -m "feat: blank Start Time column for untimed events, stop re-sorting on edit"
```

---

### Task 5: Add the "Has start time" checkbox to the event editor

**Files:**
- Modify: `src/stagetimer/ui/config_window.py`
- Test: `tests/test_ui_smoke.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ui_smoke.py`:

```python
def test_event_edit_dialog_checkbox_controls_start_time(qapp):
    from stagetimer.ui.config_window import EventEditDialog

    dialog = EventEditDialog()
    assert dialog.has_start_time.isChecked() is True
    assert dialog.start_edit.isEnabled() is True

    dialog.has_start_time.setChecked(False)
    assert dialog.start_edit.isEnabled() is False

    dialog.name_edit.setText("Freeform Session")
    dialog._on_accept()
    result = dialog.result_event()
    assert result.start_time is None
    assert result.name == "Freeform Session"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_ui_smoke.py::test_event_edit_dialog_checkbox_controls_start_time -v`
Expected: FAIL with `AttributeError: 'EventEditDialog' object has no attribute 'has_start_time'`.

- [ ] **Step 3: Add `QCheckBox` to the imports**

In `src/stagetimer/ui/config_window.py`, change:

```python
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
```

to:

```python
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
```

- [ ] **Step 4: Add the checkbox to `EventEditDialog.__init__`**

Change:

```python
        self.start_edit = QTimeEdit()
        self.start_edit.setDisplayFormat("HH:mm")
        start = event.start_time if event else time(9, 0)
        self.start_edit.setTime(start)
```

to:

```python
        self.has_start_time = QCheckBox("Has start time")
        has_time = event.start_time is not None if event else True
        self.has_start_time.setChecked(has_time)

        self.start_edit = QTimeEdit()
        self.start_edit.setDisplayFormat("HH:mm")
        start = event.start_time if (event and event.start_time) else time(9, 0)
        self.start_edit.setTime(start)
        self.start_edit.setEnabled(has_time)
        self.has_start_time.toggled.connect(self.start_edit.setEnabled)

        start_row = QHBoxLayout()
        start_row.addWidget(self.has_start_time)
        start_row.addWidget(self.start_edit)
```

- [ ] **Step 5: Use the row layout in the form**

Change:

```python
        form.addRow("Start time:", self.start_edit)
```

to:

```python
        form.addRow("Start time:", start_row)
```

- [ ] **Step 6: Make `_on_accept` respect the checkbox**

Change:

```python
        qt_time = self.start_edit.time()
        start_time = time(qt_time.hour(), qt_time.minute(), 0)
        duration_seconds = self.duration_minutes.value() * 60
```

to:

```python
        if self.has_start_time.isChecked():
            qt_time = self.start_edit.time()
            start_time = time(qt_time.hour(), qt_time.minute(), 0)
        else:
            start_time = None
        duration_seconds = self.duration_minutes.value() * 60
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_ui_smoke.py -q`
Expected: `8 passed`.

- [ ] **Step 8: Commit**

```bash
git add src/stagetimer/ui/config_window.py tests/test_ui_smoke.py
git commit -m "feat: add Has start time checkbox to the event editor"
```

---

### Task 6: Add the Start button to Live Controls

**Files:**
- Modify: `src/stagetimer/ui/config_window.py`
- Test: `tests/test_ui_smoke.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ui_smoke.py`:

```python
def test_config_window_start_button_enabled_state(qapp, engine):
    from stagetimer.core.state_machine import Mode

    timetable = Timetable(events=[Event(name="Freeform", start_time=None, duration_seconds=300)])
    engine.set_timetable(timetable)
    engine.tick(__import__("datetime").datetime(2026, 8, 11, 9, 0))
    assert engine.get_display_state().mode == Mode.AWAITING_START

    window = ConfigWindow(engine, timetable, on_logo_changed=lambda p: None)
    window._refresh_start_button()
    assert window._start_btn.isEnabled() is True

    engine.start()
    window._refresh_start_button()
    assert window._start_btn.isEnabled() is False
    window.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_ui_smoke.py::test_config_window_start_button_enabled_state -v`
Expected: FAIL with `AttributeError: 'ConfigWindow' object has no attribute '_start_btn'`.

- [ ] **Step 3: Import `QTimer` and `Mode`**

In `src/stagetimer/ui/config_window.py`, change:

```python
from PySide6.QtCore import Qt
```

to:

```python
from PySide6.QtCore import Qt, QTimer
```

and change:

```python
from stagetimer.core.state_machine import TimerEngine
```

to:

```python
from stagetimer.core.state_machine import Mode, TimerEngine
```

- [ ] **Step 4: Add the Start button to Live Controls**

Change:

```python
        pause_btn = QPushButton("Pause")
        resume_btn = QPushButton("Resume")
        prev_btn = QPushButton("« Skip Prev")
        next_btn = QPushButton("Skip Next »")
        minus_btn = QPushButton("-1 min")
        plus_btn = QPushButton("+1 min")
        pause_btn.clicked.connect(self.engine.pause)
        resume_btn.clicked.connect(self.engine.resume)
        prev_btn.clicked.connect(self.engine.skip_prev)
        next_btn.clicked.connect(self.engine.skip_next)
        minus_btn.clicked.connect(lambda: self.engine.adjust(-60))
        plus_btn.clicked.connect(lambda: self.engine.adjust(60))

        controls_row = QHBoxLayout()
        for btn in (prev_btn, pause_btn, resume_btn, next_btn, minus_btn, plus_btn):
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

        self._start_btn = start_btn
```

- [ ] **Step 5: Add a polling timer that keeps the Start button's enabled state correct**

Change:

```python
        root = QVBoxLayout(self)
        root.addWidget(timetable_box, 1)
        root.addWidget(logo_box)
        root.addWidget(controls_box)

        QShortcut(QKeySequence("Escape"), self, activated=self.close)
```

to:

```python
        root = QVBoxLayout(self)
        root.addWidget(timetable_box, 1)
        root.addWidget(logo_box)
        root.addWidget(controls_box)

        QShortcut(QKeySequence("Escape"), self, activated=self.close)

        # ConfigWindow and MainDisplay share one TimerEngine but each owns its
        # own polling loop (there's no engine-change signal) — this timer
        # keeps the Start button's enabled state in sync with engine mode.
        self._start_refresh_timer = QTimer(self)
        self._start_refresh_timer.setInterval(250)
        self._start_refresh_timer.timeout.connect(self._refresh_start_button)
        self._start_refresh_timer.start()
        self._refresh_start_button()
```

- [ ] **Step 6: Add the `_refresh_start_button` method**

Add this method to `ConfigWindow`, right after `_selected_row`:

```python
    def _refresh_start_button(self) -> None:
        mode = self.engine.get_display_state().mode
        self._start_btn.setEnabled(mode in (Mode.EMPTY, Mode.AWAITING_START, Mode.AFTER_LAST))
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_ui_smoke.py -q`
Expected: `9 passed`.

- [ ] **Step 8: Commit**

```bash
git add src/stagetimer/ui/config_window.py tests/test_ui_smoke.py
git commit -m "feat: add Start button to Live Controls, gated on engine mode"
```

---

### Task 7: Show "press Start" on the main display in `AWAITING_START`

**Files:**
- Modify: `src/stagetimer/ui/main_display.py`
- Test: `tests/test_ui_smoke.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ui_smoke.py`:

```python
def test_main_display_shows_awaiting_start_text(qapp):
    from stagetimer.ui.main_display import AWAITING_START_TEXT

    timetable = Timetable(events=[Event(name="Freeform", start_time=None, duration_seconds=300)])
    engine = TimerEngine(timetable)
    display = MainDisplay(engine, kiosk=False)
    engine.tick(__import__("datetime").datetime(2026, 8, 11, 9, 0))
    display._on_tick()
    assert display.current_box._name.text() == AWAITING_START_TEXT
    display.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_ui_smoke.py::test_main_display_shows_awaiting_start_text -v`
Expected: FAIL with `ImportError: cannot import name 'AWAITING_START_TEXT'`.

- [ ] **Step 3: Add the text constant and the `AWAITING_START` branch**

In `src/stagetimer/ui/main_display.py`, change:

```python
STANDBY_TEXT = "Standing by"
NO_EVENTS_TEXT = "No events scheduled"
```

to:

```python
STANDBY_TEXT = "Standing by"
AWAITING_START_TEXT = "Standing by — press Start"
NO_EVENTS_TEXT = "No events scheduled"
```

Change:

```python
        if state.mode == Mode.EMPTY:
            self.current_box.set_name(NO_EVENTS_TEXT)
            self.clock.set_time_and_state(EMPTY_CLOCK_TEXT, ColorState.NORMAL)
            self.next_bar.set_next(None, None)
        elif state.mode == Mode.BEFORE_FIRST:
```

to:

```python
        if state.mode == Mode.EMPTY:
            self.current_box.set_name(NO_EVENTS_TEXT)
            self.clock.set_time_and_state(EMPTY_CLOCK_TEXT, ColorState.NORMAL)
            self.next_bar.set_next(None, None)
        elif state.mode == Mode.AWAITING_START:
            self.current_box.set_name(AWAITING_START_TEXT)
            self.clock.set_time_and_state(EMPTY_CLOCK_TEXT, ColorState.NORMAL)
            self.next_bar.set_next(state.next_name, state.next_duration_seconds)
        elif state.mode == Mode.BEFORE_FIRST:
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_ui_smoke.py -q`
Expected: `10 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/stagetimer/ui/main_display.py tests/test_ui_smoke.py
git commit -m "feat: show press-Start text on main display in AWAITING_START"
```

---

### Task 8: Full-suite verification and manual smoke test

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/ -q`
Expected: `59 passed` (45 previous + 14 new: +1 persistence, +4 scheduler, +5 state_machine, +4 ui_smoke).

- [ ] **Step 2: Manual smoke test in windowed dev mode**

Run: `cd C:\Claude_Projekte\StageTimer && ./.venv/Scripts/python -m stagetimer --windowed`

With an empty or all-untimed `data/timetable.json`, verify: main display shows "Standing by — press Start"; opening the config window (Ctrl+E) shows an enabled Start button; adding an event via the "Add" button shows the "Has start time" checkbox checked by default, and unchecking it greys out the time field; saving an event with the checkbox unchecked and clicking Start begins that event immediately with its full duration and the clock counting down; the Start button becomes disabled while it's running. Close the app afterward.

- [ ] **Step 3: Sync and redeploy to the Pi (optional, only if hardware validation is wanted now)**

Run: `cd C:\Claude_Projekte\StageTimer && .\deploy\sync.ps1 -PiHost admin@raspberrypi.local`

This reinstalls the package into the Pi's venv and restarts the kiosk process (the labwc autostart loop relaunches it within ~2s). Verify over SSH:

Run: `ssh admin@raspberrypi.local "ps aux | grep -v grep | grep stagetimer"`
Expected: a running `python -m stagetimer` process with a recent start time.
