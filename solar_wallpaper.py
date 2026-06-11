#!/usr/bin/env python3
"""
Switches macOS wallpaper between Tahoe Morning/Day/Evening/Night
with smooth transitions via pre-blended frame stepping.

Instead of a fragile overlay process, transitions step through pre-rendered
intermediate frames using setDesktopImageURL. Each step is ~3% opacity change
— imperceptible individually, smooth in aggregate.

Transitions:
  night → morning:  sunrise (calculated daily)
  morning → day:    12:00
  day → evening:    19:00
  evening → night:  23:00

Usage:
  solar_wallpaper.py                  # Transition to the correct period
  solar_wallpaper.py --hard-switch X  # Immediately switch to period X
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
TRANSITIONS_DIR = os.path.join(SCRIPT_DIR, "transitions")
STATE_PATH = os.path.join(SCRIPT_DIR, ".last_period")
PROGRESS_PATH = os.path.join(SCRIPT_DIR, ".transition_progress")
SET_WALLPAPER_BIN = os.path.join(SCRIPT_DIR, "set_wallpaper")
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

TRANSITION_STEPS = 30      # intermediate frames per transition
TRANSITION_DURATION = 1800  # 30 minutes for scheduled transitions
CATCHUP_DURATION = 5.0      # 5 seconds for wake/catch-up transitions

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

    if local_hour >= 23:
        return "night"
    if not sun_is_up:
        return "night"
    if local_hour < 12:
        return "morning"
    if local_hour < 19:
        return "day"
    return "evening"


def get_transition_time(period, lat, lon):
    """Get the datetime when a transition TO this period should start."""
    now = datetime.datetime.now()
    if period == "morning":
        return calculate_sunrise(lat, lon)
    elif period == "day":
        return now.replace(hour=12, minute=0, second=0, microsecond=0)
    elif period == "evening":
        return now.replace(hour=19, minute=0, second=0, microsecond=0)
    else:  # night
        return now.replace(hour=23, minute=0, second=0, microsecond=0)


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


def save_progress(from_period, to_period, step, start_time):
    """Save transition progress so we can resume after wake."""
    data = {
        "from": from_period,
        "to": to_period,
        "step": step,
        "start_time": start_time.isoformat(),
    }
    with open(PROGRESS_PATH, "w") as f:
        json.dump(data, f)


def load_progress():
    """Load in-progress transition state."""
    if not os.path.exists(PROGRESS_PATH):
        return None
    try:
        with open(PROGRESS_PATH) as f:
            data = json.load(f)
        data["start_time"] = datetime.datetime.fromisoformat(data["start_time"])
        return data
    except Exception:
        return None


def clear_progress():
    try:
        os.remove(PROGRESS_PATH)
    except FileNotFoundError:
        pass


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


def get_transition_frame(from_period, to_period, step):
    """Get the path to a specific transition frame.
    step=0 → from.png, step=TRANSITION_STEPS+1 → to.png,
    step=1..TRANSITION_STEPS → intermediate frame."""
    if step <= 0:
        return os.path.join(FRAMES_DIR, f"{from_period}.png")
    if step > TRANSITION_STEPS:
        return os.path.join(FRAMES_DIR, f"{to_period}.png")
    # Intermediate frames are 00-indexed: step 1 → 00.jpg, step 30 → 29.jpg
    dir_name = f"{from_period}_to_{to_period}"
    frame_name = f"{step - 1:02d}.jpg"
    return os.path.join(TRANSITIONS_DIR, dir_name, frame_name)


def transition_frames_exist(from_period, to_period):
    """Check if pre-rendered transition frames exist for this pair."""
    dir_name = f"{from_period}_to_{to_period}"
    dir_path = os.path.join(TRANSITIONS_DIR, dir_name)
    if not os.path.isdir(dir_path):
        return False
    # Check at least the first and last intermediate frame
    return (
        os.path.exists(os.path.join(dir_path, "00.jpg"))
        and os.path.exists(os.path.join(dir_path, f"{TRANSITION_STEPS - 1:02d}.jpg"))
    )


def run_transition(from_period, to_period, duration):
    """Step through pre-rendered frames over the given duration.
    Uses wall-clock anchoring so sleep/wake is handled naturally."""
    if not transition_frames_exist(from_period, to_period):
        log(f"No transition frames for {from_period}→{to_period}, hard-switching")
        frame = os.path.join(FRAMES_DIR, f"{to_period}.png")
        if os.path.exists(frame):
            set_wallpaper(frame)
        save_last_period(to_period)
        clear_progress()
        return

    total_steps = TRANSITION_STEPS + 1  # intermediate frames + final
    step_interval = duration / total_steps
    start_time = datetime.datetime.now()

    save_progress(from_period, to_period, 0, start_time)

    for step in range(1, total_steps + 1):
        # Wall-clock anchoring: always check where we SHOULD be
        elapsed = (datetime.datetime.now() - start_time).total_seconds()
        expected_step = min(int(elapsed / step_interval) + 1, total_steps) if step_interval > 0 else total_steps

        # If we've fallen behind (e.g., wake from sleep), skip ahead
        actual_step = max(step, expected_step)

        frame_path = get_transition_frame(from_period, to_period, actual_step)
        if os.path.exists(frame_path):
            set_wallpaper(frame_path)

        save_progress(from_period, to_period, actual_step, start_time)

        if actual_step >= total_steps:
            break

        # Sleep until the next frame is due
        next_time = start_time + datetime.timedelta(seconds=actual_step * step_interval)
        sleep_secs = (next_time - datetime.datetime.now()).total_seconds()
        if sleep_secs > 0:
            time.sleep(sleep_secs)

        step = actual_step  # advance the loop counter past skipped frames

    # Final: set the endpoint frame and save state
    final_frame = os.path.join(FRAMES_DIR, f"{to_period}.png")
    if os.path.exists(final_frame):
        set_wallpaper(final_frame)
    save_last_period(to_period)
    clear_progress()


def hard_switch(period):
    """Immediately set wallpaper to a period with no transition."""
    frame = ensure_frame(period)
    if frame:
        set_wallpaper(frame)
    save_last_period(period)
    clear_progress()


def write_schedule():
    """Calculate today's sunrise and write the launchd plist."""
    lat, lon = get_location()
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
        # Check if we already wrote the schedule today
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

    # Acquire lock — only one instance should be stepping through frames
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

    # If already showing the correct period, nothing to do
    if last_period == target_period:
        # But check if there's an in-progress transition we should resume
        progress = load_progress()
        if progress and progress["to"] == target_period:
            # There's a stalled transition — the endpoint is correct, just finalize
            final_frame = os.path.join(FRAMES_DIR, f"{target_period}.png")
            if os.path.exists(final_frame):
                set_wallpaper(final_frame)
            clear_progress()
        return

    if not last_period:
        log(f"First run — setting wallpaper to {target_period}")
        hard_switch(target_period)
        return

    # Determine how far we are from the transition start time
    transition_start = get_transition_time(target_period, lat, lon)
    seconds_since_start = (datetime.datetime.now() - transition_start).total_seconds()

    # Are we within the normal 30-minute transition window?
    if 0 <= seconds_since_start <= TRANSITION_DURATION:
        # We're mid-window. Calculate which frame we should be on and
        # start from there (handles wake mid-transition perfectly).
        step_interval = TRANSITION_DURATION / (TRANSITION_STEPS + 1)
        current_step = int(seconds_since_start / step_interval)

        if current_step >= TRANSITION_STEPS + 1:
            # Window is basically over — just finish
            log(f"Transition {last_period}→{target_period} (completing)")
            hard_switch(target_period)
        else:
            # Jump to the current frame, then continue stepping normally
            log(f"Transition {last_period}→{target_period} "
                f"(resuming at step {current_step}/{TRANSITION_STEPS})")
            frame_path = get_transition_frame(last_period, target_period, current_step)
            if os.path.exists(frame_path):
                set_wallpaper(frame_path)

            # Calculate remaining duration
            remaining_seconds = TRANSITION_DURATION - seconds_since_start
            remaining_steps = TRANSITION_STEPS + 1 - current_step
            if remaining_steps > 0 and remaining_seconds > 0:
                # Continue the transition for the remaining time
                run_transition_from_step(
                    last_period, target_period,
                    start_step=current_step,
                    remaining_duration=remaining_seconds,
                )
            else:
                hard_switch(target_period)
    else:
        # We're past the transition window (or before it, which shouldn't happen).
        # Do a quick catch-up fade.
        log(f"Catch-up {last_period}→{target_period} "
            f"({seconds_since_start / 60:.0f}min past transition)")
        run_transition(last_period, target_period, duration=CATCHUP_DURATION)


def run_transition_from_step(from_period, to_period, start_step, remaining_duration):
    """Continue a transition from a specific step over the remaining duration."""
    if not transition_frames_exist(from_period, to_period):
        hard_switch(to_period)
        return

    total_steps = TRANSITION_STEPS + 1
    remaining_steps = total_steps - start_step
    step_interval = remaining_duration / remaining_steps if remaining_steps > 0 else 0
    start_time = datetime.datetime.now()

    save_progress(from_period, to_period, start_step, start_time)

    for i in range(remaining_steps):
        step = start_step + i + 1
        if step > total_steps:
            break

        # Wall-clock anchoring
        elapsed = (datetime.datetime.now() - start_time).total_seconds()
        expected_i = min(int(elapsed / step_interval), remaining_steps - 1) if step_interval > 0 else remaining_steps - 1
        actual_i = max(i, expected_i)
        actual_step = start_step + actual_i + 1

        if actual_step > total_steps:
            actual_step = total_steps

        frame_path = get_transition_frame(from_period, to_period, actual_step)
        if os.path.exists(frame_path):
            set_wallpaper(frame_path)

        save_progress(from_period, to_period, actual_step, start_time)

        if actual_step >= total_steps:
            break

        # Sleep until next frame
        next_time = start_time + datetime.timedelta(seconds=(actual_i + 1) * step_interval)
        sleep_secs = (next_time - datetime.datetime.now()).total_seconds()
        if sleep_secs > 0:
            time.sleep(sleep_secs)

    # Final
    final_frame = os.path.join(FRAMES_DIR, f"{to_period}.png")
    if os.path.exists(final_frame):
        set_wallpaper(final_frame)
    save_last_period(to_period)
    clear_progress()


if __name__ == "__main__":
    main()
