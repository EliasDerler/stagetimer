from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from stagetimer import config
from stagetimer.core.state_machine import ColorState
from stagetimer.ui import styles


def format_remaining(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class CurrentBox(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("currentBox")
        self.setStyleSheet(styles.CURRENT_BOX_QSS)

        layout = QVBoxLayout(self)
        self._caption = QLabel("Current")
        self._caption.setObjectName("currentCaption")
        self._name = QLabel("")
        self._name.setObjectName("currentName")
        self._name.setWordWrap(True)
        layout.addWidget(self._caption)
        layout.addWidget(self._name)

    def set_name(self, name: str | None) -> None:
        self._name.setText(name or "")


class LogoBox(QLabel):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self._pixmap: QPixmap | None = None

    def set_logo_path(self, path: str | None) -> None:
        if not path:
            self._pixmap = None
            self.clear()
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self._pixmap = None
            self.clear()
            return
        self._pixmap = pixmap
        self._rescale()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self) -> None:
        if self._pixmap is None:
            return
        scaled = self._pixmap.scaledToHeight(
            min(120, self.height() or 120), Qt.TransformationMode.SmoothTransformation
        )
        self.setPixmap(scaled)


class ClockLabel(QLabel):
    """Big centered countdown clock with color-state + 1-minute flash."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._last_color_state: ColorState | None = None
        self._flash_on = True
        self._flash_timer = QTimer(self)
        self._flash_timer.setInterval(config.FLASH_INTERVAL_MS)
        self._flash_timer.timeout.connect(self._toggle_flash)
        self.setStyleSheet(styles.clock_qss_for_color(config.COLOR_NORMAL))

    def set_time_and_state(self, text: str, color_state: ColorState) -> None:
        self.setText(text)
        if color_state != self._last_color_state:
            self._apply_color_state(color_state)
            self._last_color_state = color_state

    def _apply_color_state(self, color_state: ColorState) -> None:
        if color_state == ColorState.FLASH:
            self._flash_on = True
            self.setStyleSheet(styles.clock_qss_for_color(config.COLOR_DANGER))
            if not self._flash_timer.isActive():
                self._flash_timer.start()
            return

        if self._flash_timer.isActive():
            self._flash_timer.stop()

        color_map = {
            ColorState.NORMAL: config.COLOR_NORMAL,
            ColorState.WARNING_YELLOW: config.COLOR_WARNING,
            ColorState.DANGER_RED: config.COLOR_DANGER,
        }
        self.setStyleSheet(styles.clock_qss_for_color(color_map[color_state]))

    def _toggle_flash(self) -> None:
        self._flash_on = not self._flash_on
        color = config.COLOR_DANGER if self._flash_on else config.COLOR_FLASH_ALT
        self.setStyleSheet(styles.clock_qss_for_color(color))


class NextBar(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

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

        layout.addLayout(left, 1)
        layout.addWidget(self._duration)

    def set_next(self, name: str | None, duration_seconds: int | None) -> None:
        if name is None:
            self.setVisible(False)
            return
        self.setVisible(True)
        self._name.setText(name)
        self._duration.setText(f"-{format_remaining(duration_seconds or 0)}")
