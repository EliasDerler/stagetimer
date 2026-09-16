# Overtime, Shrinkable Events & No-Auto-Start Scheduling — Design

## Context

The last of four colleague-feedback items, deliberately tackled last since it's the largest: today, `TimerEngine` is wall-clock-authoritative — it re-derives "what's currently playing" from the clock on every tick (`scheduler.resolve()`), which is what makes events start and advance automatically. This overhauls that into a fully operator-driven model: nothing ever starts or advances on its own. An event that runs long goes into a visible, ticking overtime instead of being silently replaced by whatever the clock says should be next. Events marked "shrinkable" can absorb upstream delay by having their own live duration reduced, protecting a later fixed-time commitment (the festival-changeover use case: compress the changeover, not the headliner's start time).

## Decisions (confirmed)

1. **No auto-start, ever.** Every transition — including the very first event of the day — requires an explicit operator action. `start_time` stops being a live trigger; it becomes a *target* used only for computing lateness and for the pre-start countdown display.
2. **Main display keyboard shrinks to two shortcuts:** `Space` (advance to the next event — same action as today's Skip Next) and `Ctrl+E` (open config). `Right`/`N` (skip next), `Left`/`P` (skip prev), and `Up`/`Down`/`+`/`-` (adjust ±1 min) are removed from the main display's shortcuts entirely. Pause/Resume/Skip Prev/Skip Next/Adjust remain exactly as they are today, but reachable only via the Ctrl+E window's existing Live Controls buttons.
3. **Overtime:** once the current event's own countdown reaches zero without the operator advancing, it doesn't stop or auto-advance — it goes negative and keeps counting (`-00:01`, `-00:02`, …), rendered in red, until Space is pressed.
4. **Shrinkable events:** marked via a checkbox in the event editor (same pattern as the existing "Has start time" checkbox), with a required per-event floor — a minimum duration it can never compress below.
5. **Pre-start countdown is kept**, live-ticking toward an event's target time even though nothing auto-triggers when it reaches zero — and it can itself go negative/red if the target time passes with Space still not pressed (the "you're late to even start this" case).
6. **Cumulative schedule delay is manually resettable** — a "Reset Schedule" action in Ctrl+E's Live Controls, for cases like an intentionally-extended break that shouldn't read as "running behind."
7. **No visual "this was compressed" indicator** — a shrunk event's countdown just starts from its adjusted value, identical in appearance to any other countdown.
8. **Two independent numbers on the main display**, not one overloaded readout:
   - The big clock: the *current event's own* countdown, negative/red on overrun.
   - A small readout underneath: the *cumulative whole-day schedule delay* — persists across events, live-updates even while the current event is comfortably within budget if an earlier event's overrun hasn't been resolved yet.

## Architecture: the engine's core loop

`TimerEngine._tick_from_wallclock` (which calls `scheduler.resolve()` every tick to decide what's current) is removed entirely — there is no more "what does the clock say should be showing" concept. `_current_index` only ever changes via explicit operator action (`start()`, `skip_next()`, `skip_prev()`, all already existing entry points). Every tick, whatever is current just has its remaining time decremented by elapsed wall-clock time — unclamped, so it can go negative. This is exactly today's `_tick_overridden` path; it becomes the *only* ticking path, since there's no other mode to distinguish it from anymore. `_overridden` as a concept goes away (nothing to override — there was never anything to be "instead of").

`scheduler.compute_effective_start_times()` (the existing chained/anchored planned-time math) is **unchanged** — it keeps computing each event's fixed *target* start/end time from the plan (using each event's full, unshrunk `duration_seconds`). These targets never move during the day; they're the reference the whole delay system measures against. `scheduler.resolve()` is no longer called by `TimerEngine` (nothing needs "what should be current right now" anymore) but can stay in the module — it's harmless, and removing it isn't necessary for this feature to work. `Timetable`/`Event`'s `start_time` field keeps its exact current meaning (an anchor); nothing about the data model's chaining semantics changes, only how the engine *uses* the result.

### Modes

- `EMPTY` — no events. Unchanged.
- `AWAITING_START` — no target time exists anywhere ahead (no anchor, direct or chained, for what's next). Shows "Standing by — press Start", no live countdown. Unchanged in meaning from today.
- `BEFORE_FIRST` — a target time exists for what's next. Shows a live countdown to it (`target_start − now`), which can go negative/red if it passes with Space still not pressed. Unlike today, this can happen before *any* event, not just the day's first — whenever nothing is current yet but a target exists for what comes next.
- `RUNNING` — the current event's live countdown, decrementing every tick, unclamped (can go negative). No auto-advance at zero.
- `PAUSED` — unchanged; only reachable via Ctrl+E now, per decision 2.
- `AFTER_LAST` — only entered when the operator explicitly advances (`skip_next()`) past the final event. Never triggered by the wall clock alone.

### Shrink and delay: one formula, no separate bookkeeping

Two pieces of new engine state:

- `_current_entered_at: datetime | None` — wall-clock moment the operator most recently advanced *forward* into whatever is current (`start()` or `skip_next()`). `None` before the first advance of the day.
- `_delay_at_entry: float` (seconds) — the schedule delay **frozen at the moment `_current_entered_at` was set**, recomputed fresh (replaced, not accumulated) on every forward advance as:

  `_delay_at_entry = (moment of advancing) − target_start(the event just entered)`

  where `target_start` comes from `scheduler.compute_effective_start_times()`. If that target is `None` (nothing anchored anywhere yet in the chain up to this point), `_delay_at_entry = 0` — there's nothing meaningful to compare against, so treat it as "no info," not "on time" or "late."

This single replacement (not an accumulating `+=`) is sufficient to carry accumulated lateness correctly through the whole day, because `target_start` values are fixed from the original plan: an event that starts late but runs its full planned duration hands the *same* lateness forward automatically, since the next event's target is a fixed offset away regardless of when it was actually entered. Worked through by hand (see brainstorming notes): entering an event 3 minutes late and running it exactly as planned reproduces "3 minutes late" when entering the next one; entering a *shrinkable* event 3 minutes late, with a floor that lets it absorb the full 3 minutes, produces "0 minutes late" entering the one after — no separate "credit" mechanism needed, it falls straight out of the formula.

**Effective (possibly shrunk) duration**, computed once at the moment an event becomes current via a forward advance:

  `effective_duration = duration_seconds` if not shrinkable, else
  `effective_duration = max(min_duration_seconds, duration_seconds − max(0, _delay_at_entry))`

This is what the countdown actually starts from (i.e. `_remaining_seconds` is initialized to this value instead of always `duration_seconds`, exactly like `_jump_to` does today except for the shrink adjustment). A shrinkable event ahead of schedule (`_delay_at_entry < 0`) is never inflated — shrink only ever helps catch up, never pads.

**Live cumulative delay, shown in the small readout, at any tick:**

  - While something is current (`RUNNING`/`PAUSED`): `_delay_at_entry + max(0, -_remaining_seconds)` — i.e. the delay frozen at entry, plus however far into overtime the *current* event has gone right now. This is intentionally *not* live-decreasing while a shrinkable event runs on-schedule — it stays flat at the frozen value and resolves cleanly to whatever the next entry computes, the instant the operator actually advances. (Considered a live gradually-draining version instead; rejected as more complex to implement and no clearer to the operator than "watch it resolve when you finish this event.")
  - Before anything has ever started (`BEFORE_FIRST`): `max(0, now − target_start(upcoming event))` — the same pre-start countdown-gone-negative case from decision 5, expressed as delay.
  - `AWAITING_START`/`EMPTY`: no target exists, nothing to show — the readout is hidden.

**Gaps absorb overrun for free, automatically** — no separate mechanism needed. If event B has its own anchor later than where pure chaining from event A would land (deliberate slack), then `target_start(B)` already reflects that later time, so `_delay_at_entry` computed against it is only positive if the *actual* overrun ate past the gap too. An event that finishes late but still within a built-in buffer produces a zero or even negative `_delay_at_entry` for what follows — "ahead of the (slack-adjusted) target," exactly as intended.

**Backward moves and manual adjustment don't touch delay.** `skip_prev()` always resets the target event to its full, unshrunk `duration_seconds` (no shrink logic applied — going backward isn't "arriving via the normal flow") and does not update `_current_entered_at`/`_delay_at_entry`. `adjust(±60s)` (existing Ctrl+E buttons) changes only `_remaining_seconds` for whatever's current, same as today — it's a live on-the-fly correction, not a schedule-delay event.

**"Reset Schedule"** (new Ctrl+E action): sets `_current_entered_at = now` and `_delay_at_entry = 0`. The live delay formula continues from there unchanged — effectively "treat this exact moment as if I'd just walked into the current event on time."

**On `set_timetable()`** (day switch, app restart): `_current_entered_at` and `_delay_at_entry` reset to their initial `None`/`0` state, alongside everything else that already resets there.

## Data model

`Event` (`core/models.py`) gains two fields:

```
shrinkable: bool = False
min_duration_seconds: int = 0
```

Included in `to_dict()`/`from_dict()`; `from_dict()` defaults both when missing, same backward-compatible pattern used for `description`.

`DisplayState` (`core/state_machine.py`) gains:

```
schedule_delay_seconds: float | None = None
```

`None` means "nothing to show" (EMPTY/AWAITING_START); a number (which can be 0 or negative) means the readout should render. Rendered as an unsigned magnitude with a "BEHIND"/"ON SCHEDULE" label rather than a signed number (matching the accepted mockup's "SCHEDULE 03:45 BEHIND" / "ON SCHEDULE" pill) — a negative `schedule_delay_seconds` (running ahead) also displays as "ON SCHEDULE", since there's no operator-facing value in distinguishing "ahead" from "on time."

## Main display

- `format_remaining()` (`ui/display_widgets.py`) currently clamps to zero (`max(0, ...)`) — it needs an overtime-aware sibling (or a parameter) that, for negative input, renders `-MM:SS`/`-HH:MM:SS` instead of clamping. The existing clamped version stays as-is for anywhere overtime can't apply (e.g. the Next bar's duration display, which is always a forward-looking positive number).
- `ColorState` (`core/state_machine.py`) gains `OVERTIME`. `color_state_for()` checks `remaining_seconds < 0` first, before the existing yellow/red/flash thresholds, and returns `OVERTIME` — a steady (non-flashing) red, distinct from the existing `FLASH` state's alternating colors, matching "static" in decision 3. `ClockLabel._apply_color_state` gets a new `OVERTIME: config.COLOR_DANGER` mapping (reusing the existing danger-red color, no new color constant needed) alongside the existing `NORMAL`/`WARNING_YELLOW`/`DANGER_RED` entries, and the `FLASH` special-case stays exactly as-is for the last-minute-of-a-normal-countdown case.
- A new small widget (name TBD at planning time, e.g. `ScheduleDelayLabel`) is added to `main_display.py`'s layout directly between `clock_area` and the divider — "under the main clock" as asked for. Renders the small pill/text style from the accepted mockup (Option C): red text/badge when `schedule_delay_seconds > 0`, a neutral/green "on schedule" state at 0, hidden entirely when `schedule_delay_seconds is None`.
- The pre-start countdown (`BEFORE_FIRST` mode) reuses the same big-clock overtime rendering once its target passes zero — no separate code path, just the same negative-aware formatting/coloring applied to whatever `remaining_seconds` `BEFORE_FIRST` carries.
- The mini-timetable (schedule overview) is **not** changed — it continues showing each event's original planned duration and target time from `compute_effective_start_times()`/`duration_seconds`, unaffected by any live shrink applied to whichever event happens to be current. It's a reference view of the plan, not live state (consistent with decision 7 — no special "this was compressed" treatment anywhere).

## Config window

- `EventEditDialog` gets a "Shrinkable" `QCheckBox` and a minutes `QSpinBox` for the floor, placed after the existing Duration field and before Description — following the exact enable/disable pattern already used for `has_start_time`/`start_edit` (the floor spinner is disabled unless Shrinkable is checked).
- Ctrl+E's Live Controls row gains a "Reset Schedule" button, alongside the existing Start/Pause/Resume/Skip Prev/Skip Next/-1 min/+1 min buttons, wired to the engine's new reset action.
- The timetable table (`event_table_model.py`) is not changed — shrinkable/floor aren't proposed as new table columns, consistent with keeping the plan-reference view (table + mini-timetable) showing the unshrunk plan.

## Testing

- `core/scheduler.py`: unchanged, existing tests should still pass untouched (confirms the "no changes needed here" architectural claim).
- `core/state_machine.py`: the bulk of new coverage — `_tick_from_wallclock` removal (auto-start no longer happens even when wall clock passes an anchor with nothing done); overtime going negative and staying negative (no auto-advance); the delay formula across the exact scenarios worked out above (late-and-not-shrunk carries forward unchanged; late-and-shrunk-with-enough-floor resolves to zero; late-and-shrunk-but-floor-insufficient carries the remainder forward); gap absorption (anchored event with slack fully or partially absorbing a prior overrun); `skip_prev`/`adjust` not touching delay; `Reset Schedule` zeroing the live value immediately.
- `ui/display_widgets.py`: negative-aware formatting function; `ColorState.OVERTIME` mapping and that it doesn't flash; the new schedule-delay widget's three states (behind/on-time/hidden).
- `ui/config_window.py`: Shrinkable checkbox + floor spinner round-trip through `EventEditDialog`; floor spinner enable/disable toggling; Reset Schedule button wiring.
- `ui/shortcuts.py`/`ui/main_display.py`: Space maps to `skip_next()` (not pause/resume); Right/N/Left/P/Up/Down/+/- are no longer registered on the main display.

## Error handling / edge cases

- A shrinkable event with `min_duration_seconds >= duration_seconds` (a nonsensical floor at or above the planned duration): the effective-duration formula's `max(min_duration, ...)` naturally clamps to `min_duration_seconds` and never actually shrinks below the planned value in practice, since it can't shrink below its own floor — this just means the event behaves as if it weren't shrinkable at all. No special-cased validation needed, though the event editor should probably still cap the floor spinner's range to `[0, duration_minutes]` for sanity (implementation detail, not a design gap).
- The very first event of the day, if shrinkable, computing its effective duration against `_delay_at_entry` computed from `AWAITING_START`/`BEFORE_FIRST`'s pending-delay value (per the "before anything has ever started" formula above) — this is intentionally the same formula path, not a special case.
- Loading a timetable saved before this feature existed: `shrinkable` defaults to `False`, `min_duration_seconds` defaults to `0` — fully backward compatible, no migration needed (same pattern as `description`).
