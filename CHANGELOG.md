# Changelog & Debug Log

Ongoing record of changes, known issues, and debugging sessions for the solar wallpaper system.

## Architecture

The system has two cooperating parts:

1. **`solar_wallpaper.py`** — Scheduler. Determines the correct period and launches the overlay binary with from/to frames and a duration.
2. **`crossfade_overlay` (Swift binary)** — Transient GUI process that:
   1. Covers every display with the *from* frame.
   2. Calls `NSWorkspace.setDesktopImageURL` for each screen with the *to* frame, writing the persistent wallpaper while the overlay hides the change.
   3. Crossfades from → to over the requested duration.
   4. Fades the overlay window out and exits.

3. **`screen_watcher` (Swift binary)** — Persistent daemon that listens for `NSApplication.didChangeScreenParametersNotification`. When a new display is connected, it reads `.last_period` and re-applies the wallpaper to all screens via `setDesktopImageURL`.

**Scheduling:** A single `launchd` agent (`com.jwright.solar-wallpaper`) fires the script at sunrise, 12:00, 19:00, 23:00, and 03:00. `RunAtLoad` triggers on login. At 3am the script recalculates sunrise for the new day and rewrites the schedule.

**Display hotplug:** A second `launchd` agent (`com.jwright.solar-wallpaper-watcher`) keeps `screen_watcher` alive. It only acts when the screen count *increases* — applying the current period's wallpaper to all screens so newly connected displays don't show a stale image.

**Persistence:** macOS itself owns wallpaper persistence — `setDesktopImageURL` writes through to the wallpaper config, so the correct wallpaper survives login, sleep/wake, and reboot natively. No `Index.plist` mutation, no `killall WallpaperAgent`, no wake watcher.

## Known Issues & Fixes

### Secondary display stuck on stale wallpaper after hotplug (fixed 2026-06-07)

**Problem:** Connecting an external display after a transition already fired left the new screen showing whatever wallpaper macOS last remembered for it (e.g., daytime image at night). `setDesktopImageURL` only runs during transitions, so newly connected displays were never updated until the next scheduled period change.

**Fix:** Added `screen_watcher.swift` — a lightweight persistent daemon that observes `didChangeScreenParametersNotification`. When the screen count increases (display connected), it reads `.last_period` and calls `setDesktopImageURL` for all screens. Managed by `com.jwright.solar-wallpaper-watcher` launchd agent with `KeepAlive`.

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

**Partial fix:** Time-based catch-up. If more than 5 minutes past the expected transition time, hard_switch without overlay. However, `launchd` can fire missed jobs immediately on wake — so the script might think it's "on time" and launch the overlay, which then dies anyway.

**Final fix (2026-05-29):** Decouple the plist write from the overlay entirely. `set_wallpaper_plist()` writes the target wallpaper immediately in the Python script before launching the overlay. The overlay's mid_command is now just `killall WallpaperAgent` (to refresh the display at the right moment). If the overlay dies, the plist is already correct — WallpaperAgent will show the new wallpaper on its next restart (login, wake, etc.). The time-based catch-up still hard_switches for the instant-correction case.

### Architectural reset — single overlay writes via NSWorkspace (2026-06-06)

**Symptom:** After login, user saw morning wallpaper when the period was day. Walked away, came back to a black wallpaper.

**Investigation:** Three parallel agents (architecture critique, forensic bug hunt, macOS API research) converged on the same diagnosis. Direct evidence collected from the live `Index.plist`:
- `.last_period` file said `day`. Daemon's in-memory state said `day`. Daemon log showed a successful `morning → day` crossfade. But `Index.plist` `AllSpacesAndDisplays.Linked` aerial assetID was still pointing at the *night* UUID — last written 2026-06-04, two days stale.
- `Index.plist` `SystemDefault` had been silently corrupted: provider type rewritten from `com.apple.wallpaper.choice.aerials` to `com.apple.wallpaper.choice.image`, pointing at `frames/day.png`. The aerials metadata (shuffle, dark/light pairing) was destroyed.

**Two distinct root causes:**

1. **Plist drift under the daemon path.** When the daemon was alive, `solar_wallpaper.py`'s `crossfade_transition` called `signal_daemon()` and *returned immediately* — never running `hard_switch()`. The daemon's `switchUnderlyingWallpaper` only ran `osascript ... set picture to ...`. Neither path updated the persistent wallpaper config. WallpaperAgent reads the stale plist on every login → wrong period.

2. **`rebuildWindows` race against active crossfade.** Daemon's `displayConfigChanged` handler called `rebuildWindows` without coordinating with the in-flight `asyncAfter` crossfade-cleanup block. New windows had no sublayers; their `backgroundColor = .black, isOpaque = true` was visible. → black wallpaper.

**Meta-pattern:** The system had accumulated *six sources of truth* for "what period is showing" (`Index.plist` aerial assetID, `Index.plist` Desktop URL, `.last_period`, `.daemon_pid`, daemon's in-memory `currentPeriod`, WallpaperAgent's cache) with three control planes (launchd / daemon's own observers / SIGUSR1) and two languages independently computing the period. Every prior fix tightened one edge of this graph and ignored the others; the regression was always already present in the fix.

**Fix:** Architectural reset to a single source of truth. `NSWorkspace.setDesktopImageURL` is now the *only* writer of persistent wallpaper state, called by the overlay binary while the overlay hides the change. macOS persists across login/sleep/wake natively because we're using its own API.

**Removed:**
- `solar_daemon.swift` and binary, `wake_watcher.swift` and binary, both launchd plists.
- All `Index.plist` mutation (`set_wallpaper_plist`).
- All AppleScript `set picture to` calls (corrupted `SystemDefault` provider type).
- The SIGUSR1 path, `signal_daemon`, `--install` command, `.daemon_pid` file.
- The fallback overlay-launch branch (now the only branch).

**Added:**
- `applyPersistentWallpaper()` in `crossfade_overlay.swift` — calls `NSWorkspace.setDesktopImageURL(toURL, for: screen, options: [:])` for each screen, immediately after the ready signal fires and before the crossfade animation begins.
- `hard_switch(period)` in Python now calls the overlay with `from == to` and `duration == 0`, so persistent state is always written by the same code path.

**Tradeoff accepted:** Wallpapers are now static PNGs (the t=0 frame) rather than the moving aerial videos. Lost the in-period slow camera pan; kept the period crossfade. Was already happening implicitly because `osascript` had been corrupting `SystemDefault.Desktop` to image-provider for a while.

### Persistent daemon replaces transient overlay (2026-06-02)

**Problem:** Even with the overlay reduced to a purely visual role, every transition still spawned a fresh GUI process that was vulnerable to sleep, wake, and display reconfiguration. Wake transitions in particular were a chain of fragile launches: scheduler → overlay → hope it survives long enough to crossfade.

**Fix:** Introduced `solar_daemon` (Swift), a single always-running GUI process that:
1. Holds a fullscreen overlay window on every display, layered just above the desktop icons.
2. Listens for `SIGUSR1` from the scheduler and crossfades via Core Animation in-process.
3. Registers for `IORegisterForSystemPower`, `NSWorkspace.didWakeNotification`, screen-unlock, and display-config notifications — handling wake/unlock without any external trigger.
4. Writes its PID to `.daemon_pid` so the Python script can signal it.

`solar_wallpaper.py` now sends `SIGUSR1` to the daemon for crossfades and only falls back to the transient `crossfade_overlay` binary if no daemon is running. The hard-switch path also drops `killall WallpaperAgent` in favor of `osascript ... set picture to ...`, which avoids the brief flash that `killall` produced.

The old `wake_watcher` agent is now redundant; `--install` unloads it automatically.

### Overlay mid_command still unreliable (fixed 2026-06-01)

**Problem:** Despite plist-first approach, the wallpaper still wasn't switching after sleep. Two issues:
1. State file corruption: `echo -n` on macOS `/bin/sh` writes the literal `-n` flag into the file, making the state unreadable.
2. `killall WallpaperAgent` in the overlay's mid_command never fired — overlay dies before midpoint during sleep/wake.

**Root cause:** The overlay (a 30-minute or 30-second GUI process) was still responsible for killing WallpaperAgent. Any process death before midpoint meant the wallpaper plist was correct but never visually applied.

**Final fix:** Remove ALL responsibility from the overlay. The Python script now:
1. Launches the overlay (covers desktop with "from" image)
2. Waits 0.5s for overlay to appear
3. Runs `hard_switch()` underneath (writes plist + kills WallpaperAgent + writes state file)

The overlay has zero mid_command — it just crossfades visually and exits. If it dies at any point, the wallpaper is already correct because `hard_switch` completed in the Python process before it exited.

## Version History

| Date | Change |
|------|--------|
| 2026-05-26 | Initial crossfade system — Swift overlay, t=0 frame extraction, launchd scheduling |
| 2026-05-27 | Fix sleep catch-up (multi-step), fix agent self-unload |
| 2026-05-28 | Multi-monitor support, revert eager hard_switch |
| 2026-05-29 | Time-based catch-up + plist-first guarantee: overlay is now purely visual |
| 2026-05-30 | Wake watcher + state file for reliable wake transitions |
| 2026-06-01 | Remove overlay mid_command entirely — Python does all switching in-process |
| 2026-06-02 | Persistent `solar_daemon` replaces transient overlay; osascript switch eliminates flash |
| 2026-06-06 | Architectural reset: delete daemon, `NSWorkspace.setDesktopImageURL` is sole writer, macOS handles persistence natively |
