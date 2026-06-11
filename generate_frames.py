#!/usr/bin/env python3
"""
Pre-renders blended transition frames between each adjacent period.

Output structure:
  transitions/morning_to_day/00.jpg ... 29.jpg
  transitions/day_to_evening/00.jpg ... 29.jpg
  transitions/evening_to_night/00.jpg ... 29.jpg
  transitions/night_to_morning/00.jpg ... 29.jpg

Each frame is a linear blend: frame N = (1 - alpha) * from + alpha * to
where alpha = (N + 1) / (STEPS + 1).

Frame 00 is almost entirely the "from" image (3.2% "to").
Frame 29 is almost entirely the "to" image (96.8% "to").
The pure from/to endpoints are the base frames in frames/.
"""

import os
import sys
from PIL import Image
import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FRAMES_DIR = os.path.join(SCRIPT_DIR, "frames")
TRANSITIONS_DIR = os.path.join(SCRIPT_DIR, "transitions")

PERIODS = ["morning", "day", "evening", "night"]
STEPS = 30  # intermediate frames per transition
JPEG_QUALITY = 92


def generate_transition(from_period, to_period):
    """Generate blended frames between two periods."""
    dir_name = f"{from_period}_to_{to_period}"
    out_dir = os.path.join(TRANSITIONS_DIR, dir_name)
    os.makedirs(out_dir, exist_ok=True)

    from_path = os.path.join(FRAMES_DIR, f"{from_period}.png")
    to_path = os.path.join(FRAMES_DIR, f"{to_period}.png")

    if not os.path.exists(from_path) or not os.path.exists(to_path):
        print(f"  SKIP {dir_name} — missing source frame(s)")
        return False

    # Load as 8-bit for blending (the 16-bit source gets quantized here)
    print(f"  Loading {from_period}.png...", end="", flush=True)
    from_img = np.array(Image.open(from_path).convert("RGB"), dtype=np.float32)
    print(f" {to_period}.png...", end="", flush=True)
    to_img = np.array(Image.open(to_path).convert("RGB"), dtype=np.float32)
    print(" done.")

    if from_img.shape != to_img.shape:
        print(f"  ERROR: dimension mismatch {from_img.shape} vs {to_img.shape}")
        return False

    for i in range(STEPS):
        alpha = (i + 1) / (STEPS + 1)
        blended = ((1 - alpha) * from_img + alpha * to_img).clip(0, 255).astype(np.uint8)
        out_path = os.path.join(out_dir, f"{i:02d}.jpg")
        Image.fromarray(blended).save(out_path, "JPEG", quality=JPEG_QUALITY)
        print(f"\r  {dir_name}: {i + 1}/{STEPS} ({alpha:.1%})", end="", flush=True)

    print()
    return True


def main():
    if not os.path.isdir(FRAMES_DIR):
        print(f"Error: frames directory not found: {FRAMES_DIR}")
        print("Run solar_wallpaper.py once to extract base frames from the aerial videos.")
        sys.exit(1)

    # Check all base frames exist
    missing = [p for p in PERIODS if not os.path.exists(os.path.join(FRAMES_DIR, f"{p}.png"))]
    if missing:
        print(f"Error: missing base frames: {missing}")
        sys.exit(1)

    print(f"Generating {STEPS} transition frames per pair ({STEPS * 4} total)")
    print(f"Output: {TRANSITIONS_DIR}/")
    print()

    transitions = [
        ("morning", "day"),
        ("day", "evening"),
        ("evening", "night"),
        ("night", "morning"),
    ]

    for from_p, to_p in transitions:
        print(f"[{from_p} → {to_p}]")
        generate_transition(from_p, to_p)

    # Report disk usage
    total_size = 0
    for root, dirs, files in os.walk(TRANSITIONS_DIR):
        for f in files:
            if f.endswith(".jpg"):
                total_size += os.path.getsize(os.path.join(root, f))

    print(f"\nDone. Total transition frames: {total_size / 1024 / 1024:.0f} MB")


if __name__ == "__main__":
    main()
