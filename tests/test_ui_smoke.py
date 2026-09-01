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


def test_pause_shortcut_toggles_engine(qapp, engine):
    display = MainDisplay(engine, kiosk=False)
    display.show()
    display.setFocus()
    QTest.qWaitForWindowExposed(display)
    calls = {"toggled": 0}
    register_main_display_shortcuts(display, engine, lambda: calls.update(toggled=calls["toggled"] + 1))

    engine.tick(__import__("datetime").datetime(2026, 8, 11, 0, 10))
    assert engine.get_display_state().is_paused is False

    QTest.keyClick(display, Qt.Key.Key_Space)
    assert engine.get_display_state().is_paused is True

    QTest.keyClick(display, Qt.Key.Key_Space)
    assert engine.get_display_state().is_paused is False
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


def test_skip_next_shortcut(qapp, engine):
    display = MainDisplay(engine, kiosk=False)
    display.show()
    display.setFocus()
    QTest.qWaitForWindowExposed(display)
    register_main_display_shortcuts(display, engine, lambda: None)

    engine.tick(__import__("datetime").datetime(2026, 8, 11, 0, 10))
    assert engine.get_display_state().current_name == "Keynote"

    QTest.keyClick(display, Qt.Key.Key_Right)
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


def test_config_window_add_event_persists_to_engine(qapp, engine, tmp_path, monkeypatch):
    from stagetimer import config as st_config

    monkeypatch.setattr(st_config, "TIMETABLE_PATH", tmp_path / "timetable.json")
    monkeypatch.setattr(st_config, "DATA_DIR", tmp_path)

    timetable = Timetable(events=[])
    engine.set_timetable(timetable)
    window = ConfigWindow(engine, timetable, on_logo_changed=lambda p: None)

    new_event = Event(name="Added", start_time=time(10, 0), duration_seconds=600)
    window.model.add_event(new_event)
    window._persist_and_apply()

    assert any(e.name == "Added" for e in engine.timetable.events)
    assert (tmp_path / "timetable.json").exists()
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
