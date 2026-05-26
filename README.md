# Solar Wallpaper

A macOS dynamic wallpaper system that automatically transitions between Lake Tahoe aerial wallpapers based on the sun's position in the sky. Instead of abrupt switches, it performs smooth 30-minute crossfade transitions using a Core Animation overlay at the desktop window level.

<p align="center">
  <img src="screenshots/transition-cycle.gif" alt="Transition cycle — morning, day, evening, night" />
</p>

## How It Works

A launch agent runs the script at specific transition times rather than polling. Each day, the schedule is:

| Time | Transition |
|------|-----------|
| 3:00am | Recalculates sunrise for the new day and updates the schedule |
| Sunrise | night → morning (calculated daily based on location) |
| 12:00pm | morning → day |
| 7:00pm | day → evening |
| 11:00pm | evening → night |

When a transition triggers:

1. A compiled Swift overlay appears at the desktop window level
2. The overlay crossfades between the current and target period over 30 minutes using GPU-accelerated Core Animation
3. At the midpoint, the actual macOS wallpaper asset is switched underneath
4. The overlay fades out, revealing the real wallpaper seamlessly

All four Tahoe videos share an identical slow camera pan — only the lighting differs. The transition extracts frames at the same timestamp (t=0) so the composition stays perfectly aligned during crossfade.

## Setup

### Prerequisites

- macOS with Tahoe wallpaper aerials downloaded (System Settings → Wallpaper → Tahoe)
- `ffmpeg` installed (`brew install ffmpeg`) for initial frame extraction
- Swift compiler (included with Xcode or Command Line Tools)

### Install

```bash
# Clone
git clone https://github.com/interfaceconjurer/solar-wallpaper.git ~/git-repos/solar-wallpaper
cd ~/git-repos/solar-wallpaper

# Compile the crossfade overlay
swiftc -O -o crossfade_overlay crossfade_overlay.swift -framework Cocoa -framework QuartzCore
swiftc -O -o crossfade_cycle crossfade_cycle.swift -framework Cocoa -framework QuartzCore

# Run once to extract frames and cache them
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

## Files

| File | Purpose |
|------|---------|
| `solar_wallpaper.py` | Main script — determines period, triggers transitions |
| `crossfade_overlay.swift` | Single-transition overlay (used in production) |
| `crossfade_cycle.swift` | Demo tool — cycles through all four periods continuously |
| `simulate_transition.py` | Development tool — generates MP4 previews of transitions |
| `frames/` | Cached t=0 PNG frames extracted from each video |
| `config.json` | Latitude/longitude (auto-generated) |
