from __future__ import annotations

import dataclasses
import shutil
import uuid
from datetime import time
from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableView,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from stagetimer import config
from stagetimer.core import persistence
from stagetimer.core.models import Event, Timetable
from stagetimer.core.state_machine import Mode, TimerEngine
from stagetimer.ui.event_table_model import EventTableModel


class EventEditDialog(QDialog):
    def __init__(self, event: Event | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Edit Event" if event else "Add Event")

        self.name_edit = QLineEdit(event.name if event else "")

        self.has_start_time = QCheckBox("Has start time")
        has_time = event.start_time is not None if event else True
        self.has_start_time.setChecked(has_time)

        self.start_edit = QTimeEdit()
        self.start_edit.setDisplayFormat("HH:mm")
        start = event.start_time if (event and event.start_time) else time(9, 0)
        self.start_edit.setTime(start)
        self.start_edit.setEnabled(has_time)
        self.has_start_time.toggled.connect(self.start_edit.setEnabled)

        start_row = QHBoxLayout()
        start_row.addWidget(self.has_start_time)
        start_row.addWidget(self.start_edit)

        total_minutes = (event.duration_seconds // 60) if event else 15
        self.duration_minutes = QSpinBox()
        self.duration_minutes.setRange(0, 24 * 60)
        self.duration_minutes.setSuffix(" min")
        self.duration_minutes.setValue(total_minutes)

        self.description_edit = QTextEdit()
        self.description_edit.setPlainText(event.description if event else "")
        self.description_edit.setFixedHeight(80)

        form = QFormLayout()
        form.addRow("Name:", self.name_edit)
        form.addRow("Start time:", start_row)
        form.addRow("Duration:", self.duration_minutes)
        form.addRow("Description:", self.description_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self._result_event: Event | None = None
        self._original_id = event.id if event else None

    def _on_accept(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing name", "Please enter an event name.")
            return
        if self.has_start_time.isChecked():
            qt_time = self.start_edit.time()
            start_time = time(qt_time.hour(), qt_time.minute(), 0)
        else:
            start_time = None
        duration_seconds = self.duration_minutes.value() * 60
        description = self.description_edit.toPlainText().strip()

        kwargs = dict(name=name, start_time=start_time, duration_seconds=duration_seconds, description=description)
        if self._original_id:
            self._result_event = Event(id=self._original_id, **kwargs)
        else:
            self._result_event = Event(**kwargs)
        self.accept()

    def result_event(self) -> Event | None:
        return self._result_event


class ConfigWindow(QWidget):
    """Ctrl+E overlay: timetable editor, logo picker, and live playback controls."""

    def __init__(
        self,
        engine: TimerEngine,
        timetable: Timetable,
        on_logo_changed: Callable[[str], None],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("StageTimer — Configuration")
        self.resize(720, 560)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        self.engine = engine
        self._logo_path = timetable.logo_path
        self._on_logo_changed = on_logo_changed
        self._clipboard_event: Event | None = None
        self.model = EventTableModel(timetable.sorted_events())

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(lambda _: self._edit_selected())

        table_buttons = QHBoxLayout()
        add_btn = QPushButton("Add")
        edit_btn = QPushButton("Edit")
        delete_btn = QPushButton("Delete")
        copy_btn = QPushButton("Copy")
        paste_btn = QPushButton("Paste")
        up_btn = QPushButton("Move Up")
        down_btn = QPushButton("Move Down")
        add_btn.clicked.connect(self._add_event)
        edit_btn.clicked.connect(self._edit_selected)
        delete_btn.clicked.connect(self._delete_selected)
        copy_btn.clicked.connect(self._copy_selected)
        paste_btn.clicked.connect(self._paste_event)
        up_btn.clicked.connect(lambda: self._move_selected(-1))
        down_btn.clicked.connect(lambda: self._move_selected(1))
        for btn in (add_btn, edit_btn, delete_btn, copy_btn, paste_btn, up_btn, down_btn):
            table_buttons.addWidget(btn)
        table_buttons.addStretch(1)

        timetable_box = QGroupBox("Timetable")
        timetable_layout = QVBoxLayout(timetable_box)
        timetable_layout.addWidget(self.table)
        timetable_layout.addLayout(table_buttons)

        self.logo_label = QLabel(self._logo_path or "No logo selected")
        logo_btn = QPushButton("Choose Logo...")
        logo_btn.clicked.connect(self._choose_logo)
        logo_row = QHBoxLayout()
        logo_row.addWidget(self.logo_label, 1)
        logo_row.addWidget(logo_btn)

        logo_box = QGroupBox("Logo")
        logo_box_layout = QVBoxLayout(logo_box)
        logo_box_layout.addLayout(logo_row)

        start_btn = QPushButton("Start")
        pause_btn = QPushButton("Pause")
        resume_btn = QPushButton("Resume")
        prev_btn = QPushButton("« Skip Prev")
        next_btn = QPushButton("Skip Next »")
        minus_btn = QPushButton("-1 min")
        plus_btn = QPushButton("+1 min")
        start_btn.clicked.connect(self.engine.start)
        pause_btn.clicked.connect(self.engine.pause)
        resume_btn.clicked.connect(self.engine.resume)
        prev_btn.clicked.connect(self.engine.skip_prev)
        next_btn.clicked.connect(self.engine.skip_next)
        minus_btn.clicked.connect(lambda: self.engine.adjust(-60))
        plus_btn.clicked.connect(lambda: self.engine.adjust(60))

        controls_row = QHBoxLayout()
        for btn in (start_btn, prev_btn, pause_btn, resume_btn, next_btn, minus_btn, plus_btn):
            controls_row.addWidget(btn)

        self._start_btn = start_btn

        controls_box = QGroupBox("Live Controls")
        controls_layout = QVBoxLayout(controls_box)
        controls_layout.addLayout(controls_row)

        root = QVBoxLayout(self)
        root.addWidget(timetable_box, 1)
        root.addWidget(logo_box)
        root.addWidget(controls_box)

        QShortcut(QKeySequence("Escape"), self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+C"), self, activated=self._copy_selected)
        QShortcut(QKeySequence("Ctrl+V"), self, activated=self._paste_event)

        # ConfigWindow and MainDisplay share one TimerEngine but each owns its
        # own polling loop (there's no engine-change signal) — this timer
        # keeps the Start button's enabled state in sync with engine mode.
        self._start_refresh_timer = QTimer(self)
        self._start_refresh_timer.setInterval(250)
        self._start_refresh_timer.timeout.connect(self._refresh_start_button)
        self._start_refresh_timer.start()
        self._refresh_start_button()

    # -- timetable editing -----------------------------------------------------

    def _selected_row(self) -> int | None:
        indexes = self.table.selectionModel().selectedRows()
        return indexes[0].row() if indexes else None

    def _refresh_start_button(self) -> None:
        mode = self.engine.get_display_state().mode
        self._start_btn.setEnabled(mode in (Mode.EMPTY, Mode.AWAITING_START, Mode.AFTER_LAST))

    def _add_event(self) -> None:
        dialog = EventEditDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_event():
            self.model.add_event(dialog.result_event())
            self._persist_and_apply()

    def _edit_selected(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        dialog = EventEditDialog(event=self.model.event_at(row), parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_event():
            self.model.replace_event(row, dialog.result_event())
            self._persist_and_apply()

    def _delete_selected(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        self.model.remove_row(row)
        self._persist_and_apply()

    def _copy_selected(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        self._clipboard_event = self.model.event_at(row)

    def _paste_event(self) -> None:
        if self._clipboard_event is None:
            return
        duplicate = dataclasses.replace(self._clipboard_event, id=str(uuid.uuid4()))
        row = self._selected_row()
        insert_at = (row + 1) if row is not None else len(self.model.events())
        self.model.insert_event(insert_at, duplicate)
        self.table.selectRow(insert_at)
        self._persist_and_apply()

    def _move_selected(self, direction: int) -> None:
        row = self._selected_row()
        if row is None:
            return
        if direction < 0:
            self.model.move_up(row)
        else:
            self.model.move_down(row)
        self._persist_and_apply()

    def _choose_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose Logo Image", "", "Images (*.png *.jpg *.jpeg)")
        if not path:
            return
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy(path, config.LOGO_PATH)
        self._logo_path = str(config.LOGO_PATH)
        self.logo_label.setText(self._logo_path)
        self._on_logo_changed(self._logo_path)
        self._persist_and_apply()

    def _persist_and_apply(self) -> None:
        timetable = Timetable(events=self.model.events(), logo_path=self._logo_path)
        persistence.save(config.TIMETABLE_PATH, timetable)
        self.engine.set_timetable(timetable)
