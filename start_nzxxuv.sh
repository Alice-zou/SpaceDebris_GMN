#!/bin/bash
#
# start_nzxxuv.sh — start the Optec filter-wheel scheduler and RMS capture together.
#
# WHY THIS EXISTS
#   RMS's own StartCapture.sh does NOT launch the filter wheel: an RMS update overwrote the earlier
#   in-launcher integration, so starting capture alone never runs filter_cycle.py. This wrapper owns
#   the coupling instead, so it survives future RMS updates. Run THIS instead of StartCapture.sh:
#
#       ~/Desktop/Workspace/start_nzxxuv.sh            # defaults to station NZXXUV
#       ~/Desktop/Workspace/start_nzxxuv.sh NZXXUV
#
# WHAT IT DOES
#   1. Starts fw-python-main/filter_cycle.py in the background (the whole-night NL-brackets-UV
#      scheduler), but ONLY for stations listed in FILTERWHEEL_STATIONS (one physical wheel on this Pi).
#   2. Runs RMS capture via StartCapture.sh in the foreground.
#   3. On exit (capture ends / Ctrl-C), sends SIGINT to the scheduler so it runs its end-calibration
#      bracket and PARKS the wheel at UV before quitting.
#
# CAVEAT — launch when you are ready to observe (near/after dusk). If StartCapture waits for nightfall,
#   the wheel's start-calibration burst happens now, not when recording actually begins.
#
# ADVANCED / TESTING ENV VARS
#   FW_ARGS               extra args passed to filter_cycle.py (e.g. "--simulate --uv-frames 10 --check-frames 1")
#   NZXXUV_CAPTURE_CMD    override the capture command (used by the test harness; default = real RMS)

set -u

STATION="${1:-NZXXUV}"

# Stations that have the filter wheel attached (space-separated). Others start capture only.
FILTERWHEEL_STATIONS="${FILTERWHEEL_STATIONS:-NZXXUV}"

WORKSPACE="$HOME/Desktop/Workspace"
FW_SCRIPT="$WORKSPACE/fw-python-main/filter_cycle.py"
VENV_PY="$HOME/vRMS/bin/python"                                   # filter_cycle runs in the vRMS venv
CAPTURE_CMD="${NZXXUV_CAPTURE_CMD:-$HOME/source/RMS/Scripts/MultiCamLinux/StartCapture.sh}"

fw_pid=""

# station_has_wheel — return 0 if $STATION is in the FILTERWHEEL_STATIONS list, else 1.
station_has_wheel() {
    case " $FILTERWHEEL_STATIONS " in
        *" $STATION "*) return 0 ;;
        *) return 1 ;;
    esac
}

# start_filterwheel — launch filter_cycle.py in the background, logging to the RMS logs dir.
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

# stop_filterwheel — ask the scheduler to shut down cleanly (end-calibration bracket + park at UV).
# Runs from the EXIT trap, so the wheel is always parked no matter how capture ends.
stop_filterwheel() {
    if [[ -n "$fw_pid" ]] && kill -0 "$fw_pid" 2>/dev/null; then
        echo "Stopping filter wheel scheduler (PID $fw_pid); parking wheel at UV..."
        kill -INT "$fw_pid" 2>/dev/null   # SIGINT -> end-calibration bracket, then park, then exit
        wait "$fw_pid" 2>/dev/null
    fi
}

trap stop_filterwheel EXIT

start_filterwheel

# Capture runs in the foreground; when it returns (or is Ctrl-C'd) the EXIT trap parks the wheel.
"$CAPTURE_CMD" "$STATION"
