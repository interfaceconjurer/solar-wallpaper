#!/usr/bin/env python3
"""
Switches macOS wallpaper between Tahoe Morning/Day/Evening/Night
with smooth crossfade transitions.

Transitions:
  night → morning:  sunrise (calculated daily)
  morning → day:    12:00
  day → evening:    19:00
  evening → night:  23:00

Usage:
  solar_wallpaper.py                  # Transition to the correct period for right now
  solar_wallpaper.py --hard-switch X  # Immediately switch to period X (no crossfade)
  solar_wallpaper.py --schedule       # Calculate sunrise, write launchd schedule
"""

import datetime
import json
import math
import os
import subprocess
import sys
import time
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
VIDEOS_DIR = os.path.expanduser(
    "~/Library/Application Support/com.apple.wallpaper/aerials/videos"
)
FRAMES_DIR = os.path.join(SCRIPT_DIR, "frames")
STATE_PATH = os.path.join(SCRIPT_DIR, ".last_period")
CROSSFADE_BIN = os.path.join(SCRIPT_DIR, "crossfade_overlay")
LAUNCHD_PLIST = os.path.expanduser(
    "~/Library/LaunchAgents/com.jwright.solar-wallpaper.plist"
)

PERIODS = ["morning", "day", "evening", "night"]
WALLPAPERS = {
    "morning": "B2FC91ED-6891-4DEB-85A1-268B2B4160B6",
    "day": "4C108785-A7BA-422E-9C79-B0129F1D5550",
    "evening": "52ACB9B8-75FC-4516-BC60-4550CFF3B661",
    "night": "CF6347E2-4F81-4410-8892-4830991B6C5A",
}

FADE_DURATION = 1800.0  # 30 minutes
CATCHUP_FADE_DURATION = 30.0  # 30 seconds for login/wake transitions


def get_location():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        if "latitude" in config and "longitude" in config:
            return config["latitude"], config["longitude"]

    try:
        req = urllib.request.Request(
            "https://ipapi.co/json/",
            headers={"User-Agent": "solar-wallpaper/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        lat, lon = data["latitude"], data["longitude"]
        with open(CONFIG_PATH, "w") as f:
            json.dump({"latitude": lat, "longitude": lon}, f, indent=2)
        return lat, lon
    except Exception as e:
        print(f"Could not determine location: {e}", file=sys.stderr)
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
    """Calculate civil twilight (solar elevation = -6°) for the given date.
    Returns a local datetime for when the sun crosses -6° on the way up."""
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

    if local_hour >= 23:
        return "night"
    if not sun_is_up:
        return "night"
    if local_hour < 12:
        return "morning"
    if local_hour < 19:
        return "day"
    return "evening"


def ensure_frame(period):
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
            "ffmpeg", "-y", "-ss", "0",
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


def run_overlay(from_period, to_period, duration):
    """Launch the overlay binary. The overlay writes the persistent wallpaper
    to to_period via NSWorkspace.setDesktopImageURL while it covers the screen,
    then crossfades and exits."""
    from_frame = ensure_frame(from_period)
    to_frame = ensure_frame(to_period)

    if not to_frame or not os.path.exists(CROSSFADE_BIN):
        print(
            f"Cannot transition: missing frame or overlay binary "
            f"(to_frame={to_frame}, bin={CROSSFADE_BIN})",
            file=sys.stderr,
        )
        return False

    # If we don't have a from-frame (first run), reuse the to-frame so the
    # overlay still launches and writes the persistent wallpaper.
    if not from_frame:
        from_frame = to_frame
        duration = 0.0

    ready_path = "/tmp/.solar_overlay_ready"
    try:
        os.remove(ready_path)
    except FileNotFoundError:
        pass

    subprocess.Popen([
        CROSSFADE_BIN,
        from_frame,
        to_frame,
        str(duration),
    ])

    for _ in range(50):
        if os.path.exists(ready_path):
            break
        time.sleep(0.1)

    save_last_period(to_period)
    return True


def hard_switch(period):
    """Set the wallpaper to period with no crossfade (zero-duration overlay
    so the persistent wallpaper still gets written via setDesktopImageURL)."""
    run_overlay(period, period, duration=0.0)


def write_schedule():
    """Calculate today's sunrise and write the launchd plist with all transition times."""
    lat, lon = get_location()
    sunrise = calculate_sunrise(lat, lon)
    sunrise_hour = sunrise.hour
    sunrise_minute = sunrise.minute

    print(f"Today's sunrise (civil twilight): {sunrise.strftime('%H:%M')}")
    print(f"Schedule:")
    print(f"  {sunrise_hour:02d}:{sunrise_minute:02d} → morning")
    print(f"  12:00 → day")
    print(f"  19:00 → evening")
    print(f"  23:00 → night")
    print(f"  03:00 → recalculate schedule")

    script_path = os.path.abspath(__file__)

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
        "StandardOutPath": os.path.join(SCRIPT_DIR, "solar_wallpaper.log"),
        "StandardErrorPath": os.path.join(SCRIPT_DIR, "solar_wallpaper.log"),
    }

    import plistlib
    with open(LAUNCHD_PLIST, "wb") as f:
        plistlib.dump(plist, f)

    # Reload via a detached process — unloading from within the running job
    # would kill this process before the load can execute.
    subprocess.Popen(
        ["/bin/sh", "-c",
         f"sleep 2 && launchctl unload '{LAUNCHD_PLIST}' 2>/dev/null; "
         f"launchctl load '{LAUNCHD_PLIST}'"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"\nLaunch agent updated (reloading in background).")


def main():
    if "--hard-switch" in sys.argv:
        idx = sys.argv.index("--hard-switch")
        if idx + 1 < len(sys.argv):
            period = sys.argv[idx + 1]
            if period in WALLPAPERS:
                hard_switch(period)
                print(f"Hard-switched to {period}.")
            else:
                print(f"Unknown period: {period}", file=sys.stderr)
                sys.exit(1)
        return

    if "--schedule" in sys.argv:
        write_schedule()
        return

    # At 3am, recalculate the schedule for today's sunrise
    now = datetime.datetime.now()
    if now.hour == 3 and now.minute < 5:
        write_schedule()
        return

    lat, lon = get_location()
    period = get_period(lat, lon)
    last_period = load_last_period()

    if last_period == period:
        print(f"Already showing {period}. No change needed.")
        return

    elev = solar_elevation(lat, lon)

    if not last_period:
        print(f"Switched to Tahoe {period.capitalize()} (solar elevation: {elev:.1f}°)")
        hard_switch(period)
        return

    steps = (PERIODS.index(period) - PERIODS.index(last_period)) % 4

    # Determine if we're at the transition moment or catching up late.
    if period == "morning":
        transition_time = calculate_sunrise(lat, lon)
    elif period == "day":
        transition_time = now.replace(hour=12, minute=0, second=0, microsecond=0)
    elif period == "evening":
        transition_time = now.replace(hour=19, minute=0, second=0, microsecond=0)
    else:
        transition_time = now.replace(hour=23, minute=0, second=0, microsecond=0)

    minutes_late = (now - transition_time).total_seconds() / 60.0

    if steps != 1 or minutes_late > 5:
        print(f"Catching up {last_period} → {period} ({minutes_late:.0f}min late, quick fade)")
        run_overlay(last_period, period, duration=CATCHUP_FADE_DURATION)
    else:
        print(f"Transitioning {last_period} → {period} (solar elevation: {elev:.1f}°)")
        run_overlay(last_period, period, duration=FADE_DURATION)


if __name__ == "__main__":
    main()
