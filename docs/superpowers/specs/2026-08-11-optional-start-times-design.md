# Optional Event Start Times + Start Button — Design

## Context

StageTimer currently requires every event in a timetable to have a wall-clock
start time, since the scheduler resolves "what's current" purely from
`now` against each event's `[start_time, start_time + duration)` range. In
practice, operators often don't want to (or can't) assign a real clock time
to every event — some shows are entirely sequential ("just run through the
agenda when I say go"), and others only have a firm start time for the very
first item, with everything after it flowing back-to-back by duration alone.

This change makes `start_time` optional per event and adds a "Start" button
so a timetable with no clock anchors at all can still be kicked off
manually. It generalizes the existing wall-clock/override hybrid model
rather than replacing it — fully-timed timetables keep behaving exactly as
they do today.

## Scheduling Model

Each event's **effective start** is computed by walking the (list-ordered)
timetable once:

- If the event has an explicit `start_time`, that time is its effective
  start (an "anchor"), regardless of when the previous event ended.
- Otherwise, its effective start is the previous event's effective end
  (`effective_start + duration_seconds`) — it chains directly off its
  predecessor.
- If an event has no `start_time` and there is no anchor yet either from
  itself or any event before it, it has **no effective start** at all. It
  cannot be reached by wall-clock resolution — only by the Start button or
  Skip Next/Prev.

This single rule reproduces all the scheduling shapes that matter:

| Timetable shape | Result |
|---|---|
| No event has a `start_time` | Nothing has an effective start; wall clock never selects a current event. Only Start/skip can begin playback. |
| Only the first event has a `start_time` | That time anchors the day; every following event chains off it by duration, back-to-back. |
| Every event has a `start_time` | Identical to today's behavior — each event resolves independently against its own explicit range. |
| Mixed (e.g. an anchor partway through the list) | Events before the next anchor chain off the previous anchor; hitting a new anchor resets the chain from there, same as the two rows above but restarted mid-list. |

`Timetable.sorted_events()` is renamed in behavior (not necessarily name) to
preserve **list order**, not start-time order — sorting by start time no
longer makes sense once values can be `None`, and list order is already the
mechanism the config window's Move Up/Move Down buttons use. Saving no
longer re-sorts by start time.

## Core Changes

**`core/models.py`**
- `Event.start_time` becomes `time | None`.
- `Event.to_dict()`/`from_dict()` handle `None` (omit key or store `null`).
- `Event.end_time_seconds` (currently computed from `start_time` directly)
  is no longer meaningful on its own for unanchored events — effective-time
  computation moves to the scheduler (see below); this property is only
  used by the scheduler now, for anchored events.
- `Timetable.sorted_events()` returns events in list order, unchanged
  otherwise (no re-sort by time).

**`core/scheduler.py`**
- New internal helper computes each event's `(effective_start, effective_end)`
  in one pass, per the rule above, returning `None` for start/end on events
  with no effective start.
- `resolve(now, events)` operates over these effective times instead of raw
  `start_time`:
  - `RUNNING` / gap-`BEFORE_FIRST` logic is unchanged in shape, just sourced
    from effective times, and skips over events with no effective start
    entirely (they're invisible to wall-clock resolution).
  - New case: if **no** event in the whole list has an effective start,
    return a new `Resolution.mode == "AWAITING_START"` (index `None`).
  - `AFTER_LAST` still means "wall clock is past the last *anchored* event's
    chain end" — if the list ends in unanchored events, their chained
    effective end still counts (the chain has a defined end even without an
    explicit final anchor).

**`core/state_machine.py`**
- New `Mode.AWAITING_START`, handled in `tick()`'s wall-clock branch (mirrors
  `EMPTY` handling: no current event, no countdown).
- New `TimerEngine.start()` method: sets `current_index = 0`,
  `overridden = True`, `remaining_seconds = events[0].duration_seconds`,
  `mode = RUNNING` — mechanically identical to `skip_next()` from a
  no-current state, just named for discoverability and intent. Per the
  approved answer, it's only meant to be invoked when nothing is currently
  running; the engine itself doesn't need to reject calls while
  `RUNNING`/`PAUSED` (the config window disables the button instead — see
  below), but `start()` still overwrites playback unconditionally if called,
  same as `skip_next()` already does.
- `get_display_state()`: `AWAITING_START` renders like `EMPTY`/`BEFORE_FIRST`
  but with distinct text ("Standing by — press Start"), no countdown, and
  (if any event anywhere in the list has an effective start) still shows
  that next upcoming anchored event in the NEXT bar for visibility.

## UI Changes

**`ui/main_display.py`**
- New branch for `Mode.AWAITING_START`: current box shows "Standing by —
  press Start", clock shows `--:--`. If a future anchored event exists
  further down the list, the NEXT bar still shows it (a "first real
  checkpoint is at 14:00" hint), otherwise NEXT is hidden — mirrors how
  `BEFORE_FIRST` already surfaces the next event.

**`ui/config_window.py`**
- `EventEditDialog`: a checkbox ("Has start time") next to the `QTimeEdit`.
  Unchecked disables the time field (greyed out, matches standard Qt
  enabled/disabled styling already used elsewhere) and the saved `Event`
  gets `start_time=None`. Checked re-enables it and uses its value, exactly
  as today.
- Live Controls row gets a "Start" button next to the existing
  Pause/Resume/Skip/Adjust buttons, calling `engine.start()`. Enabled only
  when `engine.get_display_state().mode` is one of `EMPTY`,
  `AWAITING_START`, `AFTER_LAST` (nothing currently playing); disabled
  otherwise. The config window already re-renders on engine signal changes
  (per the existing shared-engine wiring), so this can piggyback on that
  same refresh to update enabled/disabled state live.

**`ui/event_table_model.py`**
- Start Time column shows a blank string (not "None"/an error) for events
  with `start_time is None`.

## Testing

- `core/test_scheduler.py`: new cases for the effective-time computation —
  no anchors at all (`AWAITING_START`), single leading anchor with the rest
  chained, a mid-list anchor resetting the chain, and confirm existing
  fully-timed cases are unaffected (regression coverage for the rename from
  start-time-sort to list-order).
- `core/test_state_machine.py`: `start()` behavior (jumps to event 0,
  overridden, full duration), `AWAITING_START` mode surfacing correctly in
  `get_display_state()`, and that auto-advance/chaining still works when
  events lack `start_time`.
- `test_ui_smoke.py`: config window's Start button enabled/disabled state
  across mode transitions; `EventEditDialog` checkbox toggling the time
  field and producing `start_time=None` when unchecked.

## Error Handling / Edge Cases

- Empty timetable: unchanged, still `Mode.EMPTY` (distinct from
  `AWAITING_START`, which implies "there are events, just none reachable by
  clock yet").
- All-unanchored timetable after the last event finishes (`AFTER_LAST`):
  pressing Start again is allowed (`AFTER_LAST` is in the enabled set) to
  restart the sequence, consistent with treating `AFTER_LAST` as "nothing
  currently running."
- Existing saved timetables (all events timed) round-trip identically — no
  migration needed since `start_time` was already a required field going to
  an optional one is backward compatible.
