#!/bin/bash
#
# boot_start_all.sh — boot orchestrator for this Pi's two meteor stations.
#
# WHY THIS EXISTS
#   The stock RMS multi-cam launcher (RMS_StartCapture_MCP.sh) just loops ~/source/Stations/* and
#   runs plain `StartCapture.sh <station>` for each. On this Pi that is wrong for NZXXUV, because:
#     * NZXXUV's video source is the local Spinnaker->RTSP stream (rtsp://127.0.0.1:8554/live),
#       which nothing else starts, and
#     * NZXXUV needs the Optec filter wheel running (filter_cycle.py), which plain StartCapture
#       does NOT launch.
#   This orchestrator fixes both, and is kept OUTSIDE the RMS repo so RMS updates can't overwrite it.
#   It is wired into boot by repointing ~/Desktop/RMS_StartCapture.sh at this file (RMS_FirstRun.sh
#   calls that symlink after the RMS self-update).
#
# WHAT IT DOES, IN ORDER
#   1. Starts the Spinnaker->RTSP stream FIRST. That script bounces eth0 to MTU 9000 (jumbo frames)
#      via passwordless sudo, so we WAIT for the stream to be up before starting any station — this
#      also lets eth0 settle before capture starts.
#   2. Loops the stations: wheel stations (FILTERWHEEL_STATIONS) launch via start_nzxxuv.sh
#      (filter wheel + capture); all others launch via plain StartCapture.sh, exactly as before.
#
# TESTING
#   DRY_RUN=1 ~/Desktop/Workspace/boot_start_all.sh   # print what it would do; launch nothing, no sleeps

set -u

WORKSPACE="$HOME/Desktop/Workspace"
STATIONS_DIR="$HOME/source/Stations"
RTSP_LAUNCHER="$WORKSPACE/RTSP/start_spinnaker_rtsp.sh"
WRAPPER="$WORKSPACE/start_nzxxuv.sh"
PLAIN_CAPTURE="$HOME/source/RMS/Scripts/MultiCamLinux/StartCapture.sh"

# Stations that have the filter wheel + local RTSP stream (space-separated). Others start plain capture.
FILTERWHEEL_STATIONS="${FILTERWHEEL_STATIONS:-NZXXUV}"

DRY_RUN="${DRY_RUN:-0}"

# term TITLE CMDSTRING — open a command in its own terminal window (matches the RMS launcher style).
term() {
    if [[ "$DRY_RUN" == "1" ]]; then
        echo "[dry-run] lxterminal --title=$1 -e \"$2\""
    else
        lxterminal --title="$1" -e "$2" &
    fi
}

# has_wheel STATION — true if STATION is in FILTERWHEEL_STATIONS.
has_wheel() {
    case " $FILTERWHEEL_STATIONS " in
        *" $1 "*) return 0 ;;
        *) return 1 ;;
    esac
}

# rtsp_up — true if something is listening on TCP :8554 (the local RTSP stream).
rtsp_up() {
    ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE ':8554$'
}

# wait_for_rtsp [TIMEOUT] — poll until the RTSP stream is up, or TIMEOUT seconds elapse.
wait_for_rtsp() {
    local timeout="${1:-90}" waited=0
    echo "Waiting up to ${timeout}s for RTSP stream on :8554 (also lets eth0 settle at MTU 9000)..."
    while (( waited < timeout )); do
        if rtsp_up; then
            echo "RTSP stream is up (:8554)."
            return 0
        fi
        sleep 3
        waited=$((waited + 3))
    done
    echo "WARNING: RTSP stream not detected on :8554 after ${timeout}s; continuing anyway."
    return 1
}

echo "== boot_start_all: bringing up the station stack =="

# 1) Start the local RTSP stream first, then wait for it (so eth0 is settled before capture starts).
if rtsp_up; then
    echo "RTSP stream already running on :8554; not starting another."
else
    echo "Starting Spinnaker->RTSP stream (NZXXUV video source)..."
    term "RTSP-stream" "$RTSP_LAUNCHER"
fi
[[ "$DRY_RUN" == "1" ]] || wait_for_rtsp 90

# 2) Start each configured station.
seconds=70
loop=0
for Dir in "$STATIONS_DIR"/*; do
    Station="$(basename "$Dir")"

    if has_wheel "$Station"; then
        echo "Starting camera $Station (filter wheel + capture via wrapper)"
        term "$Station" "$WRAPPER $Station"
    else
        echo "Starting camera $Station (plain capture)"
        term "$Station" "$PLAIN_CAPTURE $Station"
    fi

    echo "  waiting $seconds seconds..."
    [[ "$DRY_RUN" == "1" ]] || sleep "$seconds"
    (( loop == 0 )) && seconds=10
    loop=$((loop + 1))
done

echo "== boot_start_all: all stations started =="
