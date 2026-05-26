# Solar Wallpaper

A macOS dynamic wallpaper system that automatically transitions between Lake Tahoe aerial wallpapers based on the sun's position in the sky. Instead of abrupt switches, it performs smooth 30-minute crossfade transitions using a Core Animation overlay at the desktop window level.

<p align="center">
  <img src="screenshots/transition-cycle.gif" alt="Transition cycle — morning, day, evening, night" />
</p>

## How It Works

1. A launch agent runs the script every 5 minutes
2. Solar elevation is calculated for your location to determine the current period (morning, day, evening, night)
3. If the wallpaper needs to change, a compiled Swift overlay appears at the desktop window level
4. The overlay crossfades between the current and target period over 30 minutes using GPU-accelerated Core Animation
5. At the midpoint of the fade, the actual macOS wallpaper asset is switched underneath
6. The overlay fades out, revealing the real wallpaper seamlessly

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

# Install launch agent
cp com.jwright.solar-wallpaper.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.jwright.solar-wallpaper.plist
```

### Configuration

Location is auto-detected on first run and cached in `config.json`. To set it manually:

```json
{
  "latitude": 38.9687,
  "longitude": -77.3411
}
```

### Period Schedule

| Period  | Condition |
|---------|-----------|
| Morning | Sunrise (solar elevation ≥ -6°) until noon |
| Day     | Noon until 7pm |
| Evening | 7pm until 11pm |
| Night   | 11pm until sunrise |

## Files

| File | Purpose |
|------|---------|
| `solar_wallpaper.py` | Main script — determines period, triggers transitions |
| `crossfade_overlay.swift` | Single-transition overlay (used in production) |
| `crossfade_cycle.swift` | Demo tool — cycles through all four periods continuously |
| `simulate_transition.py` | Development tool — generates MP4 previews of transitions |
| `frames/` | Cached t=0 PNG frames extracted from each video |
| `config.json` | Latitude/longitude (auto-generated) |
