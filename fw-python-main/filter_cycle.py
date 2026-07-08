#!/usr/bin/env python3
"""Night-session filter scheduler for UV space-debris observing with Natural Light astrometry.

WHY THIS EXISTS
---------------
The camera detects space debris (aluminium spectral signature) through a UV filter, but stars are
essentially invisible in UV, so a debris streak captured in a UV frame cannot be plate-solved on its
own. Locating that streak on the sky instead relies on a single, powerful fact:

    For a camera that does not move, the mapping  pixel -> (azimuth, altitude)  is CONSTANT in time.

So the sky position of a debris streak is fully determined by
    (streak pixel coordinates)  +  (frame UTC timestamp)  +  (a stored plate solution / "platepar").
The stars used to *build* that plate solution can come from Natural Light (NL) frames taken at an
unrelated time. We therefore do NOT need stars in the same frame as the debris; we only need enough
NL frames to establish and (optionally) monitor the plate solution. That is what this scheduler does.

SESSION MODEL (whole-night, fixed mount)
----------------------------------------
Dwell durations are specified in CAPTURE FRAMES, not seconds. The scheduler drives the wheel on a wall
clock and is decoupled from the capture system, so a frame count is converted to a dwell time using the
nominal `--fps` (keep it in sync with the RMS capture fps). Working in frames lets the UV/Natural-Light
cadence be stated as a frame ratio - e.g. `--uv-frames 10 --check-frames 1` is a 10:1 UV-to-NL ratio.

The camera is set up and left untouched for a ~10 hour night. The wheel is driven in three phases:

    1. START CALIBRATION BURST  - Natural Light for `calib_frames`. Collect stars across the field to
                                  build the reference plate solution for the whole session.
    2. OBSERVING LOOP           - UV for `uv_frames` (long), then a short Natural Light "drift check"
                                  for `check_frames`, repeated until interrupted. The UV:NL frame ratio
                                  is `uv_frames:check_frames`. On a rigid mount the checks are cheap
                                  insurance; set `check_frames` to 0 to disable them.
    3. END CALIBRATION BURST    - Natural Light for `end_calib_frames` on shutdown. Together with the
                                  start burst this BRACKETS the night: if the start and end plate
                                  solutions agree, the pointing held all night and every UV detection in
                                  between is trustworthy on the reference plate.

Every filter change is timestamped into a history log (see below) so downstream astrometry can tell,
per captured frame, which filter was in place and whether that frame is UV science data or NL
calibration data.

DOWNSTREAM CONTRACT (filter history log)
----------------------------------------
Each line of the history file is:  "<UTC ISO timestamp> <filter name>"  recording the instant a filter
became active. A consumer (e.g. RMS detection) can split on the first space, parse the timestamp, and
know that all frames from that instant until the next line were taken through <filter name>. UV lines
mark science intervals; "Natural Light" lines mark calibration/drift-check intervals.

USAGE
-----
    # Real hardware, default night cadence (10:1 UV:NL, frame counts converted at the default 25 fps):
    python3 filter_cycle.py

    # A tighter 10:1 UV-to-NL frame ratio in the observing loop (10 UV frames per 1 NL check frame):
    python3 filter_cycle.py --uv-frames 10 --check-frames 1

    # Rely on start/end brackets only (no periodic checks), longer UV blocks, 20 fps capture:
    python3 filter_cycle.py --fps 20 --calib-frames 6000 --uv-frames 72000 --check-frames 0

    # Rehearse the schedule with NO hardware attached (prints/log only), sped up for a quick test:
    python3 filter_cycle.py --simulate --fps 25 --calib-frames 75 --uv-frames 125 \
                            --check-frames 50 --end-calib-frames 75
"""

import os
import sys
import time
import signal
import logging
import argparse
import datetime

from fw import FilterWheel


# Filter names, must match the entries in definition_file.csv
UV_FILTER = "UV"
NATURAL_LIGHT_FILTER = "Natural Light"

# Nominal capture frame rate (frames per second). The wheel scheduler is decoupled from the capture
# system and drives the wheel on a wall clock, so dwell durations are specified as frame COUNTS and
# converted to seconds using this rate. Keep it in sync with the RMS capture 'fps' (RMS/.config -> fps).
DEFAULT_FPS = 25.0

# Default dwell durations expressed in FRAMES, tuned for a whole-night fixed-mount session. The
# observing loop defaults to a 10:1 UV:NL frame ratio (uv_frames:check_frames). At the default 25 fps
# these equal 180 s calib / 100 s UV / 10 s check / 120 s end-calib.
DEFAULT_CALIB_FRAMES = 4500      # Natural Light calibration burst at session start (build platepar)
DEFAULT_UV_FRAMES = 2500         # UV observing block between NL pointing anchors (10:1 with check)
DEFAULT_CHECK_FRAMES = 250       # Natural Light pointing anchor between UV blocks (0 disables)
DEFAULT_END_CALIB_FRAMES = 3000  # Natural Light calibration burst at session end (brackets the night)

# The filter definition file lives next to this script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DEFINITION_FILE = os.path.join(SCRIPT_DIR, "definition_file.csv")

# Default filter wheel history log. Each line is "<UTC ISO timestamp> <filter name>", recording the
# moment a filter became active. Downstream astrometry reads this to decide, per captured frame, which
# filter was in place. Keep in sync with the RMS data_dir when wiring detection up.
DEFAULT_HISTORY_FILE = os.path.expanduser("~/RMS_data/filter_history.txt")


log = logging.getLogger("filter_cycle")

# Path to the history log, set in main()
history_file = DEFAULT_HISTORY_FILE


# --------------------------------------------------------------------------------------------------
# Simulated wheel (for testing the schedule without hardware attached)
# --------------------------------------------------------------------------------------------------
class SimulatedFilterWheel:
    """Drop-in stand-in for fw.FilterWheel that performs no hardware I/O.

    It mirrors only the small surface this scheduler uses (`init`, `last_error`, `position_name`,
    `set_position`) so the full phase schedule and history logging can be rehearsed on a machine with
    no filter wheel connected. Moves always "succeed" instantly.
    """

    def __init__(self, definition_file):
        # Reuse the real class only to parse and validate the filter definition CSV; fall back to the
        # two filters this scheduler needs if that class or the file is unavailable in the test env.
        self.init = True
        self.last_error = ""
        self.position_name = ""
        try:
            import pandas as pd
            df = pd.read_csv(definition_file, dtype=str)
            self.filter_list = df['Filter_Name'].tolist()
        except Exception as e:
            log.warning("Simulate: could not read %s (%s); using built-in filter list.",
                        definition_file, e)
            self.filter_list = [UV_FILTER, NATURAL_LIGHT_FILTER]

    def set_position(self, filter_name):
        """Pretend to move to `filter_name`; succeed iff it is a known filter."""
        if filter_name in self.filter_list:
            self.position_name = filter_name
            return 1
        self.last_error = "ERROR: parameter not in the list"
        return 0


# --------------------------------------------------------------------------------------------------
# History logging
# --------------------------------------------------------------------------------------------------
def record_filter(filter_name):
    """Append a "<UTC ISO timestamp> <filter name>" line to the history log.

    Uses UTC to match capture frame timestamps. Failures are logged but never interrupt the session.
    """
    try:
        history_dir = os.path.dirname(history_file)
        if history_dir:
            os.makedirs(history_dir, exist_ok=True)

        # Naive UTC ISO timestamp (no spaces, no offset), so a consumer can split on the first space and
        # parse it directly. Computed via a timezone-aware value to avoid the deprecated utcnow().
        timestamp = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()

        with open(history_file, "a") as f:
            f.write("{} {}\n".format(timestamp, filter_name))
            f.flush()

    except Exception as e:
        log.warning("Could not write filter history to %s: %s", history_file, e)


# --------------------------------------------------------------------------------------------------
# Graceful shutdown plumbing
# --------------------------------------------------------------------------------------------------
# Set by the signal handler to request a clean shutdown
_stop_requested = False


def _request_stop(signum, frame):
    """Signal handler that asks the session to stop at the next opportunity."""
    global _stop_requested
    _stop_requested = True
    log.info("Stop requested (signal %s), finishing up...", signum)


def _interruptible_sleep(seconds):
    """Sleep for `seconds`, but wake early if a stop was requested.

    Returns True if the full duration elapsed, False if interrupted.
    """
    end_time = time.time() + seconds
    while time.time() < end_time:
        if _stop_requested:
            return False
        time.sleep(min(1.0, end_time - time.time()))
    return True


def frames_to_seconds(frames, fps):
    """Convert a frame COUNT to wall-clock seconds at the given capture frame rate.

    The scheduler drives the wheel on a wall clock; it never receives frames from the capture system.
    Expressing dwell times in frames and converting here lets the UV:NL cadence be stated as a frame
    ratio - e.g. `--uv-frames 10 --check-frames 1` is a 10:1 UV-to-NL ratio - independent of fps, on the
    assumption that capture actually runs at `fps`.
    """
    return frames / fps if fps > 0 else 0.0


# --------------------------------------------------------------------------------------------------
# Wheel movement
# --------------------------------------------------------------------------------------------------
def move_to(wheel, filter_name):
    """Move the wheel to the named filter, log the outcome, and record it in the history log.

    Returns True on success, False otherwise.
    """
    log.info("Switching to '%s'...", filter_name)
    if wheel.set_position(filter_name):
        log.info("Now in '%s'.", wheel.position_name)

        # Record the moment this filter became active, for downstream astrometry to look up per frame
        record_filter(wheel.position_name)
        return True

    log.error("Failed to switch to '%s': %s", filter_name, wheel.last_error)
    return False


def calibration_burst(wheel, frames, fps, label):
    """Dwell in Natural Light for `frames` frames to collect stars for a plate solution.

    `label` is a human-readable phase name for the logs (e.g. "start", "end"). Returns True if the full
    dwell elapsed, False if a stop was requested (either before or during the burst).
    """
    if frames <= 0:
        return not _stop_requested

    if not move_to(wheel, NATURAL_LIGHT_FILTER):
        log.error("Could not enter Natural Light for the %s calibration burst.", label)
        return not _stop_requested

    seconds = frames_to_seconds(frames, fps)
    log.info("Holding Natural Light for %d frames (~%.0f s, %s calibration burst).",
             frames, seconds, label)
    return _interruptible_sleep(seconds)


# --------------------------------------------------------------------------------------------------
# Session
# --------------------------------------------------------------------------------------------------
def run_session(definition_file, fps, calib_frames, uv_frames, check_frames, end_calib_frames,
                park_filter, simulate):
    """Run one whole-night observing session: start calibration, UV/check observing loop, end bracket.

    All dwell durations are frame COUNTS, converted to seconds via `fps` (see frames_to_seconds).

    Phases:
      1. Start calibration burst in Natural Light (`calib_frames`) to build the reference platepar.
      2. Observing loop: UV for `uv_frames`, then a Natural Light drift check for `check_frames`
         (skipped when `check_frames` == 0), repeating until interrupted. The UV:NL frame ratio is
         `uv_frames:check_frames` (e.g. 10:1).
      3. End calibration burst in Natural Light (`end_calib_frames`) to bracket the night, then park
         the wheel on `park_filter`.

    `simulate` selects the no-hardware SimulatedFilterWheel. Returns a process exit code (0 = success).
    """

    if simulate:
        log.info("SIMULATE mode: no hardware will be touched.")
        wheel = SimulatedFilterWheel(definition_file)
    else:
        log.info("Connecting to filter wheel using definition file: %s", definition_file)
        wheel = FilterWheel(definition_file)

    if not wheel.init:
        log.error("Filter wheel initialization failed: %s", wheel.last_error)
        return 1

    log.info("Session plan @ %.3f fps: %d-frame NL start-calibration -> [ %d-frame UV + %d-frame NL "
             "check ] repeating (UV:NL = %d:%d frames) -> %d-frame NL end-calibration -> park on '%s'.",
             fps, calib_frames, uv_frames, check_frames, uv_frames, check_frames, end_calib_frames,
             park_filter)

    try:
        # --- Phase 1: start calibration burst (reference plate solution) ---------------------------
        if not calibration_burst(wheel, calib_frames, fps, "start"):
            log.info("Stopped during start calibration.")
            return 0

        # --- Phase 2: observing loop ---------------------------------------------------------------
        log.info("Entering observing loop. Press Ctrl+C to end the session.")
        while not _stop_requested:

            # UV science block
            if not move_to(wheel, UV_FILTER):
                # If we cannot reach UV, wait briefly and retry rather than spinning
                log.warning("Retrying UV shortly...")
                if not _interruptible_sleep(5):
                    break
                continue

            uv_secs = frames_to_seconds(uv_frames, fps)
            log.info("Holding UV for %d frames (~%.0f s, observing block).", uv_frames, uv_secs)
            if not _interruptible_sleep(uv_secs):
                break

            # Optional short Natural Light drift check between UV blocks
            if check_frames > 0:
                if move_to(wheel, NATURAL_LIGHT_FILTER):
                    check_secs = frames_to_seconds(check_frames, fps)
                    log.info("Holding Natural Light for %d frames (~%.0f s, drift check).",
                             check_frames, check_secs)
                    if not _interruptible_sleep(check_secs):
                        break

    finally:
        # --- Phase 3: end calibration bracket, then park -------------------------------------------
        # Run the end bracket even on Ctrl+C so the night is always bracketed by two plate solutions.
        # Use a plain sleep here because a stop has usually already been requested by this point, which
        # would make the interruptible sleep return immediately.
        if end_calib_frames > 0 and move_to(wheel, NATURAL_LIGHT_FILTER):
            end_secs = frames_to_seconds(end_calib_frames, fps)
            log.info("Holding Natural Light for %d frames (~%.0f s, end calibration bracket).",
                     end_calib_frames, end_secs)
            time.sleep(end_secs)

        log.info("Parking wheel on '%s' before exit...", park_filter)
        move_to(wheel, park_filter)

    log.info("Session finished.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fps", type=float, default=DEFAULT_FPS,
                        help="Capture frame rate used to convert frame counts to dwell time; keep in "
                             "sync with the RMS capture fps (default: %(default)s).")
    parser.add_argument("--calib-frames", type=int, default=DEFAULT_CALIB_FRAMES,
                        help="Natural Light calibration burst at session start, frames "
                             "(default: %(default)s).")
    parser.add_argument("--uv-frames", type=int, default=DEFAULT_UV_FRAMES,
                        help="UV observing block between drift checks, frames. With --check-frames this "
                             "sets the UV:NL frame ratio, e.g. 10:1 (default: %(default)s).")
    parser.add_argument("--check-frames", type=int, default=DEFAULT_CHECK_FRAMES,
                        help="Natural Light drift check between UV blocks, frames; 0 disables periodic "
                             "checks (default: %(default)s).")
    parser.add_argument("--end-calib-frames", type=int, default=DEFAULT_END_CALIB_FRAMES,
                        help="Natural Light calibration burst at session end to bracket the night, "
                             "frames (default: %(default)s).")
    parser.add_argument("--park-filter", type=str, default=UV_FILTER,
                        help="Filter to leave the wheel on at exit (default: %(default)s).")
    parser.add_argument("--definition-file", type=str, default=DEFAULT_DEFINITION_FILE,
                        help="Filter definition CSV (default: %(default)s).")
    parser.add_argument("--history-file", type=str, default=DEFAULT_HISTORY_FILE,
                        help="Path to the filter history log read by downstream astrometry "
                             "(default: %(default)s).")
    parser.add_argument("--simulate", action="store_true",
                        help="Rehearse the schedule with no hardware attached (log/history only).")
    args = parser.parse_args()

    global history_file
    history_file = os.path.expanduser(args.history_file)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")

    # Handle Ctrl+C and termination requests gracefully
    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    return run_session(
        definition_file=os.path.expanduser(args.definition_file),
        fps=args.fps,
        calib_frames=args.calib_frames,
        uv_frames=args.uv_frames,
        check_frames=args.check_frames,
        end_calib_frames=args.end_calib_frames,
        park_filter=args.park_filter,
        simulate=args.simulate,
    )


if __name__ == "__main__":
    sys.exit(main())
