#!/usr/bin/env bash
#
# Test harness for the wallpaper crossfade overlay.
#
# Reproduces the transition effect on demand (instead of waiting for a
# scheduled time), so the aspect-ratio / scaling behaviour can be tuned and
# verified. Your current wallpaper state (.last_period) is restored on exit.
#
# Usage:
#   ./test_crossfade.sh align [period]           Park the overlay (aspect-fill)
#                                                on top of the SAME image set as
#                                                the real wallpaper (fill screen)
#                                                and hold it, so any entrance pulse
#                                                or static misalignment is directly
#                                                inspectable. Ctrl-C to exit.
#                                                (default period: night)
#
#   ./test_crossfade.sh fade [from] [to] [secs]  Run a single crossfade.
#                                                (default: night morning 8)
#
#   ./test_crossfade.sh loop [a] [b] [secs]      Bounce a<->b repeatedly until
#                                                Ctrl-C. (default: night morning 5)
#
# Periods: morning day evening night

set -uo pipefail
cd "$(dirname "$0")"

BIN=./crossfade_overlay
SRC=crossfade_overlay.swift
FRAMES=frames
STATE=.last_period

frame() { echo "$FRAMES/$1.png"; }

build() {
  if [[ ! -x "$BIN" || "$SRC" -nt "$BIN" ]]; then
    echo "Building $BIN ..."
    swiftc -O -o "$BIN" "$SRC" || { echo "Build failed" >&2; exit 1; }
  fi
}

require_frame() {
  if [[ ! -f "$(frame "$1")" ]]; then
    echo "Frame missing: $(frame "$1")" >&2
    echo "Extract it once with: python3 solar_wallpaper.py --hard-switch $1" >&2
    exit 1
  fi
}

# --- save current state, restore on exit (idempotent) ---
ORIG_PERIOD=""
[[ -f "$STATE" ]] && ORIG_PERIOD="$(cat "$STATE")"
_restored=0
_touched=0   # set to 1 once a test actually launches the overlay
restore() {
  [[ "$_restored" == "1" ]] && return
  _restored=1
  if [[ "$_touched" == "1" && -n "$ORIG_PERIOD" ]]; then
    echo ""
    echo "Restoring wallpaper to: $ORIG_PERIOD"
    python3 solar_wallpaper.py --hard-switch "$ORIG_PERIOD" >/dev/null 2>&1 || true
  fi
}
trap 'restore; exit 0' INT TERM
trap restore EXIT

cmd="${1:-help}"
case "$cmd" in
  align)
    period="${2:-night}"
    require_frame "$period"
    build
    echo "ALIGN TEST"
    echo "  overlay  = $period  (CALayer scaling: aspect-fill)"
    echo "  wallpaper= $period  (macOS scaling: fill screen)"
    echo "Same image both layers. It should appear as ONE seamless image."
    echo "Any entrance pulse or static edge shift reveals a mismatch."
    echo ""
    _touched=1
    "$BIN" "$(frame "$period")" "$(frame "$period")" hold
    ;;

  fade)
    from="${2:-night}"; to="${3:-morning}"; dur="${4:-8}"
    require_frame "$from"; require_frame "$to"
    build
    echo "FADE TEST: $from -> $to over ${dur}s"
    _touched=1
    "$BIN" "$(frame "$from")" "$(frame "$to")" "$dur"
    ;;

  loop)
    a="${2:-night}"; b="${3:-morning}"; dur="${4:-5}"
    require_frame "$a"; require_frame "$b"
    build
    echo "LOOP TEST: $a <-> $b, ${dur}s fade each way. Ctrl-C to stop."
    _touched=1
    cur="$a"; nxt="$b"
    while true; do
      echo "  $cur -> $nxt"
      "$BIN" "$(frame "$cur")" "$(frame "$nxt")" "$dur"
      sleep 1
      tmp="$cur"; cur="$nxt"; nxt="$tmp"
    done
    ;;

  *)
    # Print only the leading usage comment block.
    awk 'NR>2 && /^#/ {sub(/^# ?/,""); print; if (/^Periods:/) exit}' "$0"
    ;;
esac
