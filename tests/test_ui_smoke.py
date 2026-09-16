import os
from datetime import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from stagetimer.core.models import Event, Timetable
from stagetimer.core.state_machine import TimerEngine
from stagetimer.ui.config_window import ConfigWindow
from stagetimer.ui.main_display import MainDisplay
from stagetimer.ui.shortcuts import register_main_display_shortcuts


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def engine():
    return TimerEngine(
        Timetable(
            events=[
                Event(name="Keynote", start_time=time(0, 0), duration_seconds=1800),
                Event(name="Panel", start_time=time(0, 30), duration_seconds=1200),
            ]
        )
    )


def test_main_display_renders_current_event(qapp, engine):
    display = MainDisplay(engine, kiosk=False)
    display._on_tick()
    assert display.current_box._name.text() != ""
    display.close()


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


def test_ctrl_e_shortcut_invokes_toggle_callback(qapp, engine):
    display = MainDisplay(engine, kiosk=False)
    display.show()
    display.setFocus()
    QTest.qWaitForWindowExposed(display)
    calls = {"toggled": 0}
    register_main_display_shortcuts(display, engine, lambda: calls.update(toggled=calls["toggled"] + 1))

    QTest.keyClick(display, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
    assert calls["toggled"] == 1
    display.close()


def test_space_keypress_advances_to_next_event(qapp, engine):
    display = MainDisplay(engine, kiosk=False)
    display.show()
    display.setFocus()
    QTest.qWaitForWindowExposed(display)
    register_main_display_shortcuts(display, engine, lambda: None)

    engine.start(now=__import__("datetime").datetime(2026, 8, 11, 0, 0))
    engine.tick(__import__("datetime").datetime(2026, 8, 11, 0, 10))
    assert engine.get_display_state().current_name == "Keynote"

    QTest.keyClick(display, Qt.Key.Key_Space)
    assert engine.get_display_state().current_name == "Panel"
    display.close()


def test_event_table_model_blank_start_time_for_untimed_event(qapp):
    from stagetimer.ui.event_table_model import EventTableModel

    model = EventTableModel([Event(name="Freeform", start_time=None, duration_seconds=300)])
    index = model.index(0, 1)
    assert model.data(index, Qt.ItemDataRole.DisplayRole) == ""


def test_config_window_opens_and_lists_events(qapp, engine):
    timetable = Timetable(
        events=[Event(name="Keynote", start_time=time(9, 0), duration_seconds=1800)]
    )
    engine.set_timetable(timetable)
    window = ConfigWindow(engine, timetable, on_logo_changed=lambda p: None)
    assert window.model.rowCount() == 1
    assert window.model.event_at(0).name == "Keynote"
    window.close()


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


def test_event_edit_dialog_prefills_from_existing_event(qapp):
    from stagetimer.ui.config_window import EventEditDialog

    timed_event = Event(name="Keynote", start_time=time(14, 30), duration_seconds=600)
    timed_dialog = EventEditDialog(event=timed_event)
    assert timed_dialog.has_start_time.isChecked() is True
    assert timed_dialog.start_edit.isEnabled() is True
    assert timed_dialog.start_edit.time().hour() == 14
    assert timed_dialog.start_edit.time().minute() == 30

    untimed_event = Event(name="Freeform", start_time=None, duration_seconds=300)
    untimed_dialog = EventEditDialog(event=untimed_event)
    assert untimed_dialog.has_start_time.isChecked() is False
    assert untimed_dialog.start_edit.isEnabled() is False


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


def test_config_window_add_event_persists_to_engine(qapp, engine, tmp_path):
    # Note: this test predates the multi-day rework and originally asserted
    # persistence to the legacy single-file config.TIMETABLE_PATH via
    # persistence.save(). _persist_and_apply now saves through day_store
    # instead (see the new Day-menu tests below), so this test is updated to
    # construct the window against an isolated tmp_path day rather than
    # continuing to assert on the now-unused legacy path.
    from stagetimer.core import day_store

    days_dir = tmp_path / "days"
    active_day_path = tmp_path / "active_day.json"
    timetable = Timetable(events=[])
    day_a = day_store.create_day(days_dir, "Friday", timetable)
    engine.set_timetable(timetable)
    window = ConfigWindow(
        engine, timetable, lambda p: None, day_a, lambda d: None, days_dir=days_dir, active_day_path=active_day_path
    )

    new_event = Event(name="Added", start_time=time(10, 0), duration_seconds=600)
    window.model.add_event(new_event)
    window._persist_and_apply()

    assert any(e.name == "Added" for e in engine.timetable.events)
    assert any(e.name == "Added" for e in day_store.load_day(days_dir, day_a).events)
    window.close()


def test_main_display_shows_realtime_clock_and_mini_timetable(qapp, engine):
    display = MainDisplay(engine, kiosk=False)
    display._on_tick()
    assert display.realtime_clock.text() != ""
    assert ":" in display.realtime_clock.text()
    assert display.mini_timetable.count() == len(engine.timetable.events)
    display.close()


def test_main_display_shows_awaiting_start_text(qapp):
    from stagetimer.ui.main_display import AWAITING_START_TEXT

    timetable = Timetable(events=[Event(name="Freeform", start_time=None, duration_seconds=300)])
    engine = TimerEngine(timetable)
    display = MainDisplay(engine, kiosk=False)
    engine.tick(__import__("datetime").datetime(2026, 8, 11, 9, 0))
    display._on_tick()
    assert display.current_box._name.text() == AWAITING_START_TEXT
    display.close()


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


def test_event_edit_dialog_description_with_special_characters_is_not_html_mangled(qapp):
    from stagetimer.ui.config_window import EventEditDialog

    event = Event(name="Keynote", start_time=time(9, 0), duration_seconds=600, description="Q&A <live demo> session")
    dialog = EventEditDialog(event=event)
    assert dialog.description_edit.toPlainText() == "Q&A <live demo> session"


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
    timetable = Timetable(
        events=[
            Event(name="Changeover", start_time=None, duration_seconds=300),
            Event(name="Closing", start_time=None, duration_seconds=600),
        ]
    )
    engine.set_timetable(timetable)
    window = ConfigWindow(engine, timetable, on_logo_changed=lambda p: None)

    window.table.selectRow(0)
    window._copy_selected()
    window._paste_event()
    window._paste_event()

    names = [e.name for e in window.model.events()]
    assert names == ["Changeover", "Changeover", "Changeover", "Closing"]
    window.close()


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
    from PySide6.QtWidgets import QMessageBox as RealQMessageBox

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
        ButtonRole = RealQMessageBox.ButtonRole

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
    from PySide6.QtWidgets import QMessageBox as RealQMessageBox

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
        ButtonRole = RealQMessageBox.ButtonRole

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


def test_config_window_rename_current_day(qapp, engine, monkeypatch, tmp_path):
    from stagetimer.core import day_store
    from stagetimer.ui.config_window import QInputDialog

    days_dir = tmp_path / "days"
    active_day_path = tmp_path / "active_day.json"
    timetable = Timetable(events=[Event(name="Keynote", start_time=None, duration_seconds=600)])
    day_a = day_store.create_day(days_dir, "Friday", timetable)

    window = ConfigWindow(
        engine, timetable, lambda p: None, day_a, lambda d: None, days_dir=days_dir, active_day_path=active_day_path
    )

    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Opening Night", True))
    window._rename_current_day()

    assert window._active_day_name == "Opening Night"
    assert window.windowTitle().endswith("Opening Night")
    assert day_store.list_days(days_dir)[0].name == "Opening Night"
    window.close()


def test_config_window_rename_blank_name_cancels(qapp, engine, monkeypatch, tmp_path):
    from stagetimer.core import day_store
    from stagetimer.ui.config_window import QInputDialog

    days_dir = tmp_path / "days"
    active_day_path = tmp_path / "active_day.json"
    timetable = Timetable(events=[Event(name="Keynote", start_time=None, duration_seconds=600)])
    day_a = day_store.create_day(days_dir, "Friday", timetable)

    window = ConfigWindow(
        engine, timetable, lambda p: None, day_a, lambda d: None, days_dir=days_dir, active_day_path=active_day_path
    )

    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("   ", True))
    window._rename_current_day()

    assert window._active_day_name == "Friday"
    assert day_store.list_days(days_dir)[0].name == "Friday"
    window.close()


def test_config_window_rename_with_no_active_day_is_noop(qapp, engine, monkeypatch, tmp_path):
    from stagetimer.core import day_store
    from stagetimer.ui.config_window import QInputDialog, QMessageBox

    days_dir = tmp_path / "days"
    active_day_path = tmp_path / "active_day.json"
    timetable = Timetable(events=[Event(name="Keynote", start_time=None, duration_seconds=600)])
    day_a = day_store.create_day(days_dir, "Friday", timetable)

    window = ConfigWindow(
        engine, timetable, lambda p: None, day_a, lambda d: None, days_dir=days_dir, active_day_path=active_day_path
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    window._delete_current_day()  # brings the window to "no active day"
    assert window._active_day_id is None

    getText_calls = []
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: (getText_calls.append(1), ("x", True))[1])
    window._rename_current_day()

    assert getText_calls == []  # never even prompted — the no-op guard returned first
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
    # isVisible() reflects the whole ancestor chain, not just this widget's
    # own setVisible() call — without showing the top-level display first,
    # schedule_delay.isVisible() reads False regardless of wiring
    # correctness (see other tests in this file that call display.show()
    # for the same reason, e.g. test_pause_shortcut_toggles_engine).
    display.show()
    display._on_tick()
    assert display.schedule_delay.isVisible() is True
    assert "01:30" in display.schedule_delay.text()
    display.close()


def test_main_display_hides_schedule_delay_when_empty(qapp):
    engine = TimerEngine(Timetable(events=[]))
    display = MainDisplay(engine, kiosk=False)
    # isVisible() reflects the whole ancestor chain, not just this widget's
    # own setVisible() call — without showing the top-level display first,
    # schedule_delay.isVisible() reads False regardless of wiring
    # correctness (see other tests in this file that call display.show()
    # for the same reason, e.g. test_pause_shortcut_toggles_engine).
    display.show()
    display._on_tick()
    assert display.schedule_delay.isVisible() is False
    display.close()
