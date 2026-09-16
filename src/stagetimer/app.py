from __future__ import annotations

import sys

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from stagetimer import config
from stagetimer.core import day_store
from stagetimer.core.state_machine import TimerEngine
from stagetimer.ui.config_window import ConfigWindow
from stagetimer.ui.main_display import MainDisplay
from stagetimer.ui.shortcuts import register_main_display_shortcuts


def _load_bundled_fonts() -> None:
    """Register the bundled JetBrains Mono font files with Qt so the app
    doesn't depend on any particular font being installed on the host OS —
    the clock relies on this for predictable digit glyphs (see
    config.FONT_FAMILY). Must run after the QApplication is constructed."""
    for font_path in config.FONT_PATHS:
        if font_path.exists():
            QFontDatabase.addApplicationFont(str(font_path))


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
