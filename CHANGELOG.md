# Changelog & Debug Log

Ongoing record of changes, known issues, and debugging sessions for the solar wallpaper system.

## Architecture

The system has two cooperating parts:

1. **`solar_wallpaper.py`** — Determines the correct period, launches the overlay or hard-switches.
2. **`crossfade_overlay` (Swift binary)** — GUI process that displays a fullscreen crossfade on all screens. Fires a mid_command (hard_switch) at the halfway point.

The wallpaper only actually changes when the overlay's mid_command fires. If the overlay process dies before reaching the midpoint, the wallpaper stays on the old image.

**Scheduling:** A `launchd` agent (`com.jwright.solar-wallpaper`) fires the script at sunrise, 12:00, 19:00, 23:00, and 03:00. `RunAtLoad` triggers on login. At 3am the script recalculates sunrise for the new day and rewrites the schedule.

## Known Issues & Fixes

### Overlay killed by sleep (fixed 2026-05-27)

**Problem:** Laptop sleeps during a 30-minute crossfade → overlay process dies → mid_command never fires → wallpaper stuck on old period.

**Fix:** Added catch-up logic in `main()`. If the current wallpaper is more than 1 step behind the target period (e.g., day→night = 2 steps), it hard-switches immediately without an overlay. This handles waking from sleep when multiple transitions were missed.

**Limitation:** If the laptop sleeps during the *single* expected transition (e.g., night→morning), the overlay dies and the wallpaper stays on night. The catch-up logic only triggers when 2+ steps are missed. This is a still-open edge case as of 2026-05-29 — see "Current Investigation" below.

### Launch agent unloading itself (fixed 2026-05-27)

**Problem:** At 3am, `write_schedule()` called `launchctl unload` on its own agent, killing the script before `launchctl load` could run. Agent stayed unloaded until next login.

**Fix:** Spawn a detached shell (`sleep 2 && launchctl unload; launchctl load`) so the script exits cleanly before the reload happens.

### Multi-monitor abrupt switch (fixed 2026-05-28)

**Problem:** Overlay only created a window on `NSScreen.main`. Second display had no overlay, so the mid_command hard_switch appeared as an abrupt snap on that screen.

**Fix:** Iterate `NSScreen.screens` and create a window + layer pair for each connected display.

### Early eager hard_switch experiment (reverted 2026-05-28)

**Problem:** Tried moving `hard_switch` to run *before* launching the overlay (so sleep couldn't prevent the switch). This caused an abrupt wallpaper change visible before the overlay could cover it.

**Reverted:** Overlay must show the old image first, then crossfade, with the real wallpaper switching underneath at the midpoint. The catch-up logic handles the sleep case instead.

### Single-step sleep failure (fixed 2026-05-29)

**Problem:** Laptop sleeps during a single-step transition (e.g., night→morning). Overlay dies, mid_command never fires, wallpaper stuck. The multi-step catch-up logic didn't help because night→morning is only 1 step.

**Attempted fix (failed):** Hard_switch before overlay with 1s delay. The `killall WallpaperAgent` causes a visible snap even with the overlay on screen.

**Working fix:** Time-based catch-up. Compare current time to the expected transition time for the target period. If more than 5 minutes late, hard_switch without overlay. Only launch the overlay if the script fires within the 5-minute window around the transition time (i.e., the scheduled trigger fired on time and the machine was awake).

**Result:** `RunAtLoad` on login correctly detects it's hours past sunrise and hard-switches immediately. Normal scheduled triggers still get the smooth crossfade.

## Version History

| Date | Change |
|------|--------|
| 2026-05-26 | Initial crossfade system — Swift overlay, t=0 frame extraction, launchd scheduling |
| 2026-05-27 | Fix sleep catch-up (multi-step), fix agent self-unload |
| 2026-05-28 | Multi-monitor support, revert eager hard_switch |
| 2026-05-29 | Time-based catch-up: hard_switch if >5min past transition time |
