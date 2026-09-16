from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget

from stagetimer.core.state_machine import TimerEngine


def register_main_display_shortcuts(
    widget: QWidget, engine: TimerEngine, toggle_config_window: Callable[[], None]
) -> list[QShortcut]:
    """Register keyboard shortcuts scoped to `widget` (the fullscreen main
    display), so they don't fire while typing in the config window's text
    fields (which live in a separate top-level widget).

    Deliberately minimal: Space is the only playback action available on
    the main display — it always advances to the next event (same action
    as Skip Next), matching "space bar always required to start any
    event." Every other manual control (Pause/Resume/Skip Prev/Skip
    Next/Adjust) is reachable only through the Ctrl+E config window's Live
    Controls buttons, never from the main display's own keyboard."""

    bindings: list[tuple[str, Callable[[], None]]] = [
        ("Space", engine.skip_next),
        ("Ctrl+E", toggle_config_window),
    ]

    shortcuts: list[QShortcut] = []
    for key_sequence, handler in bindings:
        shortcut = QShortcut(QKeySequence(key_sequence), widget)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(handler)
        shortcuts.append(shortcut)
    return shortcuts
