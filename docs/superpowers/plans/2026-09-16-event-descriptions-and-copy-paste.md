# Event Descriptions + Copy/Paste Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a free-text description per event — shown in the config window and on the main display (beside the Current event's name, in full underneath the Next event's name) — plus copy/paste for events in the config window.

**Architecture:** `Event` gains a `description` field that flows through persistence, the engine's `DisplayState`, and two UI surfaces (the config table/dialog, and the main display's `CurrentBox`/`NextBar` widgets). Copy/paste is config-window-local state (`ConfigWindow._clipboard_event`) plus one new `EventTableModel.insert_event()` method.

**Tech Stack:** Python, PySide6 (Qt6), pytest (offscreen `QT_QPA_PLATFORM`) — same as the rest of the project. No new dependencies.

---

## File Structure

| File | Change |
|---|---|
| `src/stagetimer/core/models.py` | `Event` gains `description: str = ""`, included in `to_dict()`/`from_dict()` |
| `src/stagetimer/core/state_machine.py` | `DisplayState` gains `current_description`/`next_description`, populated in every `get_display_state()` branch |
| `src/stagetimer/ui/event_table_model.py` | New "Description" column (truncated preview); new `insert_event(index, event)` method |
| `src/stagetimer/ui/config_window.py` | `EventEditDialog` gets a description text box; `ConfigWindow` gets Copy/Paste buttons + Ctrl+C/Ctrl+V |
| `src/stagetimer/ui/display_widgets.py` | `CurrentBox` shows description beside the name (elided); `NextBar` shows description under the name (full text, word-wrapped) |
| `src/stagetimer/ui/styles.py` | New `currentDescription`/`NEXT_DESCRIPTION_QSS` styles |
| `src/stagetimer/ui/main_display.py` | `_on_tick` passes descriptions into both widgets |
| `tests/test_persistence.py`, `tests/test_state_machine.py`, `tests/test_ui_smoke.py`, `tests/test_display_widgets.py` | New tests per task below |

**Task order and why it's sequential:** models → state_machine → event_table_model → config_window → display_widgets (CurrentBox) → display_widgets (NextBar) → main_display → verification. Each task builds on the previous one's additions (e.g., Task 2 needs `Event.description` from Task 1), and several tasks share a file with their neighbor (Tasks 3+4 both eventually touch `event_table_model.py`; Tasks 5+6 both touch `display_widgets.py`/`styles.py`). Per subagent-driven-development's own rules, implementer subagents are never dispatched in parallel regardless of file overlap — so this plan is fully sequential end to end; there's no safe parallelization opportunity within it. Baseline before this plan: **82 passing tests**.

---

### Task 1: Add `description` to the `Event` model

**Files:**
- Modify: `src/stagetimer/core/models.py`
- Test: `tests/test_persistence.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_persistence.py`:

```python
def test_save_then_load_roundtrip_with_description(tmp_path: Path):
    path = tmp_path / "timetable.json"
    original = Timetable(
        events=[
            Event(
                name="Keynote",
                start_time=time(9, 0, 0),
                duration_seconds=1800,
                description="Opening remarks\nand welcome",
            )
        ],
    )

    persistence.save(path, original)
    loaded = persistence.load(path)

    assert loaded.events[0].description == "Opening remarks\nand welcome"


def test_load_missing_description_defaults_to_empty_string(tmp_path: Path):
    path = tmp_path / "timetable.json"
    path.write_text(
        '{"version": 1, "logo_path": null, "events": ['
        '{"id": "x", "name": "Legacy", "start_time": null, "duration_seconds": 60}'
        ']}',
        encoding="utf-8",
    )

    loaded = persistence.load(path)

    assert loaded.events[0].description == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Claude_Projekte\StageTimer && ./.venv/Scripts/python -m pytest tests/test_persistence.py -q`
Expected: the 2 new tests FAIL — `TypeError: Event.__init__() got an unexpected keyword argument 'description'` for the first, `AttributeError: 'Event' object has no attribute 'description'` for the second.

- [ ] **Step 3: Add the field to `Event`**

In `src/stagetimer/core/models.py`, change:

```python
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Claude_Projekte\StageTimer && ./.venv/Scripts/python -m pytest tests/test_persistence.py -q`
Expected: `8 passed` (6 existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/stagetimer/core/models.py tests/test_persistence.py
git commit -m "feat: add description field to Event"
```

---

### Task 2: Surface descriptions through `DisplayState`

**Files:**
- Modify: `src/stagetimer/core/state_machine.py`
- Test: `tests/test_state_machine.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_state_machine.py`:

```python
# --- event descriptions -------------------------------------------------------

DESCRIBED_EVENTS = [
    Event(name="Keynote", start_time=time(9, 0, 0), duration_seconds=1800, description="Opening remarks"),
    Event(name="Panel", start_time=time(9, 30, 0), duration_seconds=1200, description="Q&A session"),
]


def test_display_state_carries_current_and_next_description_while_running():
    engine = make_engine(DESCRIBED_EVENTS)
    engine.tick(at(9, 10))
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


def test_display_state_no_description_after_last():
    engine = make_engine(DESCRIBED_EVENTS)
    engine.tick(at(23, 0))
    state = engine.get_display_state()
    assert state.current_description is None
    assert state.next_description is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Claude_Projekte\StageTimer && ./.venv/Scripts/python -m pytest tests/test_state_machine.py -q`
Expected: the 4 new tests FAIL with `AttributeError: 'DisplayState' object has no attribute 'current_description'`.

- [ ] **Step 3: Add the fields to `DisplayState`**

In `src/stagetimer/core/state_machine.py`, change:

```python
@dataclass(frozen=True)
class DisplayState:
    mode: Mode
    current_name: str | None
    remaining_seconds: float
    next_name: str | None
    next_duration_seconds: int | None
    color_state: ColorState
    is_paused: bool
```

to:

```python
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
```

- [ ] **Step 4: Populate the new fields in every branch of `get_display_state`**

Replace the full contents of `get_display_state` (from `def get_display_state(self) -> DisplayState:` to the end of the method) with:

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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd C:\Claude_Projekte\StageTimer && ./.venv/Scripts/python -m pytest tests/test_state_machine.py -q`
Expected: `37 passed` (33 existing + 4 new).

- [ ] **Step 6: Commit**

```bash
git add src/stagetimer/core/state_machine.py tests/test_state_machine.py
git commit -m "feat: surface event descriptions through DisplayState"
```

---

### Task 3: Add a Description column and `insert_event` to the table model

**Files:**
- Modify: `src/stagetimer/ui/event_table_model.py`
- Test: `tests/test_ui_smoke.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui_smoke.py` (the file already imports `Event`/`Timetable`/`time` and has a module-scoped `qapp` fixture — reuse them):

```python
def test_event_table_model_description_column_preview(qapp):
    from stagetimer.ui.event_table_model import EventTableModel

    long_text = "A" * 50
    model = EventTableModel(
        [Event(name="Keynote", start_time=time(9, 0), duration_seconds=600, description=long_text)]
    )
    index = model.index(0, 3)
    preview = model.data(index, Qt.ItemDataRole.DisplayRole)
    assert preview == "A" * 40 + "…"


def test_event_table_model_description_column_collapses_newlines(qapp):
    from stagetimer.ui.event_table_model import EventTableModel

    model = EventTableModel(
        [Event(name="Keynote", start_time=time(9, 0), duration_seconds=600, description="Line one\nLine two")]
    )
    index = model.index(0, 3)
    assert model.data(index, Qt.ItemDataRole.DisplayRole) == "Line one Line two"


def test_event_table_model_insert_event_at_specific_position(qapp):
    from stagetimer.ui.event_table_model import EventTableModel

    model = EventTableModel(
        [
            Event(name="A", start_time=time(9, 0), duration_seconds=60),
            Event(name="C", start_time=time(9, 10), duration_seconds=60),
        ]
    )
    model.insert_event(1, Event(name="B", start_time=time(9, 5), duration_seconds=60))
    assert [e.name for e in model.events()] == ["A", "B", "C"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_ui_smoke.py -k "description_column or insert_event" -v`
Expected: FAIL — `IndexError` (column 3 doesn't exist yet) and `AttributeError: 'EventTableModel' object has no attribute 'insert_event'`.

- [ ] **Step 3: Add the Description column and the preview helper**

In `src/stagetimer/ui/event_table_model.py`, change:

```python
COLUMNS = ["Name", "Start Time", "Duration"]
```

to:

```python
COLUMNS = ["Name", "Start Time", "Duration", "Description"]

DESCRIPTION_PREVIEW_MAX_CHARS = 40


def _description_preview(description: str) -> str:
    collapsed = " ".join(description.split("\n"))
    if len(collapsed) > DESCRIPTION_PREVIEW_MAX_CHARS:
        return collapsed[:DESCRIPTION_PREVIEW_MAX_CHARS] + "…"
    return collapsed
```

- [ ] **Step 4: Return the preview in `data()`**

Change:

```python
        if column == 2:
            return format_remaining(event.duration_seconds)
        return None
```

to:

```python
        if column == 2:
            return format_remaining(event.duration_seconds)
        if column == 3:
            return _description_preview(event.description)
        return None
```

- [ ] **Step 5: Add `insert_event`**

Add this method right after `add_event`:

```python
    def insert_event(self, index: int, event: Event) -> None:
        events = list(self._events)
        events.insert(index, event)
        self.set_events(events)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_ui_smoke.py -q`
Expected: `15 passed` (12 existing + 3 new).

- [ ] **Step 7: Commit**

```bash
git add src/stagetimer/ui/event_table_model.py tests/test_ui_smoke.py
git commit -m "feat: add Description column and insert_event to the timetable table model"
```

---

### Task 4: Description field in the editor + Copy/Paste in the config window

**Files:**
- Modify: `src/stagetimer/ui/config_window.py`
- Test: `tests/test_ui_smoke.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui_smoke.py`:

```python
def test_event_edit_dialog_description_field_round_trips(qapp):
    from stagetimer.ui.config_window import EventEditDialog

    dialog = EventEditDialog()
    dialog.name_edit.setText("Keynote")
    dialog.description_edit.setPlainText("Opening remarks\nand welcome")
    dialog._on_accept()
    result = dialog.result_event()
    assert result.description == "Opening remarks\nand welcome"


def test_event_edit_dialog_prefills_description_from_existing_event(qapp):
    from stagetimer.ui.config_window import EventEditDialog

    event = Event(name="Keynote", start_time=time(9, 0), duration_seconds=600, description="Existing notes")
    dialog = EventEditDialog(event=event)
    assert dialog.description_edit.toPlainText() == "Existing notes"


def test_config_window_copy_paste_duplicates_selected_event(qapp, engine):
    timetable = Timetable(
        events=[
            Event(name="Keynote", start_time=time(9, 0), duration_seconds=600, description="Notes"),
            Event(name="Panel", start_time=time(9, 30), duration_seconds=600),
        ]
    )
    engine.set_timetable(timetable)
    window = ConfigWindow(engine, timetable, on_logo_changed=lambda p: None)

    window.table.selectRow(0)
    window._copy_selected()
    window._paste_event()

    events = window.model.events()
    assert [e.name for e in events] == ["Keynote", "Keynote", "Panel"]
    assert events[1].description == "Notes"
    assert events[1].id != events[0].id
    assert events[1].start_time == events[0].start_time
    window.close()


def test_config_window_paste_without_copy_is_noop(qapp, engine):
    timetable = Timetable(events=[Event(name="Keynote", start_time=time(9, 0), duration_seconds=600)])
    engine.set_timetable(timetable)
    window = ConfigWindow(engine, timetable, on_logo_changed=lambda p: None)

    window._paste_event()
    assert len(window.model.events()) == 1
    window.close()


def test_config_window_repeated_paste_stacks_copies(qapp, engine):
    timetable = Timetable(events=[Event(name="Changeover", start_time=None, duration_seconds=300)])
    engine.set_timetable(timetable)
    window = ConfigWindow(engine, timetable, on_logo_changed=lambda p: None)

    window.table.selectRow(0)
    window._copy_selected()
    window._paste_event()
    window._paste_event()

    assert [e.name for e in window.model.events()] == ["Changeover", "Changeover", "Changeover"]
    window.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_ui_smoke.py -k "description_field or copy_paste or paste_without_copy or repeated_paste" -v`
Expected: FAIL — `AttributeError: 'EventEditDialog' object has no attribute 'description_edit'` and `AttributeError: 'ConfigWindow' object has no attribute '_copy_selected'`.

- [ ] **Step 3: Add imports**

In `src/stagetimer/ui/config_window.py`, change:

```python
from __future__ import annotations

import shutil
from datetime import time
from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableView,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)
```

to:

```python
from __future__ import annotations

import dataclasses
import shutil
import uuid
from datetime import time
from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableView,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)
```

- [ ] **Step 4: Add the description box to `EventEditDialog`**

Change:

```python
        total_minutes = (event.duration_seconds // 60) if event else 15
        self.duration_minutes = QSpinBox()
        self.duration_minutes.setRange(0, 24 * 60)
        self.duration_minutes.setSuffix(" min")
        self.duration_minutes.setValue(total_minutes)

        form = QFormLayout()
        form.addRow("Name:", self.name_edit)
        form.addRow("Start time:", start_row)
        form.addRow("Duration:", self.duration_minutes)
```

to:

```python
        total_minutes = (event.duration_seconds // 60) if event else 15
        self.duration_minutes = QSpinBox()
        self.duration_minutes.setRange(0, 24 * 60)
        self.duration_minutes.setSuffix(" min")
        self.duration_minutes.setValue(total_minutes)

        self.description_edit = QTextEdit(event.description if event else "")
        self.description_edit.setFixedHeight(80)

        form = QFormLayout()
        form.addRow("Name:", self.name_edit)
        form.addRow("Start time:", start_row)
        form.addRow("Duration:", self.duration_minutes)
        form.addRow("Description:", self.description_edit)
```

- [ ] **Step 5: Include the description when building the result `Event`**

Change:

```python
        duration_seconds = self.duration_minutes.value() * 60

        kwargs = dict(name=name, start_time=start_time, duration_seconds=duration_seconds)
```

to:

```python
        duration_seconds = self.duration_minutes.value() * 60
        description = self.description_edit.toPlainText().strip()

        kwargs = dict(name=name, start_time=start_time, duration_seconds=duration_seconds, description=description)
```

- [ ] **Step 6: Add Copy/Paste buttons and clipboard state**

Change:

```python
        table_buttons = QHBoxLayout()
        add_btn = QPushButton("Add")
        edit_btn = QPushButton("Edit")
        delete_btn = QPushButton("Delete")
        up_btn = QPushButton("Move Up")
        down_btn = QPushButton("Move Down")
        add_btn.clicked.connect(self._add_event)
        edit_btn.clicked.connect(self._edit_selected)
        delete_btn.clicked.connect(self._delete_selected)
        up_btn.clicked.connect(lambda: self._move_selected(-1))
        down_btn.clicked.connect(lambda: self._move_selected(1))
        for btn in (add_btn, edit_btn, delete_btn, up_btn, down_btn):
            table_buttons.addWidget(btn)
        table_buttons.addStretch(1)
```

to:

```python
        table_buttons = QHBoxLayout()
        add_btn = QPushButton("Add")
        edit_btn = QPushButton("Edit")
        delete_btn = QPushButton("Delete")
        copy_btn = QPushButton("Copy")
        paste_btn = QPushButton("Paste")
        up_btn = QPushButton("Move Up")
        down_btn = QPushButton("Move Down")
        add_btn.clicked.connect(self._add_event)
        edit_btn.clicked.connect(self._edit_selected)
        delete_btn.clicked.connect(self._delete_selected)
        copy_btn.clicked.connect(self._copy_selected)
        paste_btn.clicked.connect(self._paste_event)
        up_btn.clicked.connect(lambda: self._move_selected(-1))
        down_btn.clicked.connect(lambda: self._move_selected(1))
        for btn in (add_btn, edit_btn, delete_btn, copy_btn, paste_btn, up_btn, down_btn):
            table_buttons.addWidget(btn)
        table_buttons.addStretch(1)

        self._clipboard_event: Event | None = None
```

- [ ] **Step 7: Add the Ctrl+C/Ctrl+V shortcuts**

Change:

```python
        QShortcut(QKeySequence("Escape"), self, activated=self.close)
```

to:

```python
        QShortcut(QKeySequence("Escape"), self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+C"), self, activated=self._copy_selected)
        QShortcut(QKeySequence("Ctrl+V"), self, activated=self._paste_event)
```

- [ ] **Step 8: Add the `_copy_selected` and `_paste_event` methods**

Add these right after `_delete_selected`:

```python
    def _copy_selected(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        self._clipboard_event = self.model.event_at(row)

    def _paste_event(self) -> None:
        if self._clipboard_event is None:
            return
        duplicate = dataclasses.replace(self._clipboard_event, id=str(uuid.uuid4()))
        row = self._selected_row()
        insert_at = (row + 1) if row is not None else len(self.model.events())
        self.model.insert_event(insert_at, duplicate)
        self._persist_and_apply()
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_ui_smoke.py -q`
Expected: `20 passed` (15 existing + 5 new).

- [ ] **Step 10: Commit**

```bash
git add src/stagetimer/ui/config_window.py tests/test_ui_smoke.py
git commit -m "feat: add description field and copy/paste to the config window"
```

---

### Task 5: Show the description beside the name in the Current box

**Files:**
- Modify: `src/stagetimer/ui/display_widgets.py`
- Modify: `src/stagetimer/ui/styles.py`
- Test: `tests/test_display_widgets.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_display_widgets.py`:

```python
def test_current_box_shows_description_next_to_name(qapp):
    from stagetimer.ui.display_widgets import CurrentBox

    box = CurrentBox()
    box.set_name("Keynote")
    box.set_description("Opening remarks")
    assert box._description.text() == "Opening remarks"


def test_current_box_elides_long_description(qapp):
    from stagetimer.ui.display_widgets import CurrentBox

    box = CurrentBox()
    box._description.setFixedWidth(80)
    box.set_name("Keynote")
    long_text = "This is a very long description that will not fit in the available space at all"
    box.set_description(long_text)
    assert box._description.text() != long_text
    assert box._description.text().endswith("…")


def test_current_box_clears_description(qapp):
    from stagetimer.ui.display_widgets import CurrentBox

    box = CurrentBox()
    box.set_name("Keynote")
    box.set_description("Some notes")
    box.set_description(None)
    assert box._description.text() == ""


def test_current_box_collapses_newlines_in_description(qapp):
    from stagetimer.ui.display_widgets import CurrentBox

    box = CurrentBox()
    box.set_description("Line one\nLine two")
    assert "\n" not in box._description.text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_display_widgets.py -k current_box -v`
Expected: FAIL with `AttributeError: 'CurrentBox' object has no attribute 'set_description'`.

- [ ] **Step 3: Restructure `CurrentBox`**

Replace the full `CurrentBox` class with:

```python
class CurrentBox(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("currentBox")
        self.setStyleSheet(styles.CURRENT_BOX_QSS)

        self._caption = QLabel("Current")
        self._caption.setObjectName("currentCaption")

        self._name = QLabel("")
        self._name.setObjectName("currentName")
        self._name.setWordWrap(True)

        self._description = QLabel("")
        self._description.setObjectName("currentDescription")
        self._description_full_text = ""

        name_row = QHBoxLayout()
        name_row.addWidget(self._name, 0)
        name_row.addWidget(self._description, 1)

        layout = QVBoxLayout(self)
        layout.addWidget(self._caption)
        layout.addLayout(name_row)

    def set_name(self, name: str | None) -> None:
        self._name.setText(name or "")

    def set_description(self, description: str | None) -> None:
        self._description_full_text = (description or "").strip().replace("\n", " ")
        self._update_description_elision()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._update_description_elision()

    def _update_description_elision(self) -> None:
        if not self._description_full_text:
            self._description.setText("")
            return
        metrics = QFontMetrics(self._description.font())
        available = max(0, self._description.width())
        elided = metrics.elidedText(self._description_full_text, Qt.TextElideMode.ElideRight, available)
        self._description.setText(elided)
```

- [ ] **Step 4: Add the `currentDescription` style**

In `src/stagetimer/ui/styles.py`, change:

```python
QLabel#currentName {{
    color: {config.COLOR_NORMAL};
    font-size: 44px;
    font-weight: bold;
}}
"""
```

to:

```python
QLabel#currentName {{
    color: {config.COLOR_NORMAL};
    font-size: 44px;
    font-weight: bold;
}}
QLabel#currentDescription {{
    color: {config.COLOR_NORMAL};
    font-size: 22px;
    padding-left: 12px;
}}
"""
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_display_widgets.py -q`
Expected: `16 passed` (12 existing + 4 new).

- [ ] **Step 6: Commit**

```bash
git add src/stagetimer/ui/display_widgets.py src/stagetimer/ui/styles.py tests/test_display_widgets.py
git commit -m "feat: show event description beside the name in the Current box"
```

---

### Task 6: Show the full description under the name in the Next bar

**Files:**
- Modify: `src/stagetimer/ui/display_widgets.py`
- Modify: `src/stagetimer/ui/styles.py`
- Test: `tests/test_display_widgets.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_display_widgets.py`:

```python
def test_next_bar_shows_description_when_present(qapp):
    from stagetimer.ui.display_widgets import NextBar

    bar = NextBar()
    bar.show()
    bar.set_next("Panel", 1200, "Bring extra mics")
    assert bar._description.text() == "Bring extra mics"
    assert bar._description.isVisible() is True


def test_next_bar_hides_description_row_when_absent(qapp):
    from stagetimer.ui.display_widgets import NextBar

    bar = NextBar()
    bar.show()
    bar.set_next("Panel", 1200, None)
    assert bar._description.isVisible() is False


def test_next_bar_description_word_wraps_not_truncated(qapp):
    from stagetimer.ui.display_widgets import NextBar

    bar = NextBar()
    long_text = "This is a fairly long description with several words that should wrap across multiple lines"
    bar.set_next("Panel", 1200, long_text)
    assert bar._description.text() == long_text
    assert bar._description.wordWrap() is True


def test_next_bar_hides_entirely_when_no_next_event(qapp):
    from stagetimer.ui.display_widgets import NextBar

    bar = NextBar()
    bar.show()
    bar.set_next("Panel", 1200, "notes")
    bar.set_next(None, None)
    assert bar.isVisible() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_display_widgets.py -k next_bar -v`
Expected: FAIL — `TypeError: NextBar.set_next() takes 3 positional arguments but 4 were given` and `AttributeError: 'NextBar' object has no attribute '_description'`.

- [ ] **Step 3: Restructure `NextBar`**

Replace the full `NextBar` class with:

```python
class NextBar(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        top_row = QHBoxLayout()
        left = QHBoxLayout()
        self._label = QLabel("NEXT")
        self._label.setStyleSheet(styles.NEXT_LABEL_QSS)
        self._name = QLabel("")
        self._name.setStyleSheet(styles.NEXT_NAME_QSS)
        left.addWidget(self._label)
        left.addWidget(self._name)
        left.addStretch(1)

        self._duration = QLabel("")
        self._duration.setStyleSheet(styles.NEXT_DURATION_QSS)
        self._duration.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        top_row.addLayout(left, 1)
        top_row.addWidget(self._duration)

        self._description = QLabel("")
        self._description.setObjectName("nextDescription")
        self._description.setWordWrap(True)
        self._description.setStyleSheet(styles.NEXT_DESCRIPTION_QSS)
        self._description.setVisible(False)

        outer.addLayout(top_row)
        outer.addWidget(self._description)

    def set_next(self, name: str | None, duration_seconds: int | None, description: str | None = None) -> None:
        if name is None:
            self.setVisible(False)
            return
        self.setVisible(True)
        self._name.setText(name)
        self._duration.setText(f"-{format_remaining(duration_seconds or 0)}")
        text = (description or "").strip()
        self._description.setText(text)
        self._description.setVisible(bool(text))
```

- [ ] **Step 4: Add the `NEXT_DESCRIPTION_QSS` style**

In `src/stagetimer/ui/styles.py`, change:

```python
MINI_TIMETABLE_QSS = f"""
```

to:

```python
NEXT_DESCRIPTION_QSS = f"color: {config.COLOR_NORMAL}; font-size: 18px;"

MINI_TIMETABLE_QSS = f"""
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_display_widgets.py -q`
Expected: `20 passed` (16 existing + 4 new).

- [ ] **Step 6: Commit**

```bash
git add src/stagetimer/ui/display_widgets.py src/stagetimer/ui/styles.py tests/test_display_widgets.py
git commit -m "feat: show full event description under the name in the Next bar"
```

---

### Task 7: Wire descriptions into `MainDisplay`

**Files:**
- Modify: `src/stagetimer/ui/main_display.py`
- Test: `tests/test_ui_smoke.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ui_smoke.py`:

```python
def test_main_display_shows_current_and_next_descriptions(qapp):
    timetable = Timetable(
        events=[
            Event(name="Keynote", start_time=None, duration_seconds=1800, description="Opening remarks"),
            Event(name="Panel", start_time=None, duration_seconds=1200, description="Q&A session"),
        ]
    )
    engine = TimerEngine(timetable)
    engine.start()
    display = MainDisplay(engine, kiosk=False)
    display._on_tick()
    assert display.current_box._description_full_text == "Opening remarks"
    assert display.next_bar._description.text() == "Q&A session"
    display.close()
```

Note: this uses `engine.start()` (not a wall-clock `engine.tick(fixed_time)`) to force a deterministic `RUNNING` state — `start()` jumps to event 0 immediately regardless of real time, unlike wall-clock-anchored events whose resolved state depends on `datetime.now()` at the moment `MainDisplay._on_tick()` internally calls `engine.tick(datetime.now())`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_ui_smoke.py::test_main_display_shows_current_and_next_descriptions -v`
Expected: FAIL with `AttributeError: 'CurrentBox' object has no attribute '_description_full_text'` — or, once Tasks 5/6 are in place, the assertion fails because `main_display.py` doesn't call `set_description`/pass the description argument yet (both `_description_full_text` and `next_bar._description.text()` stay empty).

- [ ] **Step 3: Update `_on_tick`**

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
            self.clock.set_time_and_state(format_remaining(state.remaining_seconds), ColorState.NORMAL)
            self.next_bar.set_next(state.next_name, state.next_duration_seconds, state.next_description)
        elif state.mode == Mode.AFTER_LAST:
            self.current_box.set_name(DAY_COMPLETE_TEXT)
            self.current_box.set_description(None)
            self.clock.set_time_and_state(BLANK_CLOCK_TEXT, ColorState.NORMAL)
            self.next_bar.set_next(None, None)
        else:  # RUNNING or PAUSED
            self.current_box.set_name(state.current_name)
            self.current_box.set_description(state.current_description)
            self.clock.set_time_and_state(format_remaining(state.remaining_seconds), state.color_state)
            self.next_bar.set_next(state.next_name, state.next_duration_seconds, state.next_description)

        self.realtime_clock.setText(datetime.now().strftime("%H:%M:%S"))
        self.mini_timetable.set_rows(self.engine.get_schedule_overview())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_ui_smoke.py -q`
Expected: `21 passed` (20 existing + 1 new).

- [ ] **Step 5: Commit**

```bash
git add src/stagetimer/ui/main_display.py tests/test_ui_smoke.py
git commit -m "feat: wire event descriptions into the main display"
```

---

### Task 8: Full-suite verification and manual smoke test

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/ -q`
Expected: `105 passed` (82 baseline + 23 new across this plan: 2 persistence + 4 state_machine + 3+5 ui_smoke table/config + 4+4 display_widgets Current/Next + 1 ui_smoke wiring).

- [ ] **Step 2: Manual smoke test in windowed dev mode**

Run: `cd C:\Claude_Projekte\StageTimer && ./.venv/Scripts/python -m stagetimer --windowed`

Seed `~/.local/share/stagetimer/timetable.json` with at least one currently-running event that has a multi-line description and one upcoming event with a longer description, then verify: the Current box shows the running event's name with its description to the right (truncated with "…" if the window is narrow); the Next bar grows taller to show the upcoming event's full description wrapped under its name, with no truncation; opening Ctrl+E shows the new Description column (truncated preview) and the multi-line text box in Add/Edit; selecting a row and pressing Ctrl+C then Ctrl+V (and the Copy/Paste buttons) inserts a duplicate directly below with a fresh ID; repeated Ctrl+V keeps stacking copies. Close the app afterward.

- [ ] **Step 3: Deploy, if currently on the Pi's network**

Run: `cd C:\Claude_Projekte\StageTimer && .\deploy\sync.ps1 -PiHost admin@raspberrypi.local`

If not currently reachable, skip this step — everything up to here is fully verified locally and ready to push whenever the Pi is back on the network. Verify over SSH if deployed:

Run: `ssh admin@raspberrypi.local "ps aux | grep -v grep | grep stagetimer"`
Expected: a running `python -m stagetimer` process with a recent start time.
