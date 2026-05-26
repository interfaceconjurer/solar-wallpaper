#!/usr/bin/env python3
"""
Simulate crossfade transitions between Tahoe wallpaper videos.
Generates smooth MP4 videos showing the crossfade between each pair of periods.
Opens in QuickTime for real-time playback with scrubbing.
"""

import os
import subprocess
import sys
import tempfile

VIDEOS_DIR = os.path.expanduser(
    "~/Library/Application Support/com.apple.wallpaper/aerials/videos"
)

WALLPAPERS = {
    "morning": "B2FC91ED-6891-4DEB-85A1-268B2B4160B6",
    "day": "4C108785-A7BA-422E-9C79-B0129F1D5550",
    "evening": "52ACB9B8-75FC-4516-BC60-4550CFF3B661",
    "night": "CF6347E2-4F81-4410-8892-4830991B6C5A",
}

TRANSITION_ORDER = ["morning", "day", "evening", "night"]

# Each clip: 2s hold on A, 5s crossfade, 2s hold on B
HOLD_DURATION = 2
FADE_DURATION = 5
FPS = 30


def video_path(name):
    return os.path.join(VIDEOS_DIR, f"{WALLPAPERS[name]}.mov")


def generate_crossfade_video(name_a, name_b, output_path, source_timestamp=150.0):
    """
    Use ffmpeg to render a crossfade transition between two wallpaper videos.
    Extracts a still frame from each at the given timestamp, then crossfades between them.
    """
    vid_a = video_path(name_a)
    vid_b = video_path(name_b)

    total_duration = HOLD_DURATION + FADE_DURATION + HOLD_DURATION

    # Use ffmpeg's xfade filter on single-frame loops created from each video
    # 1. Grab a frame from each video and loop it for the needed duration
    # 2. Apply xfade between the two loops
    duration_a = HOLD_DURATION + FADE_DURATION  # A needs to last through the fade
    duration_b = FADE_DURATION + HOLD_DURATION  # B needs to start at fade and continue

    cmd = [
        "ffmpeg", "-y",
        # Input A: seek to timestamp, grab frames, loop as video
        "-ss", str(source_timestamp),
        "-i", vid_a,
        # Input B: seek to timestamp, grab frames, loop as video
        "-ss", str(source_timestamp),
        "-i", vid_b,
        "-filter_complex",
        (
            # Take 1 frame from each, loop them into videos at our FPS
            f"[0:v]trim=start=0:end=0.04,loop={duration_a * FPS}:{1}:0,"
            f"setpts=N/{FPS}/TB,fps={FPS},scale=960:540[a];"
            f"[1:v]trim=start=0:end=0.04,loop={duration_b * FPS}:{1}:0,"
            f"setpts=N/{FPS}/TB,fps={FPS},scale=960:540[b];"
            # Crossfade: starts at HOLD_DURATION into the timeline
            f"[a][b]xfade=transition=fade:duration={FADE_DURATION}:offset={HOLD_DURATION}"
        ),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-an",
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ffmpeg error: {result.stderr[-500:]}", file=sys.stderr)
        return False
    return True


def main():
    timestamp = 150.0
    if len(sys.argv) > 1:
        timestamp = float(sys.argv[1])

    # Verify videos exist
    for name, uuid in WALLPAPERS.items():
        vp = video_path(name)
        if not os.path.exists(vp):
            print(f"Missing: {name} ({vp})", file=sys.stderr)
            sys.exit(1)

    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transitions")
    os.makedirs(output_dir, exist_ok=True)

    print(f"Generating crossfade videos (source frame at t={timestamp}s)")
    print(f"  {HOLD_DURATION}s hold → {FADE_DURATION}s fade → {HOLD_DURATION}s hold")
    print(f"  Output: {output_dir}\n")

    video_paths = []
    for i in range(len(TRANSITION_ORDER)):
        name_a = TRANSITION_ORDER[i]
        name_b = TRANSITION_ORDER[(i + 1) % len(TRANSITION_ORDER)]

        out_path = os.path.join(output_dir, f"{name_a}_to_{name_b}.mp4")
        print(f"  {name_a} → {name_b}...", end=" ", flush=True)

        if generate_crossfade_video(name_a, name_b, out_path, timestamp):
            size_mb = os.path.getsize(out_path) / (1024 * 1024)
            print(f"done ({size_mb:.1f} MB)")
            video_paths.append(out_path)
        else:
            print("FAILED")

    if video_paths:
        # Open all in QuickTime
        print(f"\nOpening {len(video_paths)} videos...")
        subprocess.run(["open"] + video_paths)
        print("\nAll transitions:")
        for p in video_paths:
            print(f"  {p}")


if __name__ == "__main__":
    main()
