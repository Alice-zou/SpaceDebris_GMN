#!/bin/bash
#
# start_nzxxuv.sh — start the Optec filter-wheel scheduler and RMS capture together.
#
# WHY THIS EXISTS
#   RMS's own StartCapture.sh does NOT launch the filter wheel: an RMS update overwrote the earlier
#   in-launcher integration, so starting capture alone never runs the filter-wheel scheduler. This
#   wrapper owns the coupling instead, so it survives future RMS updates. Run THIS instead of
#   StartCapture.sh:
#
#       ~/Desktop/Workspace/start_nzxxuv.sh            # defaults to station NZXXUV
#       ~/Desktop/Workspace/start_nzxxuv.sh NZXXUV
#
# WHAT IT DOES
#   1. Starts fw-python-main/filter_capture_sync.py in the background (the capture-synced scheduler:
#      it watches the RMS CapturedFiles night directory and switches the wheel off real FF capture
#      blocks, default 10:1 UV:Natural Light), but ONLY for stations listed in FILTERWHEEL_STATIONS
#      (one physical wheel on this Pi). Note: filter_cycle.py (the older wall-clock scheduler) is left
#      in place but is no longer launched here.
#   2. Runs RMS capture via StartCapture.sh in the foreground.
#   3. On exit (capture ends / Ctrl-C), sends SIGINT to the scheduler so it PARKS the wheel at UV
#      before quitting.
#
# CAVEAT — RMS delays star detection / FF processing for ~2 minutes after capture starts, so the first
#   UV->Natural Light switch happens a couple of minutes into the session, not immediately.
#
# ADVANCED / TESTING ENV VARS
#   FW_ARGS               extra args passed to filter_capture_sync.py
#                         (e.g. "--simulate --simulate-ff 2 --uv-events 10 --nl-events 1")
#   NZXXUV_CAPTURE_CMD    override the capture command (used by the test harness; default = real RMS)

set -u

STATION="${1:-NZXXUV}"

# Stations that have the filter wheel attached (space-separated). Others start capture only.
FILTERWHEEL_STATIONS="${FILTERWHEEL_STATIONS:-NZXXUV}"

WORKSPACE="$HOME/Desktop/Workspace"
FW_SCRIPT="$WORKSPACE/fw-python-main/filter_capture_sync.py"
VENV_PY="$HOME/vRMS/bin/python"                                   # scheduler runs in the vRMS venv
CAPTURE_CMD="${NZXXUV_CAPTURE_CMD:-$HOME/source/RMS/Scripts/MultiCamLinux/StartCapture.sh}"

fw_pid=""

# station_has_wheel — return 0 if $STATION is in the FILTERWHEEL_STATIONS list, else 1.
station_has_wheel() {
    case " $FILTERWHEEL_STATIONS " in
        *" $STATION "*) return 0 ;;
        *) return 1 ;;
    esac
}

# start_filterwheel — launch filter_capture_sync.py in the background, logging to the RMS logs dir.
# (The scheduler also writes its own dedicated log at ~/RMS_data/filter_capture_sync.log.)
start_filterwheel() {
    if ! station_has_wheel; then
        echo "Filter wheel not enabled for $STATION (FILTERWHEEL_STATIONS='$FILTERWHEEL_STATIONS'); skipping."
        return
    fi

    mkdir -p "$HOME/RMS_data/logs"
    local log="$HOME/RMS_data/logs/$(date -u +%Y%m%d)_${STATION}_filterwheel.txt"

    echo "Starting filter wheel scheduler for $STATION..."
    # shellcheck disable=SC2086  # FW_ARGS is intentionally word-split into separate flags
    "$VENV_PY" -u "$FW_SCRIPT" ${FW_ARGS:-} >>"$log" 2>&1 &
    fw_pid=$!
    echo "Filter wheel scheduler started (PID $fw_pid), logging to"
    echo "  $log"
}

# stop_filterwheel — ask the scheduler to shut down cleanly (stop watching + park at UV).
# Runs from the EXIT trap, so the wheel is always parked no matter how capture ends.
stop_filterwheel() {
    if [[ -n "$fw_pid" ]] && kill -0 "$fw_pid" 2>/dev/null; then
        echo "Stopping filter wheel scheduler (PID $fw_pid); parking wheel at UV..."
        kill -INT "$fw_pid" 2>/dev/null   # SIGINT -> stop watching, park the wheel, then exit
        wait "$fw_pid" 2>/dev/null
    fi
}

trap stop_filterwheel EXIT

start_filterwheel

# Capture runs in the foreground; when it returns (or is Ctrl-C'd) the EXIT trap parks the wheel.
"$CAPTURE_CMD" "$STATION"
