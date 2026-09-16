# Multi-Day Timetable Management — Design

## Context

StageTimer currently persists exactly one timetable (`~/.local/share/stagetimer/timetable.json`). Festivals and multi-day events need several distinct, named timetables ("days") that can be created, switched between, renamed, and deleted independently, with the operator's last-used day remembered across restarts.

## Decisions (confirmed)

1. **Storage:** one JSON file per day, not one big multi-day file or a snapshot-copy folder.
2. **Naming:** a free-text display name; a stable internal UUID (not the name) drives the filename, so renaming never touches the file on disk.
3. **Switching UI:** a new "Day" menu (not a dropdown in the config window, not a separate management dialog).
4. **Switching while RUNNING/PAUSED:** show a confirmation dialog, then proceed if confirmed.
5. **New day content:** ask each time — start empty, or duplicate the currently active day's events.
6. **Deleting a day:** always confirm; no floor — deleting down to zero days is allowed.
7. **Restore on restart:** yes, the app reopens whichever day was active when it last closed.
8. **Active-day indicator:** shown in the Config window's title bar.

## Data model & storage

New module `core/day_store.py`, sitting alongside `core/persistence.py` (which keeps doing the actual JSON read/write — `day_store` just adds the multi-file/id/name layer on top).

- `DAYS_DIR = config.DATA_DIR / "days"` — one file per day: `days/<uuid>.json`.
- Each day file's shape: `{"id": "<uuid>", "name": "<display name>", "timetable": {...Timetable.to_dict()...}}` — the existing `Timetable` schema (version/logo_path/events) is reused unchanged and nested under `"timetable"`, so `Timetable`/`Event` themselves need no changes.
- `ACTIVE_DAY_PATH = config.DATA_DIR / "active_day.json"` — `{"active_day_id": "<uuid>"}`, updated every time the active day changes.
- New dataclass `DayMeta(id: str, name: str, modified_at: float)` for listing days (the Day menu needs id+name; `modified_at`, from the file's mtime, is used to pick a fallback day when the active one is deleted).

`day_store` public functions:

- `list_days() -> list[DayMeta]` — reads every file in `DAYS_DIR`, sorted by name.
- `load_day(day_id: str) -> Timetable` — reads `days/<id>.json`, returns the nested `Timetable`.
- `save_day(day_id: str, name: str, timetable: Timetable) -> None` — atomic write (same temp-file-then-`os.replace` pattern as `persistence.save`).
- `create_day(name: str, timetable: Timetable) -> str` — generates a fresh UUID, saves, returns the new id.
- `rename_day(day_id: str, new_name: str) -> None` — rewrites the file with a new `name`, same id/timetable.
- `delete_day(day_id: str) -> None` — removes the file.
- `get_active_day_id() -> str | None` / `set_active_day_id(day_id: str) -> None` — read/write `active_day.json`.
- `ensure_startup_day() -> str` — called once at app startup:
  - If `DAYS_DIR` already has at least one day file: return the active day id if it still points at an existing day, otherwise fall back to the first day (sorted by name) and persist that as active.
  - Else if the legacy `config.TIMETABLE_PATH` exists: load it via `persistence.load`, wrap it into a new day named `"Day 1"`, save it under `days/`, mark it active, and return its id. The legacy file is left on disk untouched (not deleted) — harmless, never read again once migrated.
  - Else (no days, no legacy file): create a new empty day named `"Day 1"`, mark it active, return its id.

## Wiring into `app.py`

- Startup: `active_day_id = day_store.ensure_startup_day()`, then `timetable = day_store.load_day(active_day_id)` replaces today's `persistence.load(config.TIMETABLE_PATH)` call. `TimerEngine` construction is unchanged.
- The existing `state` dict (already used to track the lazily-constructed `ConfigWindow` singleton) gains `state["active_day_id"] = active_day_id`, so that if the Ctrl+E window is closed and reopened, the next `ConfigWindow` is constructed with whatever day is *currently* active, not the one from app startup.
- `ConfigWindow`'s constructor gains two parameters: `active_day_id: str` and `on_day_changed: Callable[[str], None]` — the latter follows the exact same pattern as the existing `on_logo_changed` callback, and is wired in `app.py` to `state["active_day_id"] = new_id`.

## `ConfigWindow` changes

- Title bar becomes `f"StageTimer — Configuration — {day_name}"`, updated on every switch/rename.
- A `QMenuBar` is attached via `root.setMenuBar(menu_bar)` (the standard Qt mechanism for giving a plain `QWidget` — not a `QMainWindow` — a menu bar inside its own layout), containing one "Day" menu:
  - One checkable `QAction` per day from `day_store.list_days()`, checked iff it's the active day; triggering an unchecked one calls `_switch_to_day(day_id)`.
  - Separator, then "New Day…", "Rename Current Day…", "Delete Current Day…" (rename/delete act on whichever day is currently active — no per-row menu needed, keeping the menu simple).
  - The menu is rebuilt (`clear()` + repopulate) every time it's opened (`aboutToShow`) and after every switch/create/rename/delete, so it never shows stale state.
- `_switch_to_day(day_id)`:
  - No-op if `day_id == self._active_day_id`.
  - If `self.engine.get_display_state().mode` is `RUNNING` or `PAUSED`: `QMessageBox.question(...)` — "Switch to '<name>'? This will stop the current timer." Abort on anything but Yes.
  - `timetable = day_store.load_day(day_id)`; update `self._active_day_id`, `self._active_day_name`, `self._logo_path`; `self.model.set_events(timetable.sorted_events())`; `self.engine.set_timetable(timetable)` (this already fully resets engine state to `Mode.EMPTY` → re-derives `AWAITING_START`/`BEFORE_FIRST` from the new events on the next tick, exactly like today's post-edit `_persist_and_apply` flow); `self._on_logo_changed(self._logo_path)`; `day_store.set_active_day_id(day_id)`; `self._on_day_changed(day_id)`; refresh window title and Day menu.
- `_new_day()`: `QInputDialog.getText(...)` for a name (blank/cancel aborts) → `QMessageBox` with custom Yes/No buttons asking "Start empty, or duplicate events from '<current day name>'?" → build the initial `Timetable` accordingly (duplicate = `dataclasses.replace` of the current `Timetable`, keeping event ids as-is — ids only need to be unique within a day, not across days) → `day_store.create_day(name, timetable)` → `_switch_to_day(new_id)` (reuses the same running-timer confirmation and all state updates).
- `_rename_current_day()`: `QInputDialog.getText(...)` pre-filled with `self._active_day_name` → `day_store.rename_day(self._active_day_id, new_name)` → update `self._active_day_name`, window title, Day menu.
- `_delete_current_day()`: confirm via `QMessageBox` → `day_store.delete_day(self._active_day_id)` → if other days remain, switch to the most-recently-modified one (`max(day_store.list_days(), key=lambda d: d.modified_at)`); if none remain, fall back to an empty in-memory state: `self.engine.set_timetable(Timetable())`, `self.model.set_events([])`, clear `self._active_day_id`/`self._active_day_name` (title shows "No day loaded"), `day_store.set_active_day_id(None)`... — actually `active_day.json` shouldn't hold an invalid/null id since `ensure_startup_day()` expects either a valid id or a missing file; simplest: delete `ACTIVE_DAY_PATH` entirely (`get_active_day_id()` returning `None` for "file missing" already covers this) so a subsequent restart correctly falls through to "no days → create empty Day 1" rather than trying to load a nonexistent id.
- `_persist_and_apply()` (existing method, used by every event-editing action) changes its save call from `persistence.save(config.TIMETABLE_PATH, timetable)` to `day_store.save_day(self._active_day_id, self._active_day_name, timetable)` — the rest of the method (building the `Timetable`, calling `self.engine.set_timetable(timetable)`) is unchanged.

## Known limitation: the logo file is shared, not per-day

`config.LOGO_PATH` (`~/.local/share/stagetimer/logo.png`) is a single physical file — `_choose_logo()` always copies the chosen image on top of it, and every day's `Timetable.logo_path` field just stores that same shared path string. This pre-existing behavior is untouched by this plan: picking a logo while on one day overwrites the physical image every other day's `logo_path` also points at, so in practice all days end up showing whichever logo was picked most recently, regardless of which day picked it. Making logos genuinely per-day (e.g. `days/<id>-logo.png`) is a reasonable follow-up but is out of scope here — the original ask was about timetables/events, not per-day branding, and fixing it would mean touching `_choose_logo`'s storage path in a way this plan doesn't otherwise need to.

## What's explicitly out of scope

- The main fullscreen display (`main_display.py`) is untouched — it keeps reading whatever `TimerEngine` currently holds, exactly as it does today after any edit. No day-switching UI is exposed there; day management is operator-only, via the Config window.
- No per-row Rename/Delete in the Day menu — only the active day can be renamed/deleted directly, keeping the menu to a flat list + three actions.
- No day reordering — the Day menu lists days alphabetically by name; there's no persisted "day order" concept.

## Testing

- `core/day_store.py`: create/save/load/list/rename/delete round-trip; `ensure_startup_day()` covers all four startup branches (existing days-with-valid-active-pointer, existing days-with-stale-pointer, legacy-single-file migration, and fresh-install-no-data-at-all); migration leaves the legacy file untouched on disk.
- `ui/config_window.py`: Day menu reflects `day_store.list_days()` and checks the active day; `_switch_to_day` updates model/engine/logo/title and persists the new active id; switching while RUNNING/PAUSED is gated behind confirmation (test both Yes and No/cancel paths); `_new_day` covers both empty and duplicate-events paths; `_delete_current_day` covers both "other days remain → falls back to most-recently-modified" and "last day deleted → empty state" paths; `_persist_and_apply` now writes through `day_store.save_day` with the correct id.

## Error handling / edge cases

- A day file that fails to parse (corrupt JSON) is treated like today's corrupt-timetable handling in `persistence.load` — back it up with a timestamped suffix and skip it from `list_days()` rather than crashing the whole app.
- Deleting the only remaining day is allowed (per decision 6); the app falls back to a genuinely empty state (no active day, empty table, `EMPTY` engine mode) until "New Day…" is used again.
- Renaming a day to a blank name is rejected (same validation pattern as the existing "Missing name" check on event names) — the rename dialog simply doesn't proceed until a non-blank name is given, matching `QInputDialog`'s own cancel-vs-empty handling.
