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
    fields (which live in a separate top-level widget)."""

    def pause_resume_toggle() -> None:
        state = engine.get_display_state()
        if state.is_paused:
            engine.resume()
        else:
            engine.pause()

    bindings: list[tuple[str, Callable[[], None]]] = [
        ("Space", pause_resume_toggle),
        ("Right", engine.skip_next),
        ("N", engine.skip_next),
        ("Left", engine.skip_prev),
        ("P", engine.skip_prev),
        ("Up", lambda: engine.adjust(60)),
        ("=", lambda: engine.adjust(60)),
        ("+", lambda: engine.adjust(60)),
        ("Down", lambda: engine.adjust(-60)),
        ("-", lambda: engine.adjust(-60)),
        ("Ctrl+E", toggle_config_window),
    ]

    shortcuts: list[QShortcut] = []
    for key_sequence, handler in bindings:
        shortcut = QShortcut(QKeySequence(key_sequence), widget)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(handler)
        shortcuts.append(shortcut)
    return shortcuts
