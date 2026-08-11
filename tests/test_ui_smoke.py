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


def test_config_window_opens_and_lists_events(qapp, engine):
    timetable = Timetable(
        events=[Event(name="Keynote", start_time=time(9, 0), duration_seconds=1800)]
    )
    engine.set_timetable(timetable)
    window = ConfigWindow(engine, timetable, on_logo_changed=lambda p: None)
    assert window.model.rowCount() == 1
    assert window.model.event_at(0).name == "Keynote"
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
