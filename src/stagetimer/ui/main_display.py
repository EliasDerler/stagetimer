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
    ScheduleDelayLabel,
    format_overtime,
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
        self.schedule_delay = ScheduleDelayLabel()
        self.mini_timetable = MiniTimetable()
        self.mini_timetable.setMinimumWidth(320)
        self.mini_timetable.setFixedHeight(140)

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
        bottom_row.addWidget(self.next_bar, 1, Qt.AlignmentFlag.AlignVCenter)
        bottom_row.addWidget(self.mini_timetable, 0)

        root = QVBoxLayout(self)
        root.addLayout(top_row)
        root.addWidget(self.clock_area, 1)
        root.addWidget(self.schedule_delay)
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
            self.clock.set_time_and_state(format_overtime(state.remaining_seconds), state.color_state)
            self.next_bar.set_next(state.next_name, state.next_duration_seconds, state.next_description)
        elif state.mode == Mode.AFTER_LAST:
            self.current_box.set_name(DAY_COMPLETE_TEXT)
            self.current_box.set_description(None)
            self.clock.set_time_and_state(BLANK_CLOCK_TEXT, ColorState.NORMAL)
            self.next_bar.set_next(None, None)
        else:  # RUNNING or PAUSED
            self.current_box.set_name(state.current_name)
            self.current_box.set_description(state.current_description)
            self.clock.set_time_and_state(format_overtime(state.remaining_seconds), state.color_state)
            self.next_bar.set_next(state.next_name, state.next_duration_seconds, state.next_description)

        self.schedule_delay.set_delay_seconds(state.schedule_delay_seconds)
        self.realtime_clock.setText(datetime.now().strftime("%H:%M:%S"))
        self.mini_timetable.set_rows(self.engine.get_schedule_overview())
