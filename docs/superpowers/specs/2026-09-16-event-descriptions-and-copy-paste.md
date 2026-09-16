# Event Descriptions + Copy/Paste — Design

## Context

Two small-to-medium features requested together since both touch the config window's timetable editor:

1. A free-text description per event, surfaced both in the config window and on the main audience-facing display.
2. Copy/paste for events in the config window, to quickly duplicate rows (e.g. repeated "Changeover" entries).

Both are additive — no existing behavior changes, and both are backward compatible with timetables saved before this change.

## Data model

`Event` (`core/models.py`) gains one new field:

```python
description: str = ""
```

Included in `to_dict()`/`from_dict()`; `from_dict()` uses `data.get("description", "")` so existing saved timetables without the key load with an empty description, no migration needed.

## Main display placement

**Current box** (top-left): the event name and description sit side by side on one line — name keeps its existing bold 44px style; description renders in a smaller (22px), non-bold style to its right, sharing the row via a `QHBoxLayout`. If the description doesn't fit the remaining width, it's elided with "…" (Qt's standard truncation, recomputed on resize — the same pattern `WatermarkLabel` already uses for resize-driven rescaling). No dynamic multi-size shrinking — a fixed smaller size is simpler and trivially satisfies "never bigger than the name." Empty description renders nothing extra; box looks exactly as it does today.

**Next bar** (bottom-left): the next event's description, when present, renders in full underneath its name — word-wrapped, never truncated, causing the bar to grow taller to fit. `NextBar` changes from a single `QHBoxLayout` to a `QVBoxLayout` containing the existing top row (NEXT · name · duration) plus a description `QLabel` (`setWordWrap(True)`, hidden entirely via `setVisible(False)` when there's no description — collapsing back to today's exact single-line height).

Both flow through `TimerEngine.get_display_state()`: `DisplayState` gains `current_description: str | None = None` and `next_description: str | None = None`, populated alongside the existing name/duration fields in every branch (defaulted so any incidental direct construction elsewhere doesn't break).

The mini-timetable (bottom-right) is **not** touched — descriptions aren't shown there, out of scope per the original ask.

## Config window

- `EventEditDialog` gets a multi-line `QTextEdit` for the description, below the existing Duration field.
- The timetable table gets a 4th "Description" column, showing a single-line preview: newlines collapsed to spaces, then truncated to 40 characters with a trailing "…" if longer.
- Copy/Paste: buttons alongside the existing Add/Edit/Delete/Move Up/Move Down row, plus Ctrl+C/Ctrl+V shortcuts scoped to the `ConfigWindow` (safe from colliding with normal text-field copy/paste, since `EventEditDialog` is a separate modal window — Qt's default `WindowShortcut` context means the `ConfigWindow`'s shortcuts don't fire while the dialog is the active window). Copy stores the selected event; Paste creates a duplicate (fresh UUID, every other field identical — including start time, so a pasted anchored event needs its time edited by hand) inserted directly after the currently-selected row (or at the end, if nothing's selected). Pasting repeatedly stacks up multiple copies.

## Testing

- `core/models.py`: description round-trips through `to_dict()`/`from_dict()`, including the empty-string default when a saved timetable predates this field.
- `core/state_machine.py`: `get_display_state()` surfaces `current_description`/`next_description` correctly across all six modes.
- `ui/display_widgets.py`: `CurrentBox` elides long descriptions and renders short ones in full; `NextBar` shows/hides its description row correctly and doesn't truncate.
- `ui/event_table_model.py`: Description column preview truncation.
- `ui/config_window.py`: `EventEditDialog` description field round-trips; copy/paste inserts a duplicate with a new ID at the right position, and repeated pasting stacks correctly.
- `ui/main_display.py`: description flows from `DisplayState` into both widgets during `_on_tick`.

## Error handling / edge cases

- Empty/whitespace-only description: treated as "no description" everywhere (Current box shows nothing extra, Next bar's description row stays hidden).
- Very long single-word description with no natural wrap point in the Next bar: standard Qt word-wrap behavior (breaks mid-word only as a last resort) — not a special case.
- Copy with nothing selected: no-op (nothing to copy).
- Paste with nothing ever copied: no-op.
