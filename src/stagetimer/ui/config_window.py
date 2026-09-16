from __future__ import annotations

import dataclasses
import shutil
import uuid
from datetime import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenuBar,
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
from stagetimer.core import day_store
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
        on_logo_changed: Callable[[str | None], None],
        active_day_id: str | None = None,
        on_day_changed: Callable[[str | None], None] = lambda day_id: None,
        days_dir: Path = config.DAYS_DIR,
        active_day_path: Path = config.ACTIVE_DAY_PATH,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.resize(720, 560)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        self.engine = engine
        self._logo_path = timetable.logo_path
        self._on_logo_changed = on_logo_changed
        self._active_day_id = active_day_id
        self._active_day_name = "No day loaded"
        self._on_day_changed = on_day_changed
        self._days_dir = days_dir
        self._active_day_path = active_day_path
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

        menu_bar = QMenuBar(self)
        self._day_menu = menu_bar.addMenu("Day")
        self._day_menu.aboutToShow.connect(self._refresh_day_menu)
        root.setMenuBar(menu_bar)

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
        self._refresh_day_menu()

    # -- timetable editing -----------------------------------------------------

    def _selected_row(self) -> int | None:
        indexes = self.table.selectionModel().selectedRows()
        return indexes[0].row() if indexes else None

    def _refresh_start_button(self) -> None:
        mode = self.engine.get_display_state().mode
        self._start_btn.setEnabled(mode in (Mode.EMPTY, Mode.AWAITING_START, Mode.AFTER_LAST))

    # -- day menu ---------------------------------------------------------------

    def _refresh_day_menu(self) -> None:
        self._day_menu.clear()
        days = day_store.list_days(self._days_dir)
        self._active_day_name = next((d.name for d in days if d.id == self._active_day_id), "No day loaded")
        self.setWindowTitle(f"StageTimer — Configuration — {self._active_day_name}")
        for day in days:
            action = QAction(day.name, self)
            action.setCheckable(True)
            action.setChecked(day.id == self._active_day_id)
            action.triggered.connect(lambda checked=False, day_id=day.id: self._switch_to_day(day_id))
            self._day_menu.addAction(action)
        self._day_menu.addSeparator()
        new_action = QAction("New Day...", self)
        new_action.triggered.connect(self._new_day)
        self._day_menu.addAction(new_action)
        rename_action = QAction("Rename Current Day...", self)
        rename_action.triggered.connect(self._rename_current_day)
        rename_action.setEnabled(self._active_day_id is not None)
        self._day_menu.addAction(rename_action)
        delete_action = QAction("Delete Current Day...", self)
        delete_action.triggered.connect(self._delete_current_day)
        delete_action.setEnabled(self._active_day_id is not None)
        self._day_menu.addAction(delete_action)

    def _switch_to_day(self, day_id: str) -> None:
        if day_id == self._active_day_id:
            return
        if self.engine.get_display_state().mode in (Mode.RUNNING, Mode.PAUSED):
            day_name = next((d.name for d in day_store.list_days(self._days_dir) if d.id == day_id), "")
            reply = QMessageBox.question(
                self,
                "Switch day?",
                f"Switch to '{day_name}'? This will stop the current timer.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        timetable = day_store.load_day(self._days_dir, day_id)
        self._active_day_id = day_id
        self._logo_path = timetable.logo_path
        self.model.set_events(timetable.sorted_events())
        self.engine.set_timetable(timetable)
        self.logo_label.setText(self._logo_path or "No logo selected")
        self._on_logo_changed(self._logo_path)
        day_store.set_active_day_id(self._active_day_path, day_id)
        self._on_day_changed(day_id)
        self._refresh_day_menu()

    def _new_day(self) -> None:
        name, ok = QInputDialog.getText(self, "New Day", "Day name:")
        name = name.strip()
        if not ok or not name:
            return

        msg = QMessageBox(self)
        msg.setWindowTitle("New Day")
        msg.setText(f"Start '{name}' empty, or duplicate events from '{self._active_day_name}'?")
        empty_btn = msg.addButton("Empty", QMessageBox.ButtonRole.NoRole)
        msg.addButton("Duplicate", QMessageBox.ButtonRole.YesRole)
        msg.exec()

        if msg.clickedButton() is empty_btn:
            new_timetable = Timetable()
        else:
            new_timetable = Timetable(events=list(self.model.events()), logo_path=self._logo_path)

        new_id = day_store.create_day(self._days_dir, name, new_timetable)
        self._switch_to_day(new_id)

    def _rename_current_day(self) -> None:
        if self._active_day_id is None:
            return
        name, ok = QInputDialog.getText(self, "Rename Day", "Day name:", text=self._active_day_name)
        name = name.strip()
        if not ok or not name:
            return
        day_store.rename_day(self._days_dir, self._active_day_id, name)
        self._refresh_day_menu()

    def _delete_current_day(self) -> None:
        if self._active_day_id is None:
            return
        reply = QMessageBox.question(
            self,
            "Delete Day",
            f"Delete '{self._active_day_name}'? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        day_store.delete_day(self._days_dir, self._active_day_id)
        remaining = day_store.list_days(self._days_dir)
        if remaining:
            fallback = max(remaining, key=lambda d: d.modified_at)
            self._switch_to_day(fallback.id)
        else:
            self._active_day_id = None
            self._logo_path = None
            self.model.set_events([])
            self.engine.set_timetable(Timetable())
            self.logo_label.setText("No logo selected")
            self._on_logo_changed(None)
            day_store.clear_active_day(self._active_day_path)
            self._on_day_changed(None)
            self._refresh_day_menu()

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
        if self._active_day_id is None:
            return
        timetable = Timetable(events=self.model.events(), logo_path=self._logo_path)
        day_store.save_day(self._days_dir, self._active_day_id, self._active_day_name, timetable)
        self.engine.set_timetable(timetable)
