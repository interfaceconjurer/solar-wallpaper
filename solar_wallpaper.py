#!/usr/bin/env python3
"""
Switches macOS wallpaper between Tahoe Morning/Day/Evening/Night
with a smooth GPU crossfade between period stills.

Transitions are handled by `crossfade_overlay`, a tiny Swift GUI process that
covers the desktop with the *from* still, sets the real wallpaper to the *to*
still underneath, then dissolves its window opacity 1→0 at 60fps. This gives a
genuinely smooth fade instead of the visible ~3% jumps of frame stepping.

Transitions:
  night → morning:  sunrise (calculated daily)
  morning → day:    12:00
  day → evening:    19:00
  evening → night:  23:00

Usage:
  solar_wallpaper.py                  # Crossfade to the correct period
  solar_wallpaper.py --hard-switch X  # Immediately switch to period X
  solar_wallpaper.py --schedule       # Calculate sunrise, write launchd schedule
"""

import datetime
import json
import math
import os
import subprocess
import sys
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
VIDEOS_DIR = os.path.expanduser(
    "~/Library/Application Support/com.apple.wallpaper/aerials/videos"
)
FRAMES_DIR = os.path.join(SCRIPT_DIR, "frames")
STATE_PATH = os.path.join(SCRIPT_DIR, ".last_period")
SET_WALLPAPER_BIN = os.path.join(SCRIPT_DIR, "set_wallpaper")
CROSSFADE_BIN = os.path.join(SCRIPT_DIR, "crossfade_overlay")
LAUNCHD_PLIST = os.path.expanduser(
    "~/Library/LaunchAgents/com.jwright.solar-wallpaper.plist"
)
LOG_PATH = os.path.join(SCRIPT_DIR, "solar_wallpaper.log")

PERIODS = ["morning", "day", "evening", "night"]
WALLPAPERS = {
    "morning": "B2FC91ED-6891-4DEB-85A1-268B2B4160B6",
    "day": "4C108785-A7BA-422E-9C79-B0129F1D5550",
    "evening": "52ACB9B8-75FC-4516-BC60-4550CFF3B661",
    "night": "CF6347E2-4F81-4410-8892-4830991B6C5A",
}

# Smooth crossfade duration (seconds) for both scheduled and wake transitions.
CROSSFADE_DURATION = 10.0

# Seconds into each aerial video to extract the base still. At ~30s the
# foreground rock has panned fully into the bottom-right corner, and all
# four period videos line up at this offset.
FRAME_EXTRACT_OFFSET = 30

# Lock file to prevent multiple instances from fighting
LOCK_PATH = os.path.join(SCRIPT_DIR, ".solar_lock")


def log(msg):
    """Append to log with timestamp."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    try:
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def acquire_lock():
    """Simple PID-based lock. Returns True if we got it."""
    pid = os.getpid()
    if os.path.exists(LOCK_PATH):
        try:
            with open(LOCK_PATH) as f:
                old_pid = int(f.read().strip())
            # Check if the old process is still alive
            try:
                os.kill(old_pid, 0)
                # Process is alive — we lose
                return False
            except OSError:
                # Process is dead — stale lock
                pass
        except (ValueError, IOError):
            pass
    with open(LOCK_PATH, "w") as f:
        f.write(str(pid))
    return True


def release_lock():
    try:
        os.remove(LOCK_PATH)
    except FileNotFoundError:
        pass


def _read_cached_location():
    """Return (lat, lon) from config.json if present, else None."""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                config = json.load(f)
            if "latitude" in config and "longitude" in config:
                return config["latitude"], config["longitude"]
        except Exception:
            pass
    return None


def _detect_location_via_ip():
    """Detect (lat, lon) from IP geolocation. Raises on failure."""
    req = urllib.request.Request(
        "https://ipapi.co/json/",
        headers={"User-Agent": "solar-wallpaper/1.0"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read())
    return data["latitude"], data["longitude"]


def get_location(refresh=False):
    """Determine the current location.

    config.json is treated as a *cache*, not a hardcoded setting. By default
    (normal transitions and wake events) the cache is used so transitions are
    fast and work offline. When refresh=True — done during the daily 3am
    schedule recalc — the location is re-detected via IP geolocation so the
    wallpaper follows you as you travel, and the cache is updated. If detection
    fails (offline), the cached location is used as a fallback.
    """
    cached = _read_cached_location()

    if cached is not None and not refresh:
        return cached

    try:
        lat, lon = _detect_location_via_ip()
        with open(CONFIG_PATH, "w") as f:
            json.dump({"latitude": lat, "longitude": lon}, f, indent=2)
        if cached is None:
            log(f"Location detected via IP: lat={lat:.4f}, lon={lon:.4f}")
        elif (lat, lon) != cached:
            log(f"Location changed via IP: lat={lat:.4f}, lon={lon:.4f} "
                f"(was {cached[0]:.4f}, {cached[1]:.4f})")
        return lat, lon
    except Exception as e:
        if cached is not None:
            log(f"Location refresh failed ({e}); using cached location.")
            return cached
        log(f"Could not determine location: {e}")
        sys.exit(1)


def solar_elevation(lat, lon, dt=None):
    if dt is None:
        dt = datetime.datetime.now(datetime.timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)

    n = (dt - datetime.datetime(2000, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)).total_seconds() / 86400.0

    mean_longitude = (280.460 + 0.9856474 * n) % 360
    mean_anomaly = math.radians((357.528 + 0.9856003 * n) % 360)
    ecliptic_longitude = math.radians(
        mean_longitude + 1.915 * math.sin(mean_anomaly) + 0.020 * math.sin(2 * mean_anomaly)
    )
    obliquity = math.radians(23.439 - 0.0000004 * n)

    declination = math.asin(math.sin(obliquity) * math.sin(ecliptic_longitude))
    ra = math.atan2(
        math.sin(ecliptic_longitude) * math.cos(obliquity),
        math.cos(ecliptic_longitude)
    )

    gmst = (18.697374558 + 24.06570982441908 * n) % 24
    lst = (gmst + lon / 15.0) % 24
    hour_angle = math.radians(lst * 15.0) - ra

    lat_rad = math.radians(lat)
    elevation = math.asin(
        math.sin(lat_rad) * math.sin(declination)
        + math.cos(lat_rad) * math.cos(declination) * math.cos(hour_angle)
    )
    return math.degrees(elevation)


def calculate_sunrise(lat, lon, date=None):
    """Calculate civil twilight (solar elevation = -6°) for the given date."""
    if date is None:
        date = datetime.date.today()

    local_midnight = datetime.datetime(date.year, date.month, date.day, 0, 0, 0)
    tz_offset = datetime.datetime.now() - datetime.datetime.utcnow()

    prev_elev = None
    for minute in range(0, 720):
        local_time = local_midnight + datetime.timedelta(minutes=minute)
        utc_time = (local_time - tz_offset).replace(tzinfo=datetime.timezone.utc)
        elev = solar_elevation(lat, lon, utc_time)

        if prev_elev is not None and prev_elev < -6 and elev >= -6:
            fraction = (-6 - prev_elev) / (elev - prev_elev)
            sunrise_time = local_midnight + datetime.timedelta(minutes=minute - 1 + fraction)
            return sunrise_time

        prev_elev = elev

    return local_midnight.replace(hour=6)


def get_period(lat, lon):
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    local_hour = datetime.datetime.now().hour
    elev = solar_elevation(lat, lon, now_utc)
    sun_is_up = elev >= -6

    # Night runs from 23:00 until sunrise. Boundaries match the launchd
    # schedule (sunrise→morning, 12:00→day, 19:00→evening, 23:00→night).
    if local_hour >= 23:
        return "night"
    if local_hour < 12:
        # Morning only once the sun has actually risen (civil twilight);
        # before that it is still night.
        return "morning" if sun_is_up else "night"
    if local_hour < 19:
        return "day"
    # 19:00–23:00 is always evening, even after the sun has set for the day.
    # (Previously a blanket `not sun_is_up` check forced night at dusk,
    # switching to night ~2 hours early in summer.)
    return "evening"


def ensure_frame(period):
    """Return the base still for a period, extracting it from the aerial
    video at FRAME_EXTRACT_OFFSET seconds if it doesn't already exist."""
    os.makedirs(FRAMES_DIR, exist_ok=True)
    frame_path = os.path.join(FRAMES_DIR, f"{period}.png")

    if os.path.exists(frame_path):
        return frame_path

    uuid = WALLPAPERS[period]
    video_path = os.path.join(VIDEOS_DIR, f"{uuid}.mov")

    if not os.path.exists(video_path):
        return None

    subprocess.run(
        [
            "ffmpeg", "-y", "-ss", str(FRAME_EXTRACT_OFFSET),
            "-i", video_path,
            "-frames:v", "1", "-q:v", "2",
            frame_path,
        ],
        capture_output=True,
        check=True,
    )
    return frame_path


def load_last_period():
    if not os.path.exists(STATE_PATH):
        return None
    try:
        with open(STATE_PATH) as f:
            value = f.read().strip()
        return value if value in WALLPAPERS else None
    except Exception:
        return None


def save_last_period(period):
    with open(STATE_PATH, "w") as f:
        f.write(period)


def set_wallpaper(image_path):
    """Set the desktop wallpaper on all screens via the set_wallpaper binary."""
    if not os.path.exists(SET_WALLPAPER_BIN):
        log(f"Error: set_wallpaper binary not found at {SET_WALLPAPER_BIN}")
        return False
    result = subprocess.run(
        [SET_WALLPAPER_BIN, image_path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log(f"set_wallpaper failed: {result.stderr.strip()}")
        return False
    return True


def crossfade(from_period, to_period, duration):
    """Smoothly dissolve from one period still to another using the
    crossfade_overlay binary. The overlay sets the destination wallpaper
    itself, so persistence is handled by macOS once it exits."""
    from_frame = ensure_frame(from_period)
    to_frame = ensure_frame(to_period)

    # Fall back to a hard switch if anything required is missing.
    if not from_frame or not to_frame or not os.path.exists(CROSSFADE_BIN):
        log(f"Crossfade prerequisites missing — hard switching to {to_period}")
        if to_frame:
            set_wallpaper(to_frame)
        save_last_period(to_period)
        return

    result = subprocess.run(
        [CROSSFADE_BIN, from_frame, to_frame, str(duration)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log(f"crossfade_overlay failed: {result.stderr.strip()} — hard switching")
        set_wallpaper(to_frame)
    save_last_period(to_period)


def hard_switch(period):
    """Immediately set wallpaper to a period with no transition."""
    frame = ensure_frame(period)
    if frame:
        set_wallpaper(frame)
    save_last_period(period)


def write_schedule():
    """Calculate today's sunrise and write the launchd plist."""
    # Re-detect location during the daily recalc so the schedule follows you
    # as you travel; falls back to the cached location if offline.
    lat, lon = get_location(refresh=True)
    sunrise = calculate_sunrise(lat, lon)
    if sunrise.second > 0 or sunrise.microsecond > 0:
        sunrise += datetime.timedelta(minutes=1)
        sunrise = sunrise.replace(second=0, microsecond=0)
    sunrise_hour = sunrise.hour
    sunrise_minute = sunrise.minute

    log(f"Today's sunrise (civil twilight): {sunrise.strftime('%H:%M')}")
    log(f"Schedule: {sunrise_hour:02d}:{sunrise_minute:02d}→morning, "
        f"12:00→day, 19:00→evening, 23:00→night, 03:00→recalculate")

    script_path = os.path.abspath(__file__)

    import plistlib
    plist = {
        "Label": "com.jwright.solar-wallpaper",
        "ProgramArguments": ["/usr/bin/python3", script_path],
        "StartCalendarInterval": [
            {"Hour": sunrise_hour, "Minute": sunrise_minute},
            {"Hour": 12, "Minute": 0},
            {"Hour": 19, "Minute": 0},
            {"Hour": 23, "Minute": 0},
            {"Hour": 3, "Minute": 0},
        ],
        "RunAtLoad": True,
        "StandardOutPath": LOG_PATH,
        "StandardErrorPath": LOG_PATH,
    }

    with open(LAUNCHD_PLIST, "wb") as f:
        plistlib.dump(plist, f)

    subprocess.Popen(
        ["/bin/sh", "-c",
         f"sleep 2 && launchctl unload '{LAUNCHD_PLIST}' 2>/dev/null; "
         f"launchctl load '{LAUNCHD_PLIST}'"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log("Launch agent updated (reloading in background).")


def main():
    # --hard-switch: immediate jump to a period
    if "--hard-switch" in sys.argv:
        idx = sys.argv.index("--hard-switch")
        if idx + 1 < len(sys.argv):
            period = sys.argv[idx + 1]
            if period in WALLPAPERS:
                hard_switch(period)
                log(f"Hard-switched to {period}.")
            else:
                log(f"Unknown period: {period}")
                sys.exit(1)
        return

    # --schedule: just write the schedule and exit
    if "--schedule" in sys.argv:
        write_schedule()
        return

    # At 3am, recalculate the schedule — but guard against the RunAtLoad loop.
    # Only do this ONCE: check if the schedule was already written today.
    now = datetime.datetime.now()
    if now.hour == 3 and now.minute < 5:
        schedule_marker = os.path.join(SCRIPT_DIR, ".schedule_date")
        today_str = now.strftime("%Y-%m-%d")
        last_schedule = ""
        if os.path.exists(schedule_marker):
            with open(schedule_marker) as f:
                last_schedule = f.read().strip()
        if last_schedule != today_str:
            with open(schedule_marker, "w") as f:
                f.write(today_str)
            write_schedule()
        return

    # Acquire lock — only one instance should be running the crossfade
    if not acquire_lock():
        log("Another instance is running. Exiting.")
        return

    try:
        _do_transition()
    finally:
        release_lock()


def _do_transition():
    lat, lon = get_location()
    target_period = get_period(lat, lon)
    last_period = load_last_period()

    # Already showing the correct period — nothing to do.
    if last_period == target_period:
        return

    # First run — no previous state, so just set the correct image.
    if not last_period:
        log(f"First run — setting wallpaper to {target_period}")
        hard_switch(target_period)
        return

    log(f"Crossfade {last_period}→{target_period} ({CROSSFADE_DURATION:.0f}s)")
    crossfade(last_period, target_period, CROSSFADE_DURATION)


if __name__ == "__main__":
    main()
