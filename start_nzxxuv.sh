#!/bin/bash
#
# start_nzxxuv.sh — start RMS capture for the filter-wheel station.
#
# Begin Robinson Space Debris edit 2026-07-20 by Alice Zou
#
# WHY THIS EXISTS
#   The filter wheel is now driven from INSIDE RMS capture: RMS/RMS/BufferedCapture.py opens the
#   wheel lazily and calls check_in() once per FT block. There must be exactly ONE controller on the
#   one physical wheel, so this wrapper no longer launches fw-python-main/filter_capture_sync.py —
#   two processes on the same serial port interleave commands and corrupt each other's idea of the
#   current position.
#
#   The wrapper is kept (rather than pointing boot_start_all.sh straight at StartCapture.sh) so the
#   station keeps a single stable entry point, and so wheel-related setup has somewhere to live.
#
#       ~/Desktop/Workspace/start_nzxxuv.sh            # defaults to station NZXXUV
#       ~/Desktop/Workspace/start_nzxxuv.sh NZXXUV
#
# NOTE — the wheel is no longer parked at UV when capture exits; the old scheduler did that from its
#   SIGINT handler, and the in-capture hook has no equivalent. The wheel simply stops where it is.
#
# filter_capture_sync.py and filter_cycle.py are both left on disk (useful for bench testing with
# --simulate) but neither is launched automatically any more.
#
# ADVANCED / TESTING ENV VARS
#   NZXXUV_CAPTURE_CMD    override the capture command (used by the test harness; default = real RMS)
#
# End Robinson Space Debris

set -u

STATION="${1:-NZXXUV}"

CAPTURE_CMD="${NZXXUV_CAPTURE_CMD:-$HOME/source/RMS/Scripts/MultiCamLinux/StartCapture.sh}"

echo "Starting capture for $STATION (filter wheel is driven from within RMS capture)..."

"$CAPTURE_CMD" "$STATION"
