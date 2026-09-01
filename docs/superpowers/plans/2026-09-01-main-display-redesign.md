# Main Display Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a live wall-clock top-right, a bigger blue-highlighted Current box top-left, and a scrolling mini-timetable overview bottom-right (current event highlighted green) to StageTimer's main display.

**Architecture:** Two small, pure, unit-testable additions to the core layer (`scheduler.compute_effective_start_times` and `TimerEngine.get_schedule_overview`) feed a new `MiniTimetable` widget and a plain real-time-clock `QLabel`, both wired into `MainDisplay`'s existing 200ms tick loop alongside the current mode-based rendering. `CurrentBox` gets restyled QSS only — no structural change.

**Tech Stack:** Python, PySide6 (Qt6), pytest (offscreen `QT_QPA_PLATFORM` for UI tests) — same as the rest of the project. No new dependencies.

---

## File Structure

| File | Change |
|---|---|
| `src/stagetimer/core/scheduler.py` | New public `compute_effective_start_times()` wrapping the existing private `_compute_effective_times()` |
| `src/stagetimer/core/state_machine.py` | New `ScheduleRow` dataclass; new `TimerEngine.get_schedule_overview()` |
| `src/stagetimer/config.py` | New `COLOR_ACCENT_BLUE`, `COLOR_SUCCESS_GREEN` constants |
| `src/stagetimer/ui/styles.py` | `CURRENT_BOX_QSS` restyled (blue border/tint, bigger name font); new `REALTIME_CLOCK_QSS`, `MINI_TIMETABLE_QSS` |
| `src/stagetimer/ui/display_widgets.py` | New `format_clock_time()`; new `MiniTimetable` widget |
| `src/stagetimer/ui/main_display.py` | Top row gains a real-time clock above the logo; bottom row gains the mini timetable beside NEXT; `_on_tick` refreshes both every tick |
| `tests/test_scheduler.py` | New tests for `compute_effective_start_times` |
| `tests/test_state_machine.py` | New tests for `get_schedule_overview` |
| `tests/test_display_widgets.py` | New tests for `format_clock_time` and `MiniTimetable` |
| `tests/test_ui_smoke.py` | New test confirming `MainDisplay` wires the two new widgets into its tick loop |

Task order: scheduler → state_machine → styling → widget → wiring → final verification. Each task leaves the suite green. Baseline before this plan: **65 passing tests**.

---

### Task 1: Expose effective start times from the scheduler

**Files:**
- Modify: `src/stagetimer/core/scheduler.py`
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scheduler.py` (the file already imports `Event`, `time`, and `scheduler`, and has an `at()` helper — reuse them, don't redefine):

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Claude_Projekte\StageTimer && ./.venv/Scripts/python -m pytest tests/test_scheduler.py -q`
Expected: the 3 new tests FAIL with `AttributeError: module 'stagetimer.core.scheduler' has no attribute 'compute_effective_start_times'`.

- [ ] **Step 3: Add the public wrapper function**

In `src/stagetimer/core/scheduler.py`, add this function directly after `_compute_effective_times` (before `def resolve(...)`):

```python
def compute_effective_start_times(events: list[Event]) -> list[int | None]:
    """Public wrapper around `_compute_effective_times` exposing just the
    effective start (seconds since midnight, or None if unreachable by wall
    clock) for each event, aligned by index with `events`. Used by the UI to
    show a clock time for every row in a full-timetable overview, including
    events that chain off a previous event's end rather than having their
    own `start_time`."""
    return [e.start for e in _compute_effective_times(events)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Claude_Projekte\StageTimer && ./.venv/Scripts/python -m pytest tests/test_scheduler.py -q`
Expected: `19 passed` (16 existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add src/stagetimer/core/scheduler.py tests/test_scheduler.py
git commit -m "feat: expose effective event start times from the scheduler"
```

---

### Task 2: Add a schedule overview to TimerEngine

**Files:**
- Modify: `src/stagetimer/core/state_machine.py`
- Test: `tests/test_state_machine.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_state_machine.py` (the file already has `make_engine`, `at()`, `TWO_EVENTS`, and `UNANCHORED_EVENTS` fixtures — reuse them):

```python
def test_schedule_overview_empty_timetable():
    engine = make_engine([])
    engine.tick(at(9, 0))
    assert engine.get_schedule_overview() == []


def test_schedule_overview_marks_current_row_while_running():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(9, 10))
    rows = engine.get_schedule_overview()
    assert [r.name for r in rows] == ["Keynote", "Panel"]
    assert rows[0].is_current is True
    assert rows[1].is_current is False
    assert rows[0].effective_start_seconds == 9 * 3600
    assert rows[0].duration_seconds == 1800


def test_schedule_overview_marks_current_row_while_paused():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(9, 10))
    engine.pause()
    rows = engine.get_schedule_overview()
    assert rows[0].is_current is True


def test_schedule_overview_no_current_row_before_first():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(8, 45))
    rows = engine.get_schedule_overview()
    assert all(not r.is_current for r in rows)


def test_schedule_overview_no_current_row_after_last():
    engine = make_engine(TWO_EVENTS)
    engine.tick(at(23, 0))
    rows = engine.get_schedule_overview()
    assert all(not r.is_current for r in rows)


def test_schedule_overview_no_current_row_awaiting_start():
    engine = make_engine(UNANCHORED_EVENTS)
    engine.tick(at(9, 0))
    rows = engine.get_schedule_overview()
    assert all(not r.is_current for r in rows)
    assert rows[0].effective_start_seconds is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Claude_Projekte\StageTimer && ./.venv/Scripts/python -m pytest tests/test_state_machine.py -q`
Expected: the 6 new tests FAIL with `AttributeError: 'TimerEngine' object has no attribute 'get_schedule_overview'`.

- [ ] **Step 3: Add the `ScheduleRow` dataclass**

In `src/stagetimer/core/state_machine.py`, add this right after the `DisplayState` dataclass (before `class TimerEngine:`):

```python
@dataclass(frozen=True)
class ScheduleRow:
    name: str
    duration_seconds: int
    effective_start_seconds: int | None
    is_current: bool
```

- [ ] **Step 4: Add `get_schedule_overview()` to `TimerEngine`**

Add this method at the end of the `TimerEngine` class, after `get_display_state`:

```python
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

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd C:\Claude_Projekte\StageTimer && ./.venv/Scripts/python -m pytest tests/test_state_machine.py -q`
Expected: `33 passed` (27 existing + 6 new).

- [ ] **Step 6: Commit**

```bash
git add src/stagetimer/core/state_machine.py tests/test_state_machine.py
git commit -m "feat: add TimerEngine.get_schedule_overview() for the mini timetable"
```

---

### Task 3: Add color constants and restyle the Current box

**Files:**
- Modify: `src/stagetimer/config.py`
- Modify: `src/stagetimer/ui/styles.py`

No test step — this task only changes style/color constants (plain strings), which have no behavior to unit test. Verified visually in Task 6's manual smoke test.

- [ ] **Step 1: Add the new color constants**

In `src/stagetimer/config.py`, change:

```python
# Colors
COLOR_NORMAL = "#FFFFFF"
COLOR_WARNING = "#FFD300"
COLOR_DANGER = "#FF3B30"
COLOR_FLASH_ALT = "#FFFFFF"
COLOR_BACKGROUND = "#000000"
```

to:

```python
# Colors
COLOR_NORMAL = "#FFFFFF"
COLOR_WARNING = "#FFD300"
COLOR_DANGER = "#FF3B30"
COLOR_FLASH_ALT = "#FFFFFF"
COLOR_BACKGROUND = "#000000"
COLOR_ACCENT_BLUE = "#3B82F6"
COLOR_SUCCESS_GREEN = "#22C55E"
```

- [ ] **Step 2: Restyle `CURRENT_BOX_QSS` and add the two new style constants**

In `src/stagetimer/ui/styles.py`, change:

```python
CURRENT_BOX_QSS = f"""
QFrame#currentBox {{
    border: 3px solid {config.COLOR_NORMAL};
    border-radius: 4px;
}}
QLabel#currentCaption {{
    color: {config.COLOR_NORMAL};
    font-size: 20px;
}}
QLabel#currentName {{
    color: {config.COLOR_NORMAL};
    font-size: 28px;
    font-weight: bold;
}}
"""

NEXT_LABEL_QSS = f"color: {config.COLOR_NORMAL}; font-size: 26px; font-weight: bold;"
NEXT_NAME_QSS = f"color: {config.COLOR_NORMAL}; font-size: 26px;"
NEXT_DURATION_QSS = f"color: {config.COLOR_NORMAL}; font-size: 22px;"

DIVIDER_QSS = f"background-color: {config.COLOR_NORMAL}; min-height: 2px; max-height: 2px;"
```

to:

```python
CURRENT_BOX_QSS = f"""
QFrame#currentBox {{
    border: 3px solid {config.COLOR_ACCENT_BLUE};
    background-color: rgba(59, 130, 246, 0.15);
    border-radius: 4px;
}}
QLabel#currentCaption {{
    color: {config.COLOR_NORMAL};
    font-size: 20px;
}}
QLabel#currentName {{
    color: {config.COLOR_NORMAL};
    font-size: 44px;
    font-weight: bold;
}}
"""

NEXT_LABEL_QSS = f"color: {config.COLOR_NORMAL}; font-size: 26px; font-weight: bold;"
NEXT_NAME_QSS = f"color: {config.COLOR_NORMAL}; font-size: 26px;"
NEXT_DURATION_QSS = f"color: {config.COLOR_NORMAL}; font-size: 22px;"

DIVIDER_QSS = f"background-color: {config.COLOR_NORMAL}; min-height: 2px; max-height: 2px;"

REALTIME_CLOCK_QSS = f"color: {config.COLOR_NORMAL}; font-size: 22px; font-weight: 600;"

MINI_TIMETABLE_QSS = f"""
QListWidget {{
    background: transparent;
    border: none;
    color: {config.COLOR_NORMAL};
    font-size: 13px;
}}
QListWidget::item {{
    padding: 1px 0;
}}
"""
```

- [ ] **Step 3: Run the full suite to confirm nothing broke**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/ -q`
Expected: `74 passed` (unchanged from Task 2's cumulative total — this task adds no tests, just confirms the QSS changes don't break anything that references these constants).

- [ ] **Step 4: Commit**

```bash
git add src/stagetimer/config.py src/stagetimer/ui/styles.py
git commit -m "feat: blue-highlight the Current box, add real-time-clock and mini-timetable styles"
```

---

### Task 4: Add the MiniTimetable widget

**Files:**
- Modify: `src/stagetimer/ui/display_widgets.py`
- Test: `tests/test_display_widgets.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_display_widgets.py`, change the import line:

```python
from stagetimer.ui.display_widgets import fit_clock_font_pixel_size, format_remaining
```

to:

```python
from stagetimer import config
from stagetimer.core.state_machine import ScheduleRow
from stagetimer.ui.display_widgets import (
    MiniTimetable,
    fit_clock_font_pixel_size,
    format_clock_time,
    format_remaining,
)
```

Then append these tests to the end of the file:

```python
def test_format_clock_time_none_is_dashes():
    assert format_clock_time(None) == "--:--"


def test_format_clock_time_formats_hh_mm():
    assert format_clock_time(9 * 3600 + 5 * 60) == "09:05"


def test_mini_timetable_set_rows_populates_list(qapp):
    rows = [
        ScheduleRow(name="Keynote", duration_seconds=1800, effective_start_seconds=9 * 3600, is_current=True),
        ScheduleRow(name="Panel", duration_seconds=1200, effective_start_seconds=None, is_current=False),
    ]
    widget = MiniTimetable()
    widget.set_rows(rows)
    assert widget.count() == 2
    assert "Keynote" in widget.item(0).text()
    assert "09:00" in widget.item(0).text()
    assert "--:--" in widget.item(1).text()


def test_mini_timetable_current_row_is_bold_and_green(qapp):
    rows = [ScheduleRow(name="Keynote", duration_seconds=1800, effective_start_seconds=9 * 3600, is_current=True)]
    widget = MiniTimetable()
    widget.set_rows(rows)
    item = widget.item(0)
    assert item.font().bold() is True
    assert item.foreground().color().name().lower() == config.COLOR_SUCCESS_GREEN.lower()


def test_mini_timetable_clears_previous_rows(qapp):
    widget = MiniTimetable()
    widget.set_rows([ScheduleRow(name="A", duration_seconds=60, effective_start_seconds=0, is_current=False)])
    widget.set_rows([ScheduleRow(name="B", duration_seconds=60, effective_start_seconds=0, is_current=False)])
    assert widget.count() == 1
    assert "B" in widget.item(0).text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_display_widgets.py -q`
Expected: FAIL — `ImportError: cannot import name 'MiniTimetable' from 'stagetimer.ui.display_widgets'` (and `format_clock_time`).

- [ ] **Step 3: Update imports in display_widgets.py**

In `src/stagetimer/ui/display_widgets.py`, change:

```python
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from stagetimer import config
from stagetimer.core.state_machine import ColorState
from stagetimer.ui import screen_metrics, styles
```

to:

```python
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from stagetimer import config
from stagetimer.core.state_machine import ColorState, ScheduleRow
from stagetimer.ui import screen_metrics, styles
```

- [ ] **Step 4: Add `format_clock_time`**

In `src/stagetimer/ui/display_widgets.py`, add this function directly after `format_remaining`:

```python
def format_clock_time(seconds: int | None) -> str:
    if seconds is None:
        return "--:--"
    total = seconds % (24 * 3600)
    hours, rem = divmod(total, 3600)
    minutes = rem // 60
    return f"{hours:02d}:{minutes:02d}"
```

- [ ] **Step 5: Add the `MiniTimetable` widget**

In `src/stagetimer/ui/display_widgets.py`, add this class after `NextBar` (at the end of the file):

```python
class MiniTimetable(QListWidget):
    """Compact read-only overview of the whole timetable, current event
    highlighted green and kept in view via auto-scroll."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(styles.MINI_TIMETABLE_QSS)

    def set_rows(self, rows: list[ScheduleRow]) -> None:
        self.clear()
        current_item: QListWidgetItem | None = None
        for row in rows:
            time_label = format_clock_time(row.effective_start_seconds)
            duration_label = format_remaining(row.duration_seconds)
            item = QListWidgetItem(f"{time_label}  {row.name}  ({duration_label})")
            if row.is_current:
                item.setForeground(QColor(config.COLOR_SUCCESS_GREEN))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                current_item = item
            self.addItem(item)
        if current_item is not None:
            self.scrollToItem(current_item, QAbstractItemView.ScrollHint.PositionAtCenter)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_display_widgets.py -q`
Expected: `10 passed` (5 existing + 5 new).

- [ ] **Step 7: Commit**

```bash
git add src/stagetimer/ui/display_widgets.py tests/test_display_widgets.py
git commit -m "feat: add MiniTimetable widget and format_clock_time helper"
```

---

### Task 5: Wire the real-time clock and mini timetable into MainDisplay

**Files:**
- Modify: `src/stagetimer/ui/main_display.py`
- Test: `tests/test_ui_smoke.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ui_smoke.py` (the file already has a module-scoped `qapp` fixture and a function-scoped `engine` fixture with two events, "Keynote" and "Panel" — reuse them):

```python
def test_main_display_shows_realtime_clock_and_mini_timetable(qapp, engine):
    display = MainDisplay(engine, kiosk=False)
    display._on_tick()
    assert display.realtime_clock.text() != ""
    assert ":" in display.realtime_clock.text()
    assert display.mini_timetable.count() == len(engine.timetable.events)
    display.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_ui_smoke.py::test_main_display_shows_realtime_clock_and_mini_timetable -v`
Expected: FAIL with `AttributeError: 'MainDisplay' object has no attribute 'realtime_clock'`.

- [ ] **Step 3: Replace the full contents of main_display.py**

Replace the full contents of `src/stagetimer/ui/main_display.py` with:

```python
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from stagetimer import config
from stagetimer.core.state_machine import ColorState, Mode, TimerEngine
from stagetimer.ui import styles
from stagetimer.ui.display_widgets import (
    ClockArea,
    CurrentBox,
    LogoBox,
    MiniTimetable,
    NextBar,
    format_remaining,
)

STANDBY_TEXT = "Standing by"
AWAITING_START_TEXT = "Standing by — press Start"
NO_EVENTS_TEXT = "No events scheduled"
DAY_COMPLETE_TEXT = "Day complete"
BLANK_CLOCK_TEXT = ""


class MainDisplay(QWidget):
    """Fullscreen audience-facing timer display."""

    def __init__(self, engine: TimerEngine, kiosk: bool = True, parent: QWidget | None = None):
        super().__init__(parent)
        self.engine = engine
        self._kiosk = kiosk

        self.setStyleSheet(styles.MAIN_WINDOW_QSS)
        self.setWindowTitle("StageTimer")

        self.current_box = CurrentBox()
        self.realtime_clock = QLabel()
        self.realtime_clock.setStyleSheet(styles.REALTIME_CLOCK_QSS)
        self.realtime_clock.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.logo_box = LogoBox()
        self.clock_area = ClockArea()
        self.clock = self.clock_area.clock
        self.next_bar = NextBar()
        self.mini_timetable = MiniTimetable()
        self.mini_timetable.setMinimumWidth(320)
        self.mini_timetable.setMaximumHeight(140)

        top_right_column = QVBoxLayout()
        top_right_column.addWidget(self.realtime_clock)
        top_right_column.addWidget(self.logo_box)

        top_row = QHBoxLayout()
        top_row.addWidget(self.current_box, 1)
        top_row.addLayout(top_right_column, 0)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet(styles.DIVIDER_QSS)

        bottom_row = QHBoxLayout()
        bottom_row.addWidget(self.next_bar, 1)
        bottom_row.addWidget(self.mini_timetable, 0)

        root = QVBoxLayout(self)
        root.addLayout(top_row)
        root.addWidget(self.clock_area, 1)
        root.addWidget(divider)
        root.addLayout(bottom_row)

        if kiosk:
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
            self.setCursor(Qt.CursorShape.BlankCursor)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(config.TICK_INTERVAL_MS)
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start()

        self._on_tick()

    def set_logo(self, path: str | None) -> None:
        self.logo_box.set_logo_path(path)

    def show_kiosk(self) -> None:
        if self._kiosk:
            self.showFullScreen()
        else:
            self.resize(1280, 800)
            self.show()
        self.setFocus()

    def _on_tick(self) -> None:
        self.engine.tick(datetime.now())
        state = self.engine.get_display_state()

        if state.mode == Mode.EMPTY:
            self.current_box.set_name(NO_EVENTS_TEXT)
            self.clock.set_time_and_state(BLANK_CLOCK_TEXT, ColorState.NORMAL)
            self.next_bar.set_next(None, None)
        elif state.mode == Mode.AWAITING_START:
            self.current_box.set_name(AWAITING_START_TEXT)
            self.clock.set_time_and_state(BLANK_CLOCK_TEXT, ColorState.NORMAL)
            self.next_bar.set_next(state.next_name, state.next_duration_seconds)
        elif state.mode == Mode.BEFORE_FIRST:
            self.current_box.set_name(STANDBY_TEXT)
            self.clock.set_time_and_state(format_remaining(state.remaining_seconds), ColorState.NORMAL)
            self.next_bar.set_next(state.next_name, state.next_duration_seconds)
        elif state.mode == Mode.AFTER_LAST:
            self.current_box.set_name(DAY_COMPLETE_TEXT)
            self.clock.set_time_and_state(BLANK_CLOCK_TEXT, ColorState.NORMAL)
            self.next_bar.set_next(None, None)
        else:  # RUNNING or PAUSED
            self.current_box.set_name(state.current_name)
            self.clock.set_time_and_state(format_remaining(state.remaining_seconds), state.color_state)
            self.next_bar.set_next(state.next_name, state.next_duration_seconds)

        self.realtime_clock.setText(datetime.now().strftime("%H:%M:%S"))
        self.mini_timetable.set_rows(self.engine.get_schedule_overview())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_ui_smoke.py -q`
Expected: `12 passed` (11 existing + 1 new).

- [ ] **Step 5: Commit**

```bash
git add src/stagetimer/ui/main_display.py tests/test_ui_smoke.py
git commit -m "feat: wire real-time clock and mini timetable into the main display"
```

---

### Task 6: Full-suite verification, manual smoke test, and deploy

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/ -q`
Expected: `80 passed` (65 baseline + 15 new across this plan: 3 scheduler + 6 state_machine + 5 display_widgets + 1 ui_smoke).

- [ ] **Step 2: Manual smoke test in windowed dev mode**

Run: `cd C:\Claude_Projekte\StageTimer && ./.venv/Scripts/python -m stagetimer --windowed`

Seed a test timetable at `~/.local/share/stagetimer/timetable.json` with at least 3-4 events (mix of timed and untimed, so both real clock times and chained "--:--"-then-computed rows are visible) before launching, and verify: the real-time clock (top-right, above the logo) shows the correct current time and ticks forward; the Current box (top-left) is visibly bigger with a blue border and blue-tinted background; the mini timetable (bottom-right) lists every event with time/name/duration, the currently-running one in bold green; skipping to a different event (Ctrl+E → Skip Next, or the `→`/`N` keyboard shortcut) moves the green highlight to the new current row and the panel auto-scrolls if needed. Close the app afterward.

- [ ] **Step 3: Sync and redeploy to the Pi (only once back on the same network as the Pi)**

Run: `cd C:\Claude_Projekte\StageTimer && .\deploy\sync.ps1 -PiHost admin@raspberrypi.local`

This also ships the earlier font/overflow bug fixes (commit `f39cfe3`), which haven't been deployed yet either. Verify over SSH:

Run: `ssh admin@raspberrypi.local "ps aux | grep -v grep | grep stagetimer"`
Expected: a running `python -m stagetimer` process with a recent start time.
