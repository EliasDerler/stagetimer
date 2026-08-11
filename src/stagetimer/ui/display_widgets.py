from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from stagetimer import config
from stagetimer.core.state_machine import ColorState
from stagetimer.ui import screen_metrics, styles


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


class ClockLabel(QWidget):
    """Big centered countdown clock with color-state + 1-minute flash.

    Custom-painted (rather than a styled QLabel) so the digits and colon can
    be drawn with a thin outline — keeps them readable once a background
    watermark sits behind them, and paints nothing of its own outside the
    text itself so that watermark shows through around the digits.
    """

    OUTLINE_WIDTH_RATIO = 0.014  # relative to the rendered font's pixel size

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._text = ""
        self._fill_color = QColor(config.COLOR_NORMAL)
        self._last_color_state: ColorState | None = None
        self._flash_on = True
        self._flash_timer = QTimer(self)
        self._flash_timer.setInterval(config.FLASH_INTERVAL_MS)
        self._flash_timer.timeout.connect(self._toggle_flash)

    def set_time_and_state(self, text: str, color_state: ColorState) -> None:
        changed = text != self._text
        self._text = text
        if color_state != self._last_color_state:
            self._apply_color_state(color_state)
            self._last_color_state = color_state
            changed = True
        if changed:
            self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self.update()

    def _apply_color_state(self, color_state: ColorState) -> None:
        if color_state == ColorState.FLASH:
            self._flash_on = True
            self._fill_color = QColor(config.COLOR_DANGER)
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
        self._fill_color = QColor(color_map[color_state])

    def _toggle_flash(self) -> None:
        self._flash_on = not self._flash_on
        color = config.COLOR_DANGER if self._flash_on else config.COLOR_FLASH_ALT
        self._fill_color = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if not self._text:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        font = QFont("Consolas")
        font.setBold(True)
        font.setPixelSize(max(10, int(self.height() * 0.65)))

        path = QPainterPath()
        path.addText(0, 0, font, self._text)
        rect = path.boundingRect()
        dx = (self.width() - rect.width()) / 2 - rect.left()
        dy = (self.height() - rect.height()) / 2 - rect.top()
        path.translate(dx, dy)

        outline_width = max(1.0, font.pixelSize() * self.OUTLINE_WIDTH_RATIO)
        pen = QPen(QColor(config.COLOR_BACKGROUND))
        pen.setWidthF(outline_width)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(self._fill_color)
        painter.drawPath(path)


class WatermarkLabel(QLabel):
    """Faint background logo, scaled to fill the available width within a
    given side margin (in pixels), aspect-ratio preserved."""

    OPACITY = 0.5

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(self.OPACITY)
        self.setGraphicsEffect(effect)

        self._source_pixmap: QPixmap | None = None
        self._margin_px = 0
        if config.WATERMARK_PATH.exists():
            pixmap = QPixmap(str(config.WATERMARK_PATH))
            if not pixmap.isNull():
                self._source_pixmap = pixmap

    def set_margin_px(self, margin_px: int) -> None:
        if margin_px == self._margin_px:
            return
        self._margin_px = margin_px
        self._rescale()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self) -> None:
        if self._source_pixmap is None:
            return
        available_width = max(1, self.width() - 2 * self._margin_px)
        available_height = max(1, self.height())
        scaled = self._source_pixmap.scaled(
            available_width,
            available_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)


class ClockArea(QWidget):
    """Stacks the watermark behind the clock digits, both filling this
    widget's full area. Exposes `.clock` for callers that only need to drive
    the countdown display, same interface as the old bare ClockLabel."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.watermark = WatermarkLabel(self)
        self.clock = ClockLabel(self)
        self.watermark.lower()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        rect = self.rect()
        self.watermark.setGeometry(rect)
        self.clock.setGeometry(rect)
        self.watermark.set_margin_px(screen_metrics.compute_margin_px(self, config.WATERMARK_SIDE_MARGIN_CM))


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
