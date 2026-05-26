#!/usr/bin/env python3
"""
Switches macOS wallpaper between Tahoe Morning/Day/Evening/Night
based on the sun's position in the sky, with smooth crossfade transitions.
"""

import datetime
import json
import math
import os
import plistlib
import subprocess
import sys
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
STORE_PATH = os.path.expanduser(
    "~/Library/Application Support/com.apple.wallpaper/Store/Index.plist"
)
VIDEOS_DIR = os.path.expanduser(
    "~/Library/Application Support/com.apple.wallpaper/aerials/videos"
)
FRAMES_DIR = os.path.join(SCRIPT_DIR, "frames")
CROSSFADE_BIN = os.path.join(SCRIPT_DIR, "crossfade_overlay")

WALLPAPERS = {
    "morning": "B2FC91ED-6891-4DEB-85A1-268B2B4160B6",
    "day": "4C108785-A7BA-422E-9C79-B0129F1D5550",
    "evening": "52ACB9B8-75FC-4516-BC60-4550CFF3B661",
    "night": "CF6347E2-4F81-4410-8892-4830991B6C5A",
}

ASSET_TO_PERIOD = {v: k for k, v in WALLPAPERS.items()}

FADE_DURATION = 1800.0  # 30 minutes


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


def get_current_asset_id():
    try:
        with open(STORE_PATH, "rb") as f:
            data = plistlib.load(f)
        config_bytes = data["AllSpacesAndDisplays"]["Linked"]["Content"]["Choices"][0]["Configuration"]
        config = plistlib.loads(config_bytes)
        return config.get("assetID")
    except Exception:
        return None


def ensure_frame(period):
    """Extract and cache a frame from the given period's video at t=0."""
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


def hard_switch(period):
    """Switch wallpaper immediately without transition."""
    asset_id = WALLPAPERS[period]

    with open(STORE_PATH, "rb") as f:
        data = plistlib.load(f)

    new_config = plistlib.dumps({"assetID": asset_id}, fmt=plistlib.FMT_BINARY)
    now = datetime.datetime.now()

    for key in ["AllSpacesAndDisplays", "SystemDefault"]:
        if key in data and "Linked" in data[key]:
            data[key]["Linked"]["Content"]["Choices"][0]["Configuration"] = new_config
            data[key]["Linked"]["LastSet"] = now
            data[key]["Linked"]["LastUse"] = now

    with open(STORE_PATH, "wb") as f:
        plistlib.dump(data, f, fmt=plistlib.FMT_BINARY)

    subprocess.run(["killall", "WallpaperAgent"], capture_output=True)


def crossfade_transition(from_period, to_period):
    """Perform a smooth crossfade transition between two wallpaper periods."""
    from_frame = ensure_frame(from_period)
    to_frame = ensure_frame(to_period)

    if not from_frame or not to_frame:
        print("Could not extract frames, falling back to hard switch.")
        hard_switch(to_period)
        return

    if not os.path.exists(CROSSFADE_BIN):
        print("Crossfade binary not found, falling back to hard switch.")
        hard_switch(to_period)
        return

    mid_command = f"{sys.executable} {os.path.abspath(__file__)} --hard-switch {to_period}"

    subprocess.Popen([
        CROSSFADE_BIN,
        from_frame,
        to_frame,
        str(FADE_DURATION),
        mid_command,
    ])


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

    lat, lon = get_location()
    period = get_period(lat, lon)
    target_asset = WALLPAPERS[period]
    current_asset = get_current_asset_id()

    if current_asset == target_asset:
        print(f"Already showing {period}. No change needed.")
        return

    current_period = ASSET_TO_PERIOD.get(current_asset)
    elev = solar_elevation(lat, lon)

    if current_period:
        print(f"Transitioning {current_period} → {period} (solar elevation: {elev:.1f}°)")
        crossfade_transition(current_period, period)
    else:
        print(f"Switched to Tahoe {period.capitalize()} (solar elevation: {elev:.1f}°)")
        hard_switch(period)


if __name__ == "__main__":
    main()
