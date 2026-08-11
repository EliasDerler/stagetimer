from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from stagetimer.core.models import Event
from stagetimer.ui.display_widgets import format_remaining

COLUMNS = ["Name", "Start Time", "Duration"]


class EventTableModel(QAbstractTableModel):
    def __init__(self, events: list[Event] | None = None, parent=None):
        super().__init__(parent)
        self._events: list[Event] = list(events) if events else []

    # -- Qt model interface --------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._events)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole or orientation != Qt.Orientation.Horizontal:
            return None
        return COLUMNS[section]

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        event = self._events[index.row()]
        column = index.column()
        if column == 0:
            return event.name
        if column == 1:
            return event.start_time.strftime("%H:%M")
        if column == 2:
            return format_remaining(event.duration_seconds)
        return None

    # -- data access -----------------------------------------------------------

    def events(self) -> list[Event]:
        return list(self._events)

    def event_at(self, row: int) -> Event:
        return self._events[row]

    def set_events(self, events: list[Event]) -> None:
        self.beginResetModel()
        self._events = sorted(events, key=lambda e: e.start_time)
        self.endResetModel()

    def add_event(self, event: Event) -> None:
        self.set_events([*self._events, event])

    def replace_event(self, row: int, event: Event) -> None:
        events = list(self._events)
        events[row] = event
        self.set_events(events)

    def remove_row(self, row: int) -> None:
        events = list(self._events)
        del events[row]
        self.set_events(events)

    def move_up(self, row: int) -> None:
        if row <= 0:
            return
        self.beginResetModel()
        self._events[row - 1], self._events[row] = self._events[row], self._events[row - 1]
        self.endResetModel()

    def move_down(self, row: int) -> None:
        if row >= len(self._events) - 1:
            return
        self.beginResetModel()
        self._events[row + 1], self._events[row] = self._events[row], self._events[row + 1]
        self.endResetModel()
