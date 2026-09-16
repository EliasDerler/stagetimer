# Multi-Day Timetable Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the operator create, switch between, rename, and delete multiple named "days" (distinct timetables), with the last-active day remembered across restarts, surfaced through a new "Day" menu in the config window.

**Architecture:** A new `core/day_store.py` module owns multi-file persistence (`days/<uuid>.json` per day, plus a small `active_day.json` pointer) on top of the existing, unchanged `Timetable`/`Event` schema and `persistence.py` atomic-write pattern. `ConfigWindow` gains a `QMenuBar` "Day" menu and switches its single `_persist_and_apply` save call from the legacy single-file `persistence.save` to `day_store.save_day`. Both the days directory and the active-day pointer are injectable constructor parameters on `ConfigWindow` (defaulting to the real `config.DAYS_DIR`/`config.ACTIVE_DAY_PATH`), so tests can point them at an isolated `tmp_path` instead of touching the developer's real data directory. `app.py`'s startup sequence migrates the legacy single timetable into a first day the first time this code runs, then always boots from whichever day was last active.

**Tech Stack:** Python, PySide6 (Qt6), pytest (offscreen `QT_QPA_PLATFORM`) — same as the rest of the project. No new dependencies.

---

## File Structure

| File | Change |
|---|---|
| `src/stagetimer/config.py` | New `DAYS_DIR`/`ACTIVE_DAY_PATH` constants |
| `src/stagetimer/core/day_store.py` | New module: `DayMeta`, list/load/save/create/rename/delete day, active-day pointer, startup migration |
| `src/stagetimer/ui/config_window.py` | New "Day" menu (`QMenuBar`), title bar shows active day, `_persist_and_apply` uses `day_store`, days/active-day paths are injectable |
| `src/stagetimer/app.py` | Startup uses `day_store.ensure_startup_day`/`load_day`; `ConfigWindow` gets `active_day_id`/`on_day_changed` |
| `tests/test_day_store.py`, `tests/test_ui_smoke.py` | New tests per task below |

**Task order and why it's sequential:** `day_store.py` (Task 1) is a pure data-layer dependency of everything else. `config_window.py` (Task 2) needs `day_store` to exist first, and needs at least two days to test switching against (created directly via `day_store.create_day` against an isolated `tmp_path`, not through UI — no dependency on Task 3). `app.py` (Task 3) needs `ConfigWindow`'s new constructor parameters (`active_day_id`, `on_day_changed`) to already exist. Task 4 is verification only. Per subagent-driven-development's own rules, implementer subagents are never dispatched in parallel regardless of file overlap — so this plan is fully sequential end to end. Baseline before this plan: **108 passing tests**.

---

### Task 1: `core/day_store.py` — the data layer

**Files:**
- Modify: `src/stagetimer/config.py`
- Create: `src/stagetimer/core/day_store.py`
- Test: `tests/test_day_store.py` (new file)

- [ ] **Step 1: Add the new path constants**

In `src/stagetimer/config.py`, change:

```python
DATA_DIR = Path.home() / ".local" / "share" / "stagetimer"
TIMETABLE_PATH = DATA_DIR / "timetable.json"
LOGO_PATH = DATA_DIR / "logo.png"
```

to:

```python
DATA_DIR = Path.home() / ".local" / "share" / "stagetimer"
TIMETABLE_PATH = DATA_DIR / "timetable.json"
LOGO_PATH = DATA_DIR / "logo.png"
DAYS_DIR = DATA_DIR / "days"
ACTIVE_DAY_PATH = DATA_DIR / "active_day.json"
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_day_store.py`:

```python
import json
from pathlib import Path

import pytest

from stagetimer.core import day_store
from stagetimer.core.models import Event, Timetable


@pytest.fixture
def days_dir(tmp_path: Path) -> Path:
    return tmp_path / "days"


@pytest.fixture
def active_day_path(tmp_path: Path) -> Path:
    return tmp_path / "active_day.json"


def test_create_then_load_day_roundtrip(days_dir):
    timetable = Timetable(events=[Event(name="Keynote", start_time=None, duration_seconds=600)])
    day_id = day_store.create_day(days_dir, "Friday", timetable)

    loaded = day_store.load_day(days_dir, day_id)

    assert [e.name for e in loaded.events] == ["Keynote"]


def test_create_day_defaults_to_empty_timetable(days_dir):
    day_id = day_store.create_day(days_dir, "Friday")

    loaded = day_store.load_day(days_dir, day_id)

    assert loaded.events == []


def test_list_days_returns_names_sorted(days_dir):
    day_store.create_day(days_dir, "Saturday")
    day_store.create_day(days_dir, "Friday")

    names = [d.name for d in day_store.list_days(days_dir)]

    assert names == ["Friday", "Saturday"]


def test_list_days_on_missing_directory_returns_empty(days_dir):
    assert day_store.list_days(days_dir) == []


def test_save_day_overwrites_existing_day(days_dir):
    day_id = day_store.create_day(days_dir, "Friday", Timetable(events=[Event(name="A", start_time=None, duration_seconds=60)]))

    day_store.save_day(days_dir, day_id, "Friday", Timetable(events=[Event(name="B", start_time=None, duration_seconds=60)]))

    loaded = day_store.load_day(days_dir, day_id)
    assert [e.name for e in loaded.events] == ["B"]
    assert len(day_store.list_days(days_dir)) == 1


def test_rename_day_keeps_id_and_events_changes_name(days_dir):
    day_id = day_store.create_day(days_dir, "Friday", Timetable(events=[Event(name="A", start_time=None, duration_seconds=60)]))

    day_store.rename_day(days_dir, day_id, "Opening Night")

    days = day_store.list_days(days_dir)
    assert len(days) == 1
    assert days[0].id == day_id
    assert days[0].name == "Opening Night"
    assert [e.name for e in day_store.load_day(days_dir, day_id).events] == ["A"]


def test_delete_day_removes_it(days_dir):
    day_id = day_store.create_day(days_dir, "Friday")
    other_id = day_store.create_day(days_dir, "Saturday")

    day_store.delete_day(days_dir, day_id)

    assert [d.id for d in day_store.list_days(days_dir)] == [other_id]


def test_delete_nonexistent_day_is_noop(days_dir):
    day_store.delete_day(days_dir, "does-not-exist")
    assert day_store.list_days(days_dir) == []


def test_load_day_missing_file_returns_empty_timetable(days_dir):
    result = day_store.load_day(days_dir, "does-not-exist")
    assert result.events == []


def test_load_day_corrupt_file_backs_up_and_returns_empty(days_dir):
    days_dir.mkdir(parents=True)
    bad_path = days_dir / "bad-id.json"
    bad_path.write_text("{not valid json", encoding="utf-8")

    result = day_store.load_day(days_dir, "bad-id")

    assert result.events == []
    backups = list(days_dir.glob("bad-id.json.bak-*"))
    assert len(backups) == 1
    assert not bad_path.exists()


def test_list_days_skips_and_backs_up_corrupt_file(days_dir):
    days_dir.mkdir(parents=True)
    (days_dir / "bad-id.json").write_text("{not valid json", encoding="utf-8")
    day_store.create_day(days_dir, "Friday")

    days = day_store.list_days(days_dir)

    assert [d.name for d in days] == ["Friday"]
    assert list(days_dir.glob("bad-id.json.bak-*"))


def test_active_day_roundtrip(active_day_path):
    assert day_store.get_active_day_id(active_day_path) is None

    day_store.set_active_day_id(active_day_path, "abc-123")
    assert day_store.get_active_day_id(active_day_path) == "abc-123"


def test_clear_active_day_removes_pointer(active_day_path):
    day_store.set_active_day_id(active_day_path, "abc-123")
    day_store.clear_active_day(active_day_path)
    assert day_store.get_active_day_id(active_day_path) is None


def test_clear_active_day_when_nothing_set_is_noop(active_day_path):
    day_store.clear_active_day(active_day_path)
    assert day_store.get_active_day_id(active_day_path) is None


def test_ensure_startup_day_uses_valid_active_pointer(days_dir, active_day_path, tmp_path):
    day_a = day_store.create_day(days_dir, "Friday")
    day_store.create_day(days_dir, "Saturday")
    day_store.set_active_day_id(active_day_path, day_a)

    result = day_store.ensure_startup_day(days_dir, active_day_path, tmp_path / "legacy.json")

    assert result == day_a


def test_ensure_startup_day_falls_back_when_active_pointer_is_stale(days_dir, active_day_path, tmp_path):
    day_store.create_day(days_dir, "Friday")
    day_store.set_active_day_id(active_day_path, "some-id-that-was-deleted")

    result = day_store.ensure_startup_day(days_dir, active_day_path, tmp_path / "legacy.json")

    assert result in [d.id for d in day_store.list_days(days_dir)]
    assert day_store.get_active_day_id(active_day_path) == result


def test_ensure_startup_day_migrates_legacy_timetable(days_dir, active_day_path, tmp_path):
    legacy_path = tmp_path / "legacy.json"
    legacy_path.write_text(
        json.dumps(
            {
                "version": 1,
                "logo_path": None,
                "events": [{"id": "x", "name": "Legacy Event", "start_time": None, "duration_seconds": 60}],
            }
        ),
        encoding="utf-8",
    )

    result = day_store.ensure_startup_day(days_dir, active_day_path, legacy_path)

    days = day_store.list_days(days_dir)
    assert len(days) == 1
    assert days[0].name == "Day 1"
    assert [e.name for e in day_store.load_day(days_dir, result).events] == ["Legacy Event"]
    assert legacy_path.exists()  # left untouched, not deleted
    assert day_store.get_active_day_id(active_day_path) == result


def test_ensure_startup_day_creates_empty_day_1_when_nothing_exists(days_dir, active_day_path, tmp_path):
    result = day_store.ensure_startup_day(days_dir, active_day_path, tmp_path / "legacy.json")

    days = day_store.list_days(days_dir)
    assert len(days) == 1
    assert days[0].name == "Day 1"
    assert day_store.load_day(days_dir, result).events == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd C:\Claude_Projekte\StageTimer && ./.venv/Scripts/python -m pytest tests/test_day_store.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'stagetimer.core.day_store'`.

- [ ] **Step 4: Implement `core/day_store.py`**

Create `src/stagetimer/core/day_store.py`:

```python
from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from stagetimer.core import persistence
from stagetimer.core.models import Timetable

DAY_NAME_FALLBACK = "Day 1"


@dataclass
class DayMeta:
    id: str
    name: str
    modified_at: float


def _day_path(days_dir: Path, day_id: str) -> Path:
    return days_dir / f"{day_id}.json"


def _backup_corrupt_file(path: Path) -> None:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_name(f"{path.name}.bak-{timestamp}")
    try:
        path.replace(backup_path)
        print(f"stagetimer: backed up corrupt day file to {backup_path}", file=sys.stderr)
    except OSError as exc:
        print(f"stagetimer: failed to back up corrupt day file {path}: {exc}", file=sys.stderr)


def list_days(days_dir: Path) -> list[DayMeta]:
    if not days_dir.exists():
        return []
    metas: list[DayMeta] = []
    for path in days_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            metas.append(DayMeta(id=data["id"], name=data["name"], modified_at=path.stat().st_mtime))
        except (json.JSONDecodeError, KeyError, TypeError, OSError) as exc:
            print(f"stagetimer: failed to read day file {path}: {exc}", file=sys.stderr)
            _backup_corrupt_file(path)
    return sorted(metas, key=lambda m: m.name)


def load_day(days_dir: Path, day_id: str) -> Timetable:
    path = _day_path(days_dir, day_id)
    if not path.exists():
        return Timetable()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Timetable.from_dict(data["timetable"])
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        print(f"stagetimer: failed to load day {path}: {exc}", file=sys.stderr)
        _backup_corrupt_file(path)
        return Timetable()


def save_day(days_dir: Path, day_id: str, name: str, timetable: Timetable) -> None:
    days_dir.mkdir(parents=True, exist_ok=True)
    path = _day_path(days_dir, day_id)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    data = {"id": day_id, "name": name, "timetable": timetable.to_dict()}
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def create_day(days_dir: Path, name: str, timetable: Timetable | None = None) -> str:
    day_id = str(uuid.uuid4())
    save_day(days_dir, day_id, name, timetable if timetable is not None else Timetable())
    return day_id


def rename_day(days_dir: Path, day_id: str, new_name: str) -> None:
    timetable = load_day(days_dir, day_id)
    save_day(days_dir, day_id, new_name, timetable)


def delete_day(days_dir: Path, day_id: str) -> None:
    path = _day_path(days_dir, day_id)
    if path.exists():
        path.unlink()


def get_active_day_id(active_day_path: Path) -> str | None:
    if not active_day_path.exists():
        return None
    try:
        data = json.loads(active_day_path.read_text(encoding="utf-8"))
        return data.get("active_day_id")
    except (json.JSONDecodeError, OSError):
        return None


def set_active_day_id(active_day_path: Path, day_id: str) -> None:
    active_day_path.parent.mkdir(parents=True, exist_ok=True)
    active_day_path.write_text(json.dumps({"active_day_id": day_id}), encoding="utf-8")


def clear_active_day(active_day_path: Path) -> None:
    if active_day_path.exists():
        active_day_path.unlink()


def ensure_startup_day(days_dir: Path, active_day_path: Path, legacy_timetable_path: Path) -> str:
    days = list_days(days_dir)
    if days:
        active_id = get_active_day_id(active_day_path)
        if active_id and any(d.id == active_id for d in days):
            return active_id
        fallback_id = days[0].id
        set_active_day_id(active_day_path, fallback_id)
        return fallback_id

    if legacy_timetable_path.exists():
        legacy_timetable = persistence.load(legacy_timetable_path)
        day_id = create_day(days_dir, DAY_NAME_FALLBACK, legacy_timetable)
        set_active_day_id(active_day_path, day_id)
        return day_id

    day_id = create_day(days_dir, DAY_NAME_FALLBACK, Timetable())
    set_active_day_id(active_day_path, day_id)
    return day_id
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd C:\Claude_Projekte\StageTimer && ./.venv/Scripts/python -m pytest tests/test_day_store.py -q`
Expected: `19 passed`.

- [ ] **Step 6: Run the full suite to confirm no regressions**

Run: `cd C:\Claude_Projekte\StageTimer && ./.venv/Scripts/python -m pytest -q`
Expected: `127 passed` (108 baseline + 19 new).

- [ ] **Step 7: Commit**

```bash
git add src/stagetimer/config.py src/stagetimer/core/day_store.py tests/test_day_store.py
git commit -m "feat: add day_store module for multi-day timetable persistence"
```

---

### Task 2: `ConfigWindow` — the Day menu

**Files:**
- Modify: `src/stagetimer/ui/config_window.py`
- Test: `tests/test_ui_smoke.py`

**Context for the implementer:** `ConfigWindow` is a plain `QWidget` (not `QMainWindow`), so it doesn't get a menu bar automatically — Qt supports attaching one to any layout via `layout.setMenuBar(menu_bar)`, which is the mechanism this task uses. `ConfigWindow.__init__` currently has the signature `(self, engine, timetable, on_logo_changed, parent=None)`; this task adds four new parameters — `active_day_id`, `on_day_changed`, `days_dir`, `active_day_path` — all with defaults so every existing test/call site that doesn't care about day management keeps working unchanged. `days_dir`/`active_day_path` default to the real `config.DAYS_DIR`/`config.ACTIVE_DAY_PATH` (so `app.py`, updated in Task 3, never needs to pass them), but **this task's own new tests must pass `tmp_path`-based values for both**, so they never read or write the developer's real `~/.local/share/stagetimer` directory. (Note: this codebase's *existing* `ConfigWindow` tests, from earlier plans, do already write to the real `config.TIMETABLE_PATH`/`config.LOGO_PATH` via `_persist_and_apply`/`_choose_logo` — that pre-existing gap is not this task's to fix, but the new day-management tests should not add to it, since day-deletion tests in particular would give false results if a real day happens to already exist in the shared directory.)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui_smoke.py`. Every test below constructs its own isolated `days_dir`/`active_day_path` under pytest's `tmp_path`, so none of them touch real data and none need manual cleanup:

```python
def test_config_window_day_menu_lists_and_checks_active_day(qapp, engine, tmp_path):
    from stagetimer.core import day_store

    days_dir = tmp_path / "days"
    active_day_path = tmp_path / "active_day.json"
    timetable = Timetable(events=[Event(name="Keynote", start_time=None, duration_seconds=600)])
    day_a = day_store.create_day(days_dir, "Friday", timetable)
    day_store.create_day(days_dir, "Saturday")

    window = ConfigWindow(
        engine, timetable, lambda p: None, day_a, lambda d: None, days_dir=days_dir, active_day_path=active_day_path
    )
    window._refresh_day_menu()
    checkable_actions = [a for a in window._day_menu.actions() if a.isCheckable()]
    names = {a.text() for a in checkable_actions}
    assert names == {"Friday", "Saturday"}
    checked = [a.text() for a in checkable_actions if a.isChecked()]
    assert checked == ["Friday"]
    assert window.windowTitle().endswith("Friday")
    window.close()


def test_config_window_switch_day_updates_model_and_engine(qapp, engine, tmp_path):
    from stagetimer.core import day_store

    days_dir = tmp_path / "days"
    active_day_path = tmp_path / "active_day.json"
    timetable_a = Timetable(events=[Event(name="Keynote", start_time=None, duration_seconds=600)])
    timetable_b = Timetable(events=[Event(name="Panel", start_time=None, duration_seconds=600)])
    day_a = day_store.create_day(days_dir, "Friday", timetable_a)
    day_b = day_store.create_day(days_dir, "Saturday", timetable_b)
    engine.set_timetable(timetable_a)

    window = ConfigWindow(
        engine, timetable_a, lambda p: None, day_a, lambda d: None, days_dir=days_dir, active_day_path=active_day_path
    )
    window._switch_to_day(day_b)

    assert [e.name for e in window.model.events()] == ["Panel"]
    assert [e.name for e in engine.timetable.events] == ["Panel"]
    assert window._active_day_id == day_b
    assert day_store.get_active_day_id(active_day_path) == day_b
    window.close()


def test_config_window_switch_to_same_day_is_noop(qapp, engine, tmp_path):
    from stagetimer.core import day_store

    days_dir = tmp_path / "days"
    active_day_path = tmp_path / "active_day.json"
    timetable = Timetable(events=[Event(name="Keynote", start_time=None, duration_seconds=600)])
    day_a = day_store.create_day(days_dir, "Friday", timetable)

    window = ConfigWindow(
        engine, timetable, lambda p: None, day_a, lambda d: None, days_dir=days_dir, active_day_path=active_day_path
    )
    window._switch_to_day(day_a)
    assert window._active_day_id == day_a
    window.close()


def test_config_window_switch_while_running_requires_confirmation(qapp, engine, monkeypatch, tmp_path):
    from stagetimer.core import day_store
    from stagetimer.ui.config_window import QMessageBox

    days_dir = tmp_path / "days"
    active_day_path = tmp_path / "active_day.json"
    timetable_a = Timetable(events=[Event(name="Keynote", start_time=None, duration_seconds=600)])
    timetable_b = Timetable(events=[Event(name="Panel", start_time=None, duration_seconds=600)])
    day_a = day_store.create_day(days_dir, "Friday", timetable_a)
    day_b = day_store.create_day(days_dir, "Saturday", timetable_b)
    engine.set_timetable(timetable_a)
    engine.start()

    window = ConfigWindow(
        engine, timetable_a, lambda p: None, day_a, lambda d: None, days_dir=days_dir, active_day_path=active_day_path
    )

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    window._switch_to_day(day_b)
    assert window._active_day_id == day_a  # declined, stayed put

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    window._switch_to_day(day_b)
    assert window._active_day_id == day_b  # confirmed, switched

    window.close()


def test_config_window_new_day_empty(qapp, engine, monkeypatch, tmp_path):
    from stagetimer.core import day_store
    from stagetimer.ui.config_window import QInputDialog

    days_dir = tmp_path / "days"
    active_day_path = tmp_path / "active_day.json"
    timetable = Timetable(events=[Event(name="Keynote", start_time=None, duration_seconds=600)])
    day_a = day_store.create_day(days_dir, "Friday", timetable)

    window = ConfigWindow(
        engine, timetable, lambda p: None, day_a, lambda d: None, days_dir=days_dir, active_day_path=active_day_path
    )

    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Saturday", True))

    class FakeMsg:
        def __init__(self, *a, **k):
            pass

        def setWindowTitle(self, *a):
            pass

        def setText(self, *a):
            pass

        def addButton(self, label, role):
            return label

        def exec(self):
            pass

        def clickedButton(self):
            return "Empty"

    monkeypatch.setattr("stagetimer.ui.config_window.QMessageBox", FakeMsg)
    window._new_day()

    assert window._active_day_name == "Saturday"
    assert window.model.events() == []
    window.close()


def test_config_window_new_day_duplicate(qapp, engine, monkeypatch, tmp_path):
    from stagetimer.core import day_store
    from stagetimer.ui.config_window import QInputDialog

    days_dir = tmp_path / "days"
    active_day_path = tmp_path / "active_day.json"
    timetable = Timetable(events=[Event(name="Keynote", start_time=None, duration_seconds=600)])
    day_a = day_store.create_day(days_dir, "Friday", timetable)

    window = ConfigWindow(
        engine, timetable, lambda p: None, day_a, lambda d: None, days_dir=days_dir, active_day_path=active_day_path
    )

    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Saturday", True))

    class FakeMsg:
        def __init__(self, *a, **k):
            pass

        def setWindowTitle(self, *a):
            pass

        def setText(self, *a):
            pass

        def addButton(self, label, role):
            return label

        def exec(self):
            pass

        def clickedButton(self):
            return "Duplicate"

    monkeypatch.setattr("stagetimer.ui.config_window.QMessageBox", FakeMsg)
    window._new_day()

    assert window._active_day_name == "Saturday"
    assert [e.name for e in window.model.events()] == ["Keynote"]

    # Editing the original day afterward must not affect the duplicate already
    # sitting in this window's model/engine — they were copied, not shared.
    day_store.save_day(
        days_dir, day_a, "Friday", Timetable(events=[Event(name="Changed", start_time=None, duration_seconds=600)])
    )
    assert [e.name for e in day_store.load_day(days_dir, day_a).events] == ["Changed"]
    assert [e.name for e in window.model.events()] == ["Keynote"]
    window.close()


def test_config_window_delete_day_falls_back_to_another_day(qapp, engine, monkeypatch, tmp_path):
    from stagetimer.core import day_store
    from stagetimer.ui.config_window import QMessageBox

    days_dir = tmp_path / "days"
    active_day_path = tmp_path / "active_day.json"
    timetable_a = Timetable(events=[Event(name="Keynote", start_time=None, duration_seconds=600)])
    timetable_b = Timetable(events=[Event(name="Panel", start_time=None, duration_seconds=600)])
    day_a = day_store.create_day(days_dir, "Friday", timetable_a)
    day_b = day_store.create_day(days_dir, "Saturday", timetable_b)

    window = ConfigWindow(
        engine, timetable_a, lambda p: None, day_a, lambda d: None, days_dir=days_dir, active_day_path=active_day_path
    )

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    window._delete_current_day()

    assert window._active_day_id == day_b
    assert [e.name for e in window.model.events()] == ["Panel"]
    assert [d.id for d in day_store.list_days(days_dir)] == [day_b]
    window.close()


def test_config_window_delete_last_day_leaves_empty_state(qapp, engine, monkeypatch, tmp_path):
    from stagetimer.core import day_store
    from stagetimer.ui.config_window import QMessageBox

    days_dir = tmp_path / "days"
    active_day_path = tmp_path / "active_day.json"
    timetable = Timetable(events=[Event(name="Keynote", start_time=None, duration_seconds=600)])
    day_a = day_store.create_day(days_dir, "Friday", timetable)

    window = ConfigWindow(
        engine, timetable, lambda p: None, day_a, lambda d: None, days_dir=days_dir, active_day_path=active_day_path
    )

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    window._delete_current_day()

    assert window._active_day_id is None
    assert window.model.events() == []
    assert day_store.get_active_day_id(active_day_path) is None
    assert day_store.list_days(days_dir) == []
    assert window.windowTitle().endswith("No day loaded")
    window.close()


def test_config_window_persist_and_apply_saves_through_day_store(qapp, engine, tmp_path):
    from stagetimer.core import day_store

    days_dir = tmp_path / "days"
    active_day_path = tmp_path / "active_day.json"
    timetable = Timetable(events=[Event(name="Keynote", start_time=None, duration_seconds=600)])
    day_a = day_store.create_day(days_dir, "Friday", timetable)

    window = ConfigWindow(
        engine, timetable, lambda p: None, day_a, lambda d: None, days_dir=days_dir, active_day_path=active_day_path
    )
    window.model.add_event(Event(name="Panel", start_time=None, duration_seconds=600))
    window._persist_and_apply()

    reloaded = day_store.load_day(days_dir, day_a)
    assert [e.name for e in reloaded.events] == ["Keynote", "Panel"]
    window.close()
```

Note on the `FakeMsg` fake used in the two `_new_day` tests: driving a real modal `QMessageBox.exec()` in an offscreen headless test would block, so these tests replace the `QMessageBox` name inside `stagetimer.ui.config_window` entirely via monkeypatch, rather than clicking a real dialog. Read `src/stagetimer/ui/config_window.py`'s actual current imports before writing `_new_day` in Step 6 below — if the real implementation ends up using `QMessageBox` differently than this fake assumes (e.g. different method names), adjust the fake to match the real implementation rather than forcing the implementation to match this exact fake shape; the important behavior to preserve is "Empty" produces an empty timetable and "Duplicate" produces a copy of the current one.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_ui_smoke.py -k "day_menu or switch_day or switch_to_same or switch_while_running or new_day or delete_day or delete_last_day or persist_and_apply_saves" -v`
Expected: FAIL — `TypeError: ConfigWindow() takes from 4 to 5 positional arguments but 6 were given` (constructor doesn't accept the new parameters yet).

- [ ] **Step 3: Update imports**

In `src/stagetimer/ui/config_window.py`, change:

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

from stagetimer import config
from stagetimer.core import persistence
from stagetimer.core.models import Event, Timetable
from stagetimer.core.state_machine import Mode, TimerEngine
from stagetimer.ui.event_table_model import EventTableModel
```

to:

```python
from __future__ import annotations

import dataclasses
import shutil
import uuid
from datetime import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableView,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from stagetimer import config
from stagetimer.core import day_store, persistence
from stagetimer.core.models import Event, Timetable
from stagetimer.core.state_machine import Mode, TimerEngine
from stagetimer.ui.event_table_model import EventTableModel
```

(`persistence` stays imported — it's still referenced by other code in this module; if it turns out unused after this task's changes, remove it, but check first.)

- [ ] **Step 4: Update the `ConfigWindow` constructor**

Change:

```python
    def __init__(
        self,
        engine: TimerEngine,
        timetable: Timetable,
        on_logo_changed: Callable[[str], None],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("StageTimer — Configuration")
        self.resize(720, 560)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        self.engine = engine
        self._logo_path = timetable.logo_path
        self._on_logo_changed = on_logo_changed
        self._clipboard_event: Event | None = None
        self.model = EventTableModel(timetable.sorted_events())
```

to:

```python
    def __init__(
        self,
        engine: TimerEngine,
        timetable: Timetable,
        on_logo_changed: Callable[[str | None], None],
        active_day_id: str | None = None,
        on_day_changed: Callable[[str | None], None] = lambda day_id: None,
        days_dir: Path = config.DAYS_DIR,
        active_day_path: Path = config.ACTIVE_DAY_PATH,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.resize(720, 560)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        self.engine = engine
        self._logo_path = timetable.logo_path
        self._on_logo_changed = on_logo_changed
        self._active_day_id = active_day_id
        self._active_day_name = "No day loaded"
        self._on_day_changed = on_day_changed
        self._days_dir = days_dir
        self._active_day_path = active_day_path
        self._clipboard_event: Event | None = None
        self.model = EventTableModel(timetable.sorted_events())
```

(The `setWindowTitle("StageTimer — Configuration")` line is removed here because `_refresh_day_menu`, called at the end of `__init__` in Step 6 below, now sets the title including the active day's name.)

- [ ] **Step 5: Add the Day menu bar**

Read the actual current `__init__` to find this existing code (it appears near the end, right before the `QShortcut` lines):

```python
        root = QVBoxLayout(self)
        root.addWidget(timetable_box, 1)
        root.addWidget(logo_box)
        root.addWidget(controls_box)

        QShortcut(QKeySequence("Escape"), self, activated=self.close)
```

Change it to:

```python
        root = QVBoxLayout(self)
        root.addWidget(timetable_box, 1)
        root.addWidget(logo_box)
        root.addWidget(controls_box)

        menu_bar = QMenuBar(self)
        self._day_menu = menu_bar.addMenu("Day")
        self._day_menu.aboutToShow.connect(self._refresh_day_menu)
        root.setMenuBar(menu_bar)

        QShortcut(QKeySequence("Escape"), self, activated=self.close)
```

- [ ] **Step 6: Call `_refresh_day_menu()` once at the end of `__init__`**

Find the last lines of `__init__`:

```python
        self._start_refresh_timer = QTimer(self)
        self._start_refresh_timer.setInterval(250)
        self._start_refresh_timer.timeout.connect(self._refresh_start_button)
        self._start_refresh_timer.start()
        self._refresh_start_button()
```

Change to:

```python
        self._start_refresh_timer = QTimer(self)
        self._start_refresh_timer.setInterval(250)
        self._start_refresh_timer.timeout.connect(self._refresh_start_button)
        self._start_refresh_timer.start()
        self._refresh_start_button()
        self._refresh_day_menu()
```

- [ ] **Step 7: Add the Day menu methods**

Add these new methods after `_refresh_start_button` (which is defined right after `_selected_row`):

```python
    def _refresh_day_menu(self) -> None:
        self._day_menu.clear()
        days = day_store.list_days(self._days_dir)
        self._active_day_name = next((d.name for d in days if d.id == self._active_day_id), "No day loaded")
        self.setWindowTitle(f"StageTimer — Configuration — {self._active_day_name}")
        for day in days:
            action = QAction(day.name, self)
            action.setCheckable(True)
            action.setChecked(day.id == self._active_day_id)
            action.triggered.connect(lambda checked=False, day_id=day.id: self._switch_to_day(day_id))
            self._day_menu.addAction(action)
        self._day_menu.addSeparator()
        new_action = QAction("New Day...", self)
        new_action.triggered.connect(self._new_day)
        self._day_menu.addAction(new_action)
        rename_action = QAction("Rename Current Day...", self)
        rename_action.triggered.connect(self._rename_current_day)
        rename_action.setEnabled(self._active_day_id is not None)
        self._day_menu.addAction(rename_action)
        delete_action = QAction("Delete Current Day...", self)
        delete_action.triggered.connect(self._delete_current_day)
        delete_action.setEnabled(self._active_day_id is not None)
        self._day_menu.addAction(delete_action)

    def _switch_to_day(self, day_id: str) -> None:
        if day_id == self._active_day_id:
            return
        if self.engine.get_display_state().mode in (Mode.RUNNING, Mode.PAUSED):
            day_name = next((d.name for d in day_store.list_days(self._days_dir) if d.id == day_id), "")
            reply = QMessageBox.question(
                self,
                "Switch day?",
                f"Switch to '{day_name}'? This will stop the current timer.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        timetable = day_store.load_day(self._days_dir, day_id)
        self._active_day_id = day_id
        self._logo_path = timetable.logo_path
        self.model.set_events(timetable.sorted_events())
        self.engine.set_timetable(timetable)
        self.logo_label.setText(self._logo_path or "No logo selected")
        self._on_logo_changed(self._logo_path)
        day_store.set_active_day_id(self._active_day_path, day_id)
        self._on_day_changed(day_id)
        self._refresh_day_menu()

    def _new_day(self) -> None:
        name, ok = QInputDialog.getText(self, "New Day", "Day name:")
        name = name.strip()
        if not ok or not name:
            return

        msg = QMessageBox(self)
        msg.setWindowTitle("New Day")
        msg.setText(f"Start '{name}' empty, or duplicate events from '{self._active_day_name}'?")
        empty_btn = msg.addButton("Empty", QMessageBox.ButtonRole.NoRole)
        msg.addButton("Duplicate", QMessageBox.ButtonRole.YesRole)
        msg.exec()

        if msg.clickedButton() is empty_btn:
            new_timetable = Timetable()
        else:
            new_timetable = Timetable(events=list(self.model.events()), logo_path=self._logo_path)

        new_id = day_store.create_day(self._days_dir, name, new_timetable)
        self._switch_to_day(new_id)

    def _rename_current_day(self) -> None:
        if self._active_day_id is None:
            return
        name, ok = QInputDialog.getText(self, "Rename Day", "Day name:", text=self._active_day_name)
        name = name.strip()
        if not ok or not name:
            return
        day_store.rename_day(self._days_dir, self._active_day_id, name)
        self._refresh_day_menu()

    def _delete_current_day(self) -> None:
        if self._active_day_id is None:
            return
        reply = QMessageBox.question(
            self,
            "Delete Day",
            f"Delete '{self._active_day_name}'? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        day_store.delete_day(self._days_dir, self._active_day_id)
        remaining = day_store.list_days(self._days_dir)
        if remaining:
            fallback = max(remaining, key=lambda d: d.modified_at)
            self._switch_to_day(fallback.id)
        else:
            self._active_day_id = None
            self._logo_path = None
            self.model.set_events([])
            self.engine.set_timetable(Timetable())
            self.logo_label.setText("No logo selected")
            self._on_logo_changed(None)
            day_store.clear_active_day(self._active_day_path)
            self._on_day_changed(None)
            self._refresh_day_menu()
```

Note: `_switch_to_day`'s no-op guard (`if day_id == self._active_day_id: return`) means the fallback branch in `_delete_current_day` — which calls `_switch_to_day(fallback.id)` right after the *old* day was already deleted — always proceeds, since `fallback.id` can never equal the just-deleted `self._active_day_id` (that file no longer exists in `remaining`).

- [ ] **Step 8: Update `_persist_and_apply` to save through `day_store`**

Change:

```python
    def _persist_and_apply(self) -> None:
        timetable = Timetable(events=self.model.events(), logo_path=self._logo_path)
        persistence.save(config.TIMETABLE_PATH, timetable)
        self.engine.set_timetable(timetable)
```

to:

```python
    def _persist_and_apply(self) -> None:
        if self._active_day_id is None:
            return
        timetable = Timetable(events=self.model.events(), logo_path=self._logo_path)
        day_store.save_day(self._days_dir, self._active_day_id, self._active_day_name, timetable)
        self.engine.set_timetable(timetable)
```

(The `if self._active_day_id is None: return` guard covers the edge case reached only via "delete every day, then try to Add/Edit/Delete/Copy/Paste an event with no day loaded" — the table model still updates visually in that state, since `_add_event`/etc. call `self.model.add_event(...)` before calling `_persist_and_apply()`, but nothing is saved to disk until a new day exists to save it into. This is an intentional, narrow consequence of allowing zero days to exist at all — not a bug to fix in this task.)

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/test_ui_smoke.py -q`
Expected: `31 passed` (22 existing + 9 new).

- [ ] **Step 10: Run the full suite**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest -q`
Expected: `136 passed` (127 after Task 1 + 9 new).

- [ ] **Step 11: Commit**

```bash
git add src/stagetimer/ui/config_window.py tests/test_ui_smoke.py
git commit -m "feat: add Day menu (switch/new/rename/delete) to the config window"
```

---

### Task 3: Wire `day_store` into `app.py` startup

**Files:**
- Modify: `src/stagetimer/app.py`

No new automated test for this task — `app.py::run()` opens a real fullscreen/windowed Qt application event loop and isn't unit-tested anywhere in this codebase today (there's no existing `test_app.py`); this task's correctness is covered by Task 4's full-suite regression run (nothing here changes behavior the existing suite exercises) plus Task 4's manual smoke test, which specifically exercises day switching end-to-end in the real running app.

- [ ] **Step 1: Update `app.py`**

Change:

```python
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from stagetimer import config
from stagetimer.core import persistence
from stagetimer.core.state_machine import TimerEngine
from stagetimer.ui.config_window import ConfigWindow
from stagetimer.ui.main_display import MainDisplay
from stagetimer.ui.shortcuts import register_main_display_shortcuts
```

to:

```python
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from stagetimer import config
from stagetimer.core import day_store
from stagetimer.core.state_machine import TimerEngine
from stagetimer.ui.config_window import ConfigWindow
from stagetimer.ui.main_display import MainDisplay
from stagetimer.ui.shortcuts import register_main_display_shortcuts
```

(`persistence` is no longer used directly in `app.py` — `day_store.ensure_startup_day` calls into it internally instead.)

Change:

```python
def run(kiosk: bool = True) -> int:
    app = QApplication(sys.argv)
    _load_bundled_fonts()

    timetable = persistence.load(config.TIMETABLE_PATH)
    engine = TimerEngine(timetable)

    main_display = MainDisplay(engine, kiosk=kiosk)
    main_display.set_logo(timetable.logo_path)

    state = {"config_window": None}

    def on_logo_changed(path: str) -> None:
        main_display.set_logo(path)

    def toggle_config_window() -> None:
        window = state["config_window"]
        if window is not None:
            try:
                visible = window.isVisible()
            except RuntimeError:
                # The underlying Qt widget was already destroyed (WA_DeleteOnClose
                # deletes it after close()); treat this the same as "not visible".
                window = None
                state["config_window"] = None
                visible = False
            if visible:
                window.close()
                return
        window = ConfigWindow(engine, engine.timetable, on_logo_changed)
        state["config_window"] = window
        window.show()
        window.raise_()
        window.activateWindow()

    register_main_display_shortcuts(main_display, engine, toggle_config_window)

    main_display.show_kiosk()
    return app.exec()
```

to:

```python
def run(kiosk: bool = True) -> int:
    app = QApplication(sys.argv)
    _load_bundled_fonts()

    active_day_id = day_store.ensure_startup_day(config.DAYS_DIR, config.ACTIVE_DAY_PATH, config.TIMETABLE_PATH)
    timetable = day_store.load_day(config.DAYS_DIR, active_day_id)
    engine = TimerEngine(timetable)

    main_display = MainDisplay(engine, kiosk=kiosk)
    main_display.set_logo(timetable.logo_path)

    state = {"config_window": None, "active_day_id": active_day_id}

    def on_logo_changed(path: str | None) -> None:
        main_display.set_logo(path)

    def on_day_changed(day_id: str | None) -> None:
        state["active_day_id"] = day_id

    def toggle_config_window() -> None:
        window = state["config_window"]
        if window is not None:
            try:
                visible = window.isVisible()
            except RuntimeError:
                # The underlying Qt widget was already destroyed (WA_DeleteOnClose
                # deletes it after close()); treat this the same as "not visible".
                window = None
                state["config_window"] = None
                visible = False
            if visible:
                window.close()
                return
        window = ConfigWindow(engine, engine.timetable, on_logo_changed, state["active_day_id"], on_day_changed)
        state["config_window"] = window
        window.show()
        window.raise_()
        window.activateWindow()

    register_main_display_shortcuts(main_display, engine, toggle_config_window)

    main_display.show_kiosk()
    return app.exec()
```

- [ ] **Step 2: Run the full suite to confirm no regressions**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest -q`
Expected: `136 passed` (unchanged from Task 2 — this task has no new tests, only wiring).

- [ ] **Step 3: Commit**

```bash
git add src/stagetimer/app.py
git commit -m "feat: boot from the active day via day_store instead of the single legacy timetable"
```

---

### Task 4: Full-suite verification and manual smoke test

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `cd C:\Claude_Projekte\StageTimer && QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python -m pytest tests/ -q`
Expected: `136 passed` (108 baseline before this plan + 19 day_store + 9 config_window).

- [ ] **Step 2: Manual smoke test in windowed dev mode**

Before running, note that this is the **first run under the new day system** — it will auto-migrate whatever the current `~/.local/share/stagetimer/timetable.json` contains into a day named "Day 1". Back up that file first if it holds anything worth keeping (`cp ~/.local/share/stagetimer/timetable.json ~/.local/share/stagetimer/timetable.json.bak-manual` or equivalent), since testing this migration path (rather than starting from an already-migrated `days/` directory) is itself part of what needs verifying here.

Run: `cd C:\Claude_Projekte\StageTimer && ./.venv/Scripts/python -m stagetimer --windowed`

Verify manually:
- On first launch, the config window's title bar reads "StageTimer — Configuration — Day 1", and the Day menu shows exactly one entry ("Day 1", checked) plus New/Rename/Delete.
- "New Day..." → enter a name, choose "Empty" → title bar and Day menu update to the new day; the table is empty.
- Add a couple of events to this new day, close and reopen the config window (Ctrl+E twice) — the new day and its events are still there (proves `_persist_and_apply` is saving through `day_store` correctly, and that reopening `ConfigWindow` picks up the currently-active day rather than resetting to Day 1).
- "New Day..." again → enter a different name, choose "Duplicate" → the new day starts with a copy of the previous day's events; editing an event in this new day does not change the day it was duplicated from.
- Switch back to "Day 1" via the Day menu while nothing is running — switches immediately, no confirmation.
- Press Start (or the Start button) to enter `RUNNING` mode, then try switching days via the Day menu — a confirmation dialog appears; Cancel/No keeps you on the running day, Yes switches and the main display's countdown stops/resets to the new day's `AWAITING_START`.
- Rename the active day — title bar and Day menu update immediately.
- Delete the active day while at least one other day exists — falls back to another day automatically (no crash, no empty state).
- Delete every remaining day, one at a time, down to zero — the last deletion leaves the config window showing "No day loaded", an empty table, and Rename/Delete disabled in the Day menu; "New Day..." still works from this state.
- Close the app entirely and relaunch `python -m stagetimer --windowed` — it reopens on whichever day was active when it closed (the restart-restore behavior), not always "Day 1".
- Close the app afterward.

- [ ] **Step 3: Deploy, if currently on the Pi's network**

Run: `cd C:\Claude_Projekte\StageTimer && .\deploy\sync.ps1 -PiHost admin@raspberrypi.local`

If not currently reachable, skip this step — everything up to here is fully verified locally and ready to push whenever the Pi is back on the network. Verify over SSH if deployed:

Run: `ssh admin@raspberrypi.local "ps aux | grep -v grep | grep stagetimer"`
Expected: a running `python -m stagetimer` process with a recent start time.
