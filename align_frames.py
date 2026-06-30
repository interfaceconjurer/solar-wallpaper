#!/usr/bin/env python3
"""
Register the period stills (frames/*.png) to a common reference so that
crossfades between periods don't visibly shift.

The Tahoe aerial videos are separate renders whose content sits at slightly
different pixel positions, so frames extracted at the same timestamp are
misregistered by a few pixels. Scaling already matches macOS (aspect-fill),
but this residual content shift makes features (e.g. the right-side tree)
appear to jump as one period dissolves into the next.

This tool measures each frame's shift relative to a reference frame via FFT
phase correlation, rolls each frame into alignment, then crops a uniform
margin off every frame to discard the wrapped edges. All output frames end up
the same size and mutually registered.

Run it once after frames are (re)extracted:

    python3 align_frames.py                 # reference = night
    python3 align_frames.py --reference day
    python3 align_frames.py --dry-run       # measure only, don't rewrite

Requires numpy + Pillow (run with a Python that has them, e.g. Homebrew's).
Originals are backed up to frames/.unaligned/ on first run.
"""

import argparse
import os
import sys

import numpy as np
from PIL import Image

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FRAMES_DIR = os.path.join(SCRIPT_DIR, "frames")
BACKUP_DIR = os.path.join(FRAMES_DIR, ".unaligned")
PERIODS = ["morning", "day", "evening", "night"]

# Pixels trimmed from every edge after rolling, to remove wrap-around. Must be
# larger than the largest expected misregistration (observed <= ~10px).
MARGIN = 24


def frame_path(period):
    return os.path.join(FRAMES_DIR, f"{period}.png")


def phase_shift(ref_gray, other_gray):
    """Integer (dy, dx) such that np.roll(other, (dy, dx)) best matches ref."""
    Fa = np.fft.fft2(ref_gray)
    Fb = np.fft.fft2(other_gray)
    R = Fa * np.conj(Fb)
    R /= np.abs(R) + 1e-9
    corr = np.fft.ifft2(R).real
    dy, dx = np.unravel_index(np.argmax(corr), corr.shape)
    h, w = ref_gray.shape
    if dy > h // 2:
        dy -= h
    if dx > w // 2:
        dx -= w
    return int(dy), int(dx)


def main():
    ap = argparse.ArgumentParser(description="Register period frames to a reference.")
    ap.add_argument("--reference", default="night", choices=PERIODS,
                    help="Frame all others are aligned to (default: night).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Measure and report shifts without rewriting frames.")
    args = ap.parse_args()

    missing = [p for p in PERIODS if not os.path.exists(frame_path(p))]
    if missing:
        print(f"Missing frames: {', '.join(missing)}", file=sys.stderr)
        print("Extract them first (e.g. run solar_wallpaper.py).", file=sys.stderr)
        sys.exit(1)

    # Load color + grayscale views.
    rgb = {p: np.asarray(Image.open(frame_path(p)).convert("RGB")) for p in PERIODS}
    gray = {p: np.asarray(Image.open(frame_path(p)).convert("L"), dtype=np.float64)
            for p in PERIODS}

    sizes = {p: rgb[p].shape[:2] for p in PERIODS}
    if len(set(sizes.values())) != 1:
        print(f"Frames differ in size: {sizes}", file=sys.stderr)
        print("All frames must share dimensions to register.", file=sys.stderr)
        sys.exit(1)

    ref = args.reference
    print(f"Reference frame: {ref}  (size {sizes[ref][1]}x{sizes[ref][0]})")
    print(f"Margin trimmed per edge: {MARGIN}px\n")

    shifts = {}
    for p in PERIODS:
        if p == ref:
            shifts[p] = (0, 0)
        else:
            shifts[p] = phase_shift(gray[ref], gray[p])
        dy, dx = shifts[p]
        if abs(dy) >= MARGIN or abs(dx) >= MARGIN:
            print(f"WARNING: {p} shift dx={dx:+d} dy={dy:+d} exceeds margin "
                  f"{MARGIN}px; increase MARGIN.", file=sys.stderr)
        print(f"  {p:8s} dx={dx:+4d}  dy={dy:+4d}")

    if args.dry_run:
        print("\n(dry run — no frames rewritten)")
        return

    # Back up originals once.
    os.makedirs(BACKUP_DIR, exist_ok=True)
    for p in PERIODS:
        bk = os.path.join(BACKUP_DIR, f"{p}.png")
        if not os.path.exists(bk):
            Image.fromarray(rgb[p]).save(bk)

    h, w = sizes[ref]
    print(f"\nWriting registered frames ({w - 2 * MARGIN}x{h - 2 * MARGIN})...")
    for p in PERIODS:
        dy, dx = shifts[p]
        rolled = np.roll(rgb[p], shift=(dy, dx), axis=(0, 1))
        cropped = rolled[MARGIN:h - MARGIN, MARGIN:w - MARGIN]
        Image.fromarray(cropped).save(frame_path(p))

    # Verify: re-measure on the rewritten frames.
    print("\nVerification (post-alignment shift to reference):")
    new_gray = {p: np.asarray(Image.open(frame_path(p)).convert("L"),
                              dtype=np.float64) for p in PERIODS}
    ok = True
    for p in PERIODS:
        dy, dx = (0, 0) if p == ref else phase_shift(new_gray[ref], new_gray[p])
        flag = "" if (abs(dx) <= 1 and abs(dy) <= 1) else "  <-- still off"
        if flag:
            ok = False
        print(f"  {p:8s} dx={dx:+4d}  dy={dy:+4d}{flag}")
    print("\nDone." if ok else "\nDone (some residual remains).")


if __name__ == "__main__":
    main()
