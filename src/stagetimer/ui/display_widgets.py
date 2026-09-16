from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from stagetimer import config
from stagetimer.core.state_machine import ColorState, ScheduleRow
from stagetimer.ui import screen_metrics, styles


def format_remaining(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_overtime(seconds: float) -> str:
    """Like `format_remaining`, but for values that can be negative
    (overtime) — rendered with a leading '-' and the magnitude, never
    clamped at zero. Used for the main clock (which can go negative once
    an event overruns) and the pre-start countdown (which can too, per the
    design spec); `format_remaining` stays used everywhere a value is
    always forward-looking and positive (the Next bar, the mini-timetable)."""
    sign = "-" if seconds < 0 else ""
    total = int(round(abs(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{sign}{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{sign}{minutes:02d}:{secs:02d}"


def format_clock_time(seconds: int | None) -> str:
    if seconds is None:
        return "--:--"
    total = seconds % (24 * 3600)
    hours, rem = divmod(total, 3600)
    minutes = rem // 60
    return f"{hours:02d}:{minutes:02d}"


def fit_clock_font_pixel_size(
    text: str,
    family: str,
    bold: bool,
    available_width: int,
    available_height: int,
    height_ratio: float = 0.65,
    min_size: int = 10,
    width_margin: float = 0.92,
) -> int:
    """Pick the pixel size for `text` (rendered in `family`/`bold`) that
    fits within `available_width`, starting from a candidate derived only
    from `available_height` (via `height_ratio`) and shrinking it if the
    candidate turns out too wide.

    ClockLabel originally sized its font from height alone, which is fine
    for "MM:SS" (5 chars) but overflows the widget once the text grows to
    "HH:MM:SS" (8 chars, e.g. once remaining time reaches 60 minutes) — so
    this measures the actual rendered width via QFontMetrics and scales the
    size down (proportionally, then corrected with a short verification
    loop to absorb hinting/kerning non-linearity) until it fits within
    `available_width * width_margin`. Pure function (no QWidget involved)
    so the fitting math is directly unit-testable.
    """
    size = max(min_size, int(available_height * height_ratio))
    if not text:
        return size

    target_width = max(1.0, available_width * width_margin)

    font = QFont(family)
    font.setBold(bold)
    font.setPixelSize(size)
    width = QFontMetrics(font).horizontalAdvance(text)

    if width <= target_width:
        return size

    scaled = max(min_size, int(size * target_width / width))
    font.setPixelSize(scaled)
    width = QFontMetrics(font).horizontalAdvance(text)
    while width > target_width and scaled > min_size:
        scaled -= 1
        font.setPixelSize(scaled)
        width = QFontMetrics(font).horizontalAdvance(text)

    return scaled


class CurrentBox(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("currentBox")
        self.setStyleSheet(styles.CURRENT_BOX_QSS)

        self._caption = QLabel("Current")
        self._caption.setObjectName("currentCaption")

        self._name = QLabel("")
        self._name.setObjectName("currentName")
        self._name.setWordWrap(True)

        self._description = QLabel("")
        self._description.setObjectName("currentDescription")
        # QLabel defaults to Qt::AutoText, which auto-detects HTML-looking
        # content and renders it as rich text. A description like "Q&A
        # session" would then get silently mangled on the live,
        # audience-facing display. Force plain text so the description
        # always renders literally, regardless of content.
        self._description.setTextFormat(Qt.TextFormat.PlainText)
        self._description_full_text = ""
        self._last_description_arg: str | None = None

        name_row = QHBoxLayout()
        name_row.addWidget(self._name, 0)
        name_row.addWidget(self._description, 1)

        layout = QVBoxLayout(self)
        layout.addWidget(self._caption)
        layout.addLayout(name_row)

    def set_name(self, name: str | None) -> None:
        self._name.setText(name or "")

    def set_description(self, description: str | None) -> None:
        # CurrentBox.set_description() is called ~5x/second from the main
        # tick loop (Task 7); skip the redundant strip/replace + elision
        # work when nothing actually changed since the last call, mirroring
        # the guard NextBar.set_next() (and MiniTimetable.set_rows(),
        # WatermarkLabel.set_margin_px()) already use for the same reason.
        if description == self._last_description_arg:
            return
        self._last_description_arg = description
        self._description_full_text = (description or "").strip().replace("\n", " ")
        self._update_description_elision()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._update_description_elision()

    def _update_description_elision(self) -> None:
        if not self._description_full_text:
            self._description.setText("")
            return
        metrics = QFontMetrics(self._description.font())
        available = max(0, self._description.width())
        elided = metrics.elidedText(self._description_full_text, Qt.TextElideMode.ElideRight, available)
        self._description.setText(elided)


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
            ColorState.OVERTIME: config.COLOR_DANGER,
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

        pixel_size = fit_clock_font_pixel_size(
            self._text, config.FONT_FAMILY, True, self.width(), self.height()
        )
        font = QFont(config.FONT_FAMILY)
        font.setBold(True)
        font.setPixelSize(pixel_size)
        if hasattr(font, "setFeature"):
            # JetBrains Mono's default zero has a dot (its way of telling 0
            # apart from O); the "zero" OpenType feature switches it to a
            # slashed zero instead, which is clearer at a glance on a
            # countdown clock. setFeature was only added in Qt 6.7 — older
            # PySide6 just keeps the (still clean, still unambiguous) dot.
            font.setFeature(QFont.Tag.fromString("zero"), 1)

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
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        top_row = QHBoxLayout()
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

        top_row.addLayout(left, 1)
        top_row.addWidget(self._duration)

        self._description = QLabel("")
        self._description.setObjectName("nextDescription")
        self._description.setWordWrap(True)
        self._description.setStyleSheet(styles.NEXT_DESCRIPTION_QSS)
        # QLabel defaults to Qt::AutoText, which auto-detects HTML-looking
        # content and renders it as rich text. A description like "Q&A
        # session" would then get silently mangled on the live,
        # audience-facing display. Force plain text so the description
        # always renders literally, regardless of content.
        self._description.setTextFormat(Qt.TextFormat.PlainText)
        self._description.setVisible(False)

        outer.addLayout(top_row)
        outer.addWidget(self._description)

        self._last_args: tuple[str | None, int | None, str | None] | None = None

    def set_next(self, name: str | None, duration_seconds: int | None, description: str | None = None) -> None:
        # NextBar.set_next() will be called ~5x/second from the main tick
        # loop (Task 7); skip the redundant setText/setVisible work when
        # nothing actually changed since the last call, mirroring the
        # guard MiniTimetable.set_rows() and WatermarkLabel.set_margin_px()
        # already use for the same reason.
        args = (name, duration_seconds, description)
        if args == self._last_args:
            return
        self._last_args = args

        if name is None:
            self.setVisible(False)
            return
        self.setVisible(True)
        self._name.setText(name)
        self._duration.setText(f"-{format_remaining(duration_seconds or 0)}")
        text = (description or "").strip()
        self._description.setText(text)
        self._description.setVisible(bool(text))


class MiniTimetable(QListWidget):
    """Compact read-only overview of the whole timetable, current event
    highlighted green and kept in view via auto-scroll."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(styles.MINI_TIMETABLE_QSS)
        self._rows: list[ScheduleRow] = []

    def set_rows(self, rows: list[ScheduleRow]) -> None:
        if rows == self._rows:
            # Called every 200ms tick from MainDisplay; skip the full
            # clear+rebuild (and the accompanying scrollToItem) when nothing
            # actually changed since the last tick, since ScheduleRow is a
            # frozen, equality-comparable dataclass.
            return
        self._rows = rows
        self.clear()
        current_item: QListWidgetItem | None = None
        for row in rows:
            time_label = format_clock_time(row.effective_start_seconds)
            duration_label = format_remaining(row.duration_seconds)
            item = QListWidgetItem(f"{time_label}  {row.name}  ({duration_label})")
            if row.is_current:
                item.setForeground(QColor(config.COLOR_SUCCESS_GREEN))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                current_item = item
            self.addItem(item)
        if current_item is not None:
            self.scrollToItem(current_item, QAbstractItemView.ScrollHint.PositionAtCenter)


class ScheduleDelayLabel(QLabel):
    """Small readout meant to sit directly under the main clock, showing
    cumulative schedule delay across the whole day — independent of the
    current event's own countdown (which the big clock already shows).
    Hidden entirely when there's nothing meaningful to report (EMPTY,
    AWAITING_START, AFTER_LAST)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._last_seconds: float | None = None
        self.setVisible(False)

    def set_delay_seconds(self, seconds: float | None) -> None:
        if seconds == self._last_seconds:
            return
        self._last_seconds = seconds
        if seconds is None:
            self.setVisible(False)
            return
        self.setVisible(True)
        if seconds <= 0:
            self.setText("ON SCHEDULE")
            self.setStyleSheet(styles.SCHEDULE_DELAY_ONTIME_QSS)
        else:
            self.setText(f"SCHEDULE {format_remaining(seconds)} BEHIND")
            self.setStyleSheet(styles.SCHEDULE_DELAY_BEHIND_QSS)
