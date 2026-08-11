from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from stagetimer import config
from stagetimer.core.state_machine import ColorState, Mode, TimerEngine
from stagetimer.ui import styles
from stagetimer.ui.display_widgets import ClockLabel, CurrentBox, LogoBox, NextBar, format_remaining

STANDBY_TEXT = "Standing by"
NO_EVENTS_TEXT = "No events scheduled"
DAY_COMPLETE_TEXT = "Day complete"
EMPTY_CLOCK_TEXT = "--:--"


class MainDisplay(QWidget):
    """Fullscreen audience-facing timer display."""

    def __init__(self, engine: TimerEngine, kiosk: bool = True, parent: QWidget | None = None):
        super().__init__(parent)
        self.engine = engine
        self._kiosk = kiosk

        self.setStyleSheet(styles.MAIN_WINDOW_QSS)
        self.setWindowTitle("StageTimer")

        self.current_box = CurrentBox()
        self.logo_box = LogoBox()
        self.clock = ClockLabel()
        self.next_bar = NextBar()

        top_row = QHBoxLayout()
        top_row.addWidget(self.current_box, 1)
        top_row.addWidget(self.logo_box, 0)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet(styles.DIVIDER_QSS)

        root = QVBoxLayout(self)
        root.addLayout(top_row)
        root.addWidget(self.clock, 1)
        root.addWidget(divider)
        root.addWidget(self.next_bar)

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
            self.clock.set_time_and_state(EMPTY_CLOCK_TEXT, ColorState.NORMAL)
            self.next_bar.set_next(None, None)
        elif state.mode == Mode.BEFORE_FIRST:
            self.current_box.set_name(STANDBY_TEXT)
            self.clock.set_time_and_state(format_remaining(state.remaining_seconds), ColorState.NORMAL)
            self.next_bar.set_next(state.next_name, state.next_duration_seconds)
        elif state.mode == Mode.AFTER_LAST:
            self.current_box.set_name(DAY_COMPLETE_TEXT)
            self.clock.set_time_and_state(EMPTY_CLOCK_TEXT, ColorState.NORMAL)
            self.next_bar.set_next(None, None)
        else:  # RUNNING or PAUSED
            self.current_box.set_name(state.current_name)
            self.clock.set_time_and_state(format_remaining(state.remaining_seconds), state.color_state)
            self.next_bar.set_next(state.next_name, state.next_duration_seconds)
