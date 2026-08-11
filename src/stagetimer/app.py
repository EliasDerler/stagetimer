from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from stagetimer import config
from stagetimer.core import persistence
from stagetimer.core.state_machine import TimerEngine
from stagetimer.ui.config_window import ConfigWindow
from stagetimer.ui.main_display import MainDisplay
from stagetimer.ui.shortcuts import register_main_display_shortcuts


def run(kiosk: bool = True) -> int:
    app = QApplication(sys.argv)

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
