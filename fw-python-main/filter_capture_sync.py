#!/usr/bin/env python3
"""Capture-synced UV / Natural-Light filter cycler.

WHY THIS EXISTS
---------------
Its sibling ``filter_cycle.py`` drives the Optec wheel on a WALL CLOCK: it converts frame counts to
seconds using an assumed fps and is fully decoupled from the capture system. This script instead ties
the wheel to REAL capture progress. RMS writes one FF file (a ~256-frame capture block, ~10 s at 25
fps) per compression cycle into the current night's ``CapturedFiles`` directory; each new FF file is
one "capture event". This watcher counts those events and advances a UV -> Natural Light cadence off
them, so the filter schedule follows the camera instead of a stopwatch.

The default cadence is 10 FF blocks in UV, then 1 FF block in Natural Light (10:1), matching the ratio
in ``filter_cycle.py``. Because each switch fires immediately AFTER an FF block finishes, the wheel
moves in the gap between blocks and is aligned with what is actually being recorded.

    While in UV      : count each new FF block. After ``--uv-events`` blocks (default 10), switch to
                       Natural Light.
    While Natural Light: count each new FF block. After ``--nl-events`` blocks (default 1), switch back
                       to UV.

WHAT IT OUTPUTS
---------------
1. Terminal / console: a line per FF block showing the ACTIVE filter and the running count, plus a
   clear banner on every UV<->Natural Light switch. So at a glance you can always see whether the wheel
   is in UV or in Natural Light.
2. A DEDICATED sync log (``--sync-log``, default ~/RMS_data/filter_capture_sync.log): the same
   messages persisted to their own file, separate from the RMS log and from the filter history file.
3. The filter HISTORY file (``--history-file``, default ~/RMS_data/filter_history.txt): the existing
   downstream-astrometry contract - one "<UTC ISO timestamp> <filter name>" line per switch, written by
   the shared ``filter_cycle.move_to`` helper - so per-frame filter attribution keeps working unchanged.

USAGE
-----
    # Real hardware, default 10:1 UV:NL, watching the default ~/RMS_data/CapturedFiles:
    python3 filter_capture_sync.py

    # Restrict to one station's capture dirs and use a 10:1 cadence explicitly:
    python3 filter_capture_sync.py --station-id NZXXUV --uv-events 10 --nl-events 1

    # Rehearse with NO hardware and NO capture running: fake an FF block every 2 s (sped up):
    python3 filter_capture_sync.py --simulate --simulate-ff 2

This script is meant to run ALONGSIDE RMS capture (e.g. launched from start_nzxxuv.sh), for the whole
night, and to be stopped with Ctrl+C / SIGTERM when capture ends.
"""

import os
import sys
import time
import signal
import logging
import argparse

# Make sibling modules importable when launched from any working directory.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from fw import FilterWheel

# Reuse the wheel-movement + history-logging plumbing already written for filter_cycle.py so both
# schedulers move the wheel and record the downstream history file in exactly the same way.
import filter_cycle
from filter_cycle import (
    SimulatedFilterWheel,
    move_to,
    UV_FILTER,
    NATURAL_LIGHT_FILTER,
)


# Defaults for the capture-directory watch. FF files are named "FF_<station>_<date>_..." and land in
# <data_dir>/<captured_dir>/<stationID>_<datetime>/ while capture runs.
DEFAULT_DATA_DIR = os.path.expanduser("~/RMS_data")
DEFAULT_CAPTURED_DIR = "CapturedFiles"

# Default cadence: 10 FF blocks in UV per 1 FF block in Natural Light (10:1).
DEFAULT_UV_EVENTS = 10
DEFAULT_NL_EVENTS = 1

# Dedicated log for this scheduler (separate from the RMS log and the filter history file).
DEFAULT_SYNC_LOG = os.path.join(DEFAULT_DATA_DIR, "filter_capture_sync.log")

# The filter definition CSV lives next to this script.
DEFAULT_DEFINITION_FILE = os.path.join(SCRIPT_DIR, "definition_file.csv")

# Filter history file (downstream astrometry contract). Same default as filter_cycle.py.
DEFAULT_HISTORY_FILE = filter_cycle.DEFAULT_HISTORY_FILE


log = logging.getLogger("filter_capture_sync")


# --------------------------------------------------------------------------------------------------
# Graceful shutdown
# --------------------------------------------------------------------------------------------------
_stop_requested = False


def _request_stop(signum, frame):
    """Signal handler that asks the watch loop to stop at the next opportunity."""
    global _stop_requested
    _stop_requested = True
    log.info("Stop requested (signal %s), finishing up...", signum)


def _interruptible_sleep(seconds):
    """Sleep for ``seconds`` but wake early if a stop was requested."""
    end_time = time.time() + seconds
    while time.time() < end_time:
        if _stop_requested:
            return
        time.sleep(min(0.5, max(0.0, end_time - time.time())))


# --------------------------------------------------------------------------------------------------
# Capture-directory watching
# --------------------------------------------------------------------------------------------------
def find_active_night_dir(captured_path, station_id):
    """Return the most recently modified capture night directory, or None if none exists yet.

    RMS creates one directory per night under ``captured_path`` named "<stationID>_<datetime>". The
    active one is simply the newest by modification time. ``station_id`` (optional) restricts the search
    to directories whose name starts with that station code.
    """
    if not os.path.isdir(captured_path):
        return None

    newest_dir = None
    newest_mtime = -1.0
    for name in os.listdir(captured_path):
        if station_id and not name.startswith(station_id):
            continue
        path = os.path.join(captured_path, name)
        if not os.path.isdir(path):
            continue
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if mtime > newest_mtime:
            newest_mtime = mtime
            newest_dir = path

    return newest_dir


def list_ff_files(dir_path):
    """Return the set of FF capture files currently in ``dir_path`` (names starting with 'FF_')."""
    try:
        return {name for name in os.listdir(dir_path) if name.startswith("FF_")}
    except OSError:
        return set()


# --------------------------------------------------------------------------------------------------
# Cadence
# --------------------------------------------------------------------------------------------------
class Cadence:
    """Tracks the UV <-> Natural Light schedule and drives the wheel on each FF capture event.

    Starts in UV. Each ``on_ff_event`` counts one captured FF block against the active filter's target
    (``uv_events`` for UV, ``nl_events`` for Natural Light) and, once the target is reached, switches to
    the other filter via the shared ``filter_cycle.move_to`` helper (which also records the switch in the
    downstream filter history file).
    """

    def __init__(self, wheel, uv_events, nl_events):
        self.wheel = wheel
        self.uv_events = uv_events
        self.nl_events = nl_events
        self.state = UV_FILTER
        self.count = 0

    def _target(self):
        return self.uv_events if self.state == UV_FILTER else self.nl_events

    def start(self):
        """Move the wheel to the initial UV filter and log the plan."""
        log.info("Cadence: %d FF block(s) in UV per %d FF block(s) in Natural Light (%d:%d).",
                 self.uv_events, self.nl_events, self.uv_events, self.nl_events)
        if move_to(self.wheel, UV_FILTER):
            self.state = UV_FILTER
        else:
            # Record intended state even if the move failed, so counting/labelling still proceeds; the
            # first switch attempt will surface the hardware error again.
            log.error("Could not enter initial UV filter: %s", getattr(self.wheel, "last_error", ""))
        self.count = 0

    def on_ff_event(self, ff_name):
        """Register one captured FF block; switch filters when the active target is reached."""
        self.count += 1
        target = self._target()

        # Per-block status line: always makes the ACTIVE filter visible on the terminal and in the log.
        log.info("FF captured: %-38s | filter = %-13s (%s %d/%d)",
                 ff_name, self.state, self.state, self.count, target)

        if self.count < target:
            return

        # Target reached -> switch to the other filter.
        next_filter = NATURAL_LIGHT_FILTER if self.state == UV_FILTER else UV_FILTER
        log.info("---- %d %s block(s) captured -> switching to %s ----",
                 target, self.state, next_filter)
        if move_to(self.wheel, next_filter):
            self.state = next_filter
            self.count = 0
        else:
            # Leave the count at/above target so the switch is retried on the next FF event rather than
            # silently continuing in the wrong filter.
            log.error("Switch to %s failed (%s); will retry on next FF block.",
                      next_filter, getattr(self.wheel, "last_error", ""))


# --------------------------------------------------------------------------------------------------
# Run loops
# --------------------------------------------------------------------------------------------------
def run_watch(cadence, captured_path, station_id, poll_interval, count_existing):
    """Watch the capture directory and feed each new FF file to ``cadence`` until a stop is requested."""
    log.info("Watching for FF capture blocks under: %s%s",
             captured_path, " (station {})".format(station_id) if station_id else "")

    current_dir = None
    seen = set()

    while not _stop_requested:
        night_dir = find_active_night_dir(captured_path, station_id)

        if night_dir is None:
            log.info("No capture directory yet; waiting for RMS capture to start...")
            _interruptible_sleep(poll_interval)
            continue

        # Follow into a newly created night directory. Snapshot its existing FF files so pre-existing
        # blocks (e.g. a resumed night) are not counted, unless --count-existing was given.
        if night_dir != current_dir:
            current_dir = night_dir
            existing = list_ff_files(current_dir)
            seen = set() if count_existing else set(existing)
            log.info("Active capture directory: %s (%d FF file(s) already present%s).",
                     current_dir, len(existing),
                     ", counting them" if count_existing else ", ignored")

        # Detect and process new FF files in creation order.
        for ff_name in sorted(list_ff_files(current_dir) - seen):
            seen.add(ff_name)
            cadence.on_ff_event(ff_name)
            if _stop_requested:
                break

        _interruptible_sleep(poll_interval)


def run_simulated_ff(cadence, interval):
    """Synthesize a fake FF capture event every ``interval`` seconds (for testing without capture)."""
    log.info("SIMULATE FF mode: generating a fake FF block every %.1f s (no capture directory read).",
             interval)
    counter = 0
    while not _stop_requested:
        _interruptible_sleep(interval)
        if _stop_requested:
            break
        counter += 1
        cadence.on_ff_event("FF_SIMULATED_{:06d}.fits".format(counter))


# --------------------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=str, default=DEFAULT_DATA_DIR,
                        help="RMS data directory containing the captured-files folder "
                             "(default: %(default)s).")
    parser.add_argument("--captured-dir", type=str, default=DEFAULT_CAPTURED_DIR,
                        help="Name of the captured-files subfolder under --data-dir "
                             "(default: %(default)s).")
    parser.add_argument("--station-id", type=str, default=None,
                        help="Only watch night directories whose name starts with this station code "
                             "(default: watch the newest directory regardless of station).")
    parser.add_argument("--uv-events", type=int, default=DEFAULT_UV_EVENTS,
                        help="Number of FF capture blocks to stay in UV before switching to Natural "
                             "Light (default: %(default)s).")
    parser.add_argument("--nl-events", type=int, default=DEFAULT_NL_EVENTS,
                        help="Number of FF capture blocks to stay in Natural Light before switching "
                             "back to UV (default: %(default)s).")
    parser.add_argument("--poll-interval", type=float, default=2.0,
                        help="Seconds between capture-directory scans (default: %(default)s).")
    parser.add_argument("--count-existing", action="store_true",
                        help="Also count FF files already present when the watcher starts (default: "
                             "ignore pre-existing files and only react to new ones).")
    parser.add_argument("--park-filter", type=str, default=UV_FILTER,
                        help="Filter to leave the wheel on at exit (default: %(default)s).")
    parser.add_argument("--definition-file", type=str, default=DEFAULT_DEFINITION_FILE,
                        help="Filter definition CSV (default: %(default)s).")
    parser.add_argument("--history-file", type=str, default=DEFAULT_HISTORY_FILE,
                        help="Filter history log read by downstream astrometry "
                             "(default: %(default)s).")
    parser.add_argument("--sync-log", type=str, default=DEFAULT_SYNC_LOG,
                        help="Dedicated log file for this capture-sync scheduler "
                             "(default: %(default)s).")
    parser.add_argument("--simulate", action="store_true",
                        help="Use the no-hardware simulated wheel (log/history only).")
    parser.add_argument("--simulate-ff", type=float, default=0.0, metavar="SECONDS",
                        help="Instead of watching the capture directory, synthesize a fake FF block "
                             "every SECONDS (for end-to-end testing without capture running).")
    args = parser.parse_args()

    # Point the shared history-logging helper at the requested history file so move_to() records there.
    filter_cycle.history_file = os.path.expanduser(args.history_file)

    # Log to both the console and the dedicated sync-log file.
    sync_log_path = os.path.expanduser(args.sync_log)
    sync_log_dir = os.path.dirname(sync_log_path)
    if sync_log_dir:
        os.makedirs(sync_log_dir, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    file_handler = logging.FileHandler(sync_log_path)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    log.info("Dedicated capture-sync log: %s", sync_log_path)
    log.info("Filter history (downstream contract): %s", filter_cycle.history_file)

    # Handle Ctrl+C / termination gracefully.
    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    # Connect to the wheel (real or simulated).
    definition_file = os.path.expanduser(args.definition_file)
    if args.simulate:
        log.info("SIMULATE mode: no hardware will be touched.")
        wheel = SimulatedFilterWheel(definition_file)
    else:
        log.info("Connecting to filter wheel using definition file: %s", definition_file)
        wheel = FilterWheel(definition_file)

    if not wheel.init:
        log.error("Filter wheel initialization failed: %s", wheel.last_error)
        return 1

    cadence = Cadence(wheel, uv_events=args.uv_events, nl_events=args.nl_events)
    cadence.start()

    try:
        if args.simulate_ff > 0:
            run_simulated_ff(cadence, args.simulate_ff)
        else:
            captured_path = os.path.join(os.path.abspath(os.path.expanduser(args.data_dir)),
                                         args.captured_dir)
            run_watch(cadence, captured_path, args.station_id, args.poll_interval, args.count_existing)
    finally:
        log.info("Parking wheel on '%s' before exit...", args.park_filter)
        move_to(wheel, args.park_filter)
        log.info("Capture-sync session finished.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
