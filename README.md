# Solar Wallpaper

A macOS dynamic wallpaper system that automatically transitions between Lake Tahoe aerial wallpapers based on the sun's position in the sky. Transitions are smooth real-time GPU crossfades: a borderless overlay window dissolves from the old period still to the new one at 60fps, then macOS's native `NSWorkspace.setDesktopImageURL` API persists the result.

<p align="center">
  <img src="screenshots/transition-cycle.png" alt="Transition cycle — morning, day, evening, night" />
</p>

<p align="center">
  <img src="screenshots/periods.png" alt="Morning, Day, Evening, Night" />
</p>

## How It Works

### Scheduled Transitions

A launch agent fires the script at each transition time:

| Time | Transition |
|------|-----------|
| 3:00am | Recalculates sunrise for the new day and updates the schedule |
| Sunrise | night → morning (calculated daily based on location) |
| 12:00pm | morning → day |
| 7:00pm | day → evening |
| 11:00pm | evening → night |

When a transition triggers, the script launches `crossfade_overlay`. The overlay covers the desktop with the *current* still (so its appearance is invisible), sets the real wallpaper to the *new* still underneath via `NSWorkspace.setDesktopImageURL`, then dissolves its own opacity 1→0 over 10 seconds. Because the wallpaper is written *before* the fade begins, macOS persists the correct image through sleep, login, and reboot even if the overlay is interrupted mid-fade. The overlay sits just above the desktop icons but below normal windows, so it never covers your apps.

### Wake / Lid-Open

When you open the laptop after it's been closed:

1. macOS shows the **previous wallpaper** (already persisted from the last `setDesktopImageURL` call)
2. The screen watcher daemon detects wake and triggers the script
3. The script calculates the correct current period and, if it changed while asleep, crossfades from the previous wallpaper to the current one

### Why This Approach

The overlay is self-contained and ordered to avoid the classic crossfade pitfalls:
- It shows the **current** still first, so the window appearing is visually invisible
- It writes the destination wallpaper **before** fading, so correctness never depends on the fade finishing — if the process is killed (e.g., sleep), macOS already has the right image
- The fade is a continuous 60fps Core Animation opacity dissolve, eliminating the visible ~3% steps of frame-by-frame blending

The script itself stays idempotent: it determines the correct period from wall-clock time and the sun's elevation, and only crossfades when the period has actually changed.

## Setup

### Prerequisites

- macOS with Tahoe wallpaper aerials downloaded (System Settings → Wallpaper → Tahoe)
- `ffmpeg` installed (`brew install ffmpeg`) for initial frame extraction
- Swift compiler (included with Xcode or Command Line Tools)
- Python 3 with Pillow and NumPy (`pip3 install Pillow numpy`)

### Install

```bash
# Clone
git clone https://github.com/interfaceconjurer/solar-wallpaper.git ~/git-repos/solar-wallpaper
cd ~/git-repos/solar-wallpaper

# Compile the wallpaper-setting binary and screen watcher
swiftc -O -o set_wallpaper set_wallpaper.swift -framework Cocoa
swiftc -O -o screen_watcher screen_watcher.swift -framework Cocoa

# Compile the crossfade overlay
swiftc -O -o crossfade_overlay crossfade_overlay.swift

# Extract base frames from the aerial videos (first run only)
python3 solar_wallpaper.py

# Calculate sunrise and install the launch agent schedule
python3 solar_wallpaper.py --schedule
```

### Configuration

Location is auto-detected on first run and cached in `config.json`. To set it manually:

```json
{
  "latitude": 38.9687,
  "longitude": -77.3411
}
```

### Commands

```bash
# Normal run — transitions if the period has changed
python3 solar_wallpaper.py

# Force a specific period immediately
python3 solar_wallpaper.py --hard-switch morning

# Recalculate sunrise and update the launchd schedule
python3 solar_wallpaper.py --schedule
```

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│ launchd (com.jwright.solar-wallpaper)                     │
│ Fires at: sunrise, 12:00, 19:00, 23:00, 03:00           │
│ RunAtLoad: yes                                           │
└────────────────────────┬─────────────────────────────────┘
                         │ launches
                         ▼
┌──────────────────────────────────────────────────────────┐
│ solar_wallpaper.py                                        │
│ • Determines current period from sun elevation / clock    │
│ • Reads .last_period to know what's currently displayed   │
│ • Crossfades old→new when the period changed              │
└────────────────────────┬─────────────────────────────────┘
              subprocess  │  (from, to, duration)
                         ▼
┌──────────────────────────────────────────────────────────┐
│ crossfade_overlay (Swift GUI binary)                      │
│ • Covers desktop with the FROM still (invisible appear)   │
│ • Sets wallpaper to TO still via setDesktopImageURL       │
│ • Dissolves window opacity 1→0 over 10s at 60fps          │
│ • macOS persists the TO still through sleep/login/reboot  │
└──────────────────────────────────────────────────────────┘

( set_wallpaper is still used for hard switches and hotplug )

┌──────────────────────────────────────────────────────────┐
│ screen_watcher (Swift daemon, launchd KeepAlive)          │
│ • Listens: didWakeNotification, screenIsUnlocked,         │
│   didChangeScreenParametersNotification                   │
│ • On wake: triggers solar_wallpaper.py (handles catch-up) │
│ • On display connect: applies current wallpaper directly  │
└──────────────────────────────────────────────────────────┘
```

## Files

| File | Purpose |
|------|---------|
| `solar_wallpaper.py` | Main script — determines period, runs crossfades |
| `crossfade_overlay.swift` | GPU crossfade overlay window (the transition) |
| `set_wallpaper.swift` | Minimal binary to call `setDesktopImageURL` (hard switch / hotplug) |
| `screen_watcher.swift` | Wake/display-connect daemon |
| `frames/` | Base PNG stills (extracted ~30s into each aerial video) |
| `config.json` | Latitude/longitude (auto-generated) |
| `.last_period` | Current period state file |
