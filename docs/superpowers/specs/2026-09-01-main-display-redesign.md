# Main Display Redesign — Design

## Context

An operator's colleague reviewed StageTimer on the actual hardware and sent back a list of usability feedback. Three items were confirmed as font/rendering bugs and handed off separately for a direct fix (no design needed). This spec covers the remaining main-display layout requests, which all touch the same screen and need one coherent visual pass:

- A live wall-clock (`hh:mm:ss`) in the top-right, so the audience/operator can see the actual time alongside the countdown.
- A compact overview of the whole day's timetable in the bottom-right, with the currently-running event highlighted green — so people can see what's coming without opening the config window.
- The "Current" box (top-left) made larger and visually louder — blue border and soft blue-tinted background — since it's the single most important piece of information on the screen and currently reads as no more prominent than anything else.

Countdown behavior (space-to-start, count-into-negative-overtime) and the config-window features (calendar dates, End Time column, notes, row copy/paste) are separate, later brainstorming passes — out of scope here.

## Layout (chosen direction: "Corners")

Of three layout directions mocked up, the operator picked the one closest to today's structure: everything stays in its existing corner, just bigger/added, rather than a larger structural rework (e.g. a dedicated sidebar).

- **Top-right**: the logo's spot becomes a small vertical stack — the live clock label on top, the existing logo image below it, both right-aligned. No new widget class needed; it's a `QVBoxLayout` composed directly in `MainDisplay`, wrapping the current `logo_box`.
- **Top-left (Current box)**: same `CurrentBox` widget, restyled — blue border + soft blue-tinted background instead of the current plain white outline, and a noticeably larger event-name font.
- **Bottom**: today's single-line `NextBar` row becomes a two-column strip. `NextBar` keeps its current content and position (left side). A new `MiniTimetable` panel sits to its right, listing every event in the day as `time — name (duration)`, one per line, with the currently-running event's line in green and bold. If there are more events than fit the panel's height, it auto-scrolls to keep the current-event line centered in view. The panel gets a fixed-ish minimum height (enough for ~4-5 rows) rather than expanding to fill available space — it's meant to stay a compact reference, not compete with the center clock for the screen's real estate.

## Data: exposing effective event times

The mini timetable needs a clock time for *every* row, including events that don't have their own `start_time` and instead chain off the previous event's end (the optional-start-times feature). That chaining math already exists in `core/scheduler.py` as a private function, `_compute_effective_times`. It gets a small public wrapper:

```python
def compute_effective_start_times(events: list[Event]) -> list[int | None]:
    """Effective start (seconds since midnight, or None if unreachable by
    wall clock) for each event, aligned by index with `events`."""
```

`TimerEngine` (in `core/state_machine.py`) gets one new read-only method, `get_schedule_overview() -> list[ScheduleRow]`, mirroring how `get_display_state()` already works — a plain snapshot the UI polls every tick, no new state stored on the engine:

```python
@dataclass(frozen=True)
class ScheduleRow:
    name: str
    duration_seconds: int
    effective_start_seconds: int | None
    is_current: bool
```

`is_current` is `True` only when the engine's mode is `RUNNING` or `PAUSED` and the row's index matches `_current_index` — during `BEFORE_FIRST`/`AWAITING_START`/`AFTER_LAST`/`EMPTY` nothing is highlighted, matching how none of today's UI treats those modes as "something is current" either.

## New/changed widgets

- **`MiniTimetable`** (`ui/display_widgets.py`, new): a `QListWidget` (no selection, no focus ring, frame hidden) styled as plain text rows. `set_rows(rows: list[ScheduleRow])` clears and repopulates it each tick, bolds+greens the current row, and calls `scrollToItem(..., PositionAtCenter)` on it so it's always in view regardless of list length. A small `format_clock_time(seconds: int) -> str` helper (→ `"HH:MM"`) sits alongside it; rows with no effective start show `"--:--"`.
- **`CurrentBox`**: unchanged structurally, restyled via `styles.CURRENT_BOX_QSS` (new blue border/background color constants added to `config.py`: `COLOR_ACCENT_BLUE`, `COLOR_SUCCESS_GREEN` for the mini timetable's current-row highlight) and a larger `currentName` font size.
- **Real-time clock**: a plain styled `QLabel`, no new class — instantiated directly in `MainDisplay.__init__`, text refreshed each tick via `datetime.now().strftime("%H:%M:%S")`. Reuses the existing 200ms tick timer; no new timer needed.

`MainDisplay._on_tick` gains two lines (refresh the real-time clock label, refresh `MiniTimetable.set_rows(self.engine.get_schedule_overview())`) alongside its existing mode-based branching, which is otherwise untouched.

## Testing

- `core/scheduler.py`: unit tests for `compute_effective_start_times` against the same anchored/chained/unanchored fixture shapes already covered in `test_scheduler.py`.
- `core/state_machine.py`: unit tests for `get_schedule_overview()` — correct `is_current` placement across all six modes, correct effective-time passthrough for events with and without their own `start_time`.
- `ui/display_widgets.py`: tests in `tests/test_display_widgets.py` (already exists, created by the recent font-bug fix) for `MiniTimetable.set_rows` — row count, current-row styling, and `format_clock_time`'s `None`-handling.
- Existing `tests/test_ui_smoke.py` pattern (offscreen Qt) for confirming `MainDisplay` wires the new widgets into `_on_tick` without breaking the existing mode-based rendering tests.

## Error handling / edge cases

- Empty timetable: `get_schedule_overview()` returns `[]`; `MiniTimetable` shows nothing (already handles an empty list naturally as a `QListWidget` with zero items).
- All-events-unanchored (`AWAITING_START`): every row still shows via `compute_effective_start_times` returning `None` for all of them → all rows display `"--:--"` as their time, `is_current` is `False` for all (matches the mode gating above).
- Very long event names: `MiniTimetable` rows elide with Qt's default "…" truncation for list items (no horizontal scrollbar, per the widget setup above) rather than wrapping to multiple lines — keeps each row a fixed single-line height so the panel's row count (and thus its height/scroll behavior) stays predictable. Not a bespoke behavior — it's `QListWidget`'s default.
