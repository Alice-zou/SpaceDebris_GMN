# NZXXUV UV Meteor Station — Workflow & Data Reference

This document describes the **end-to-end workflow** for the NZXXUV station on this Raspberry Pi 5:
from starting the camera RTSP stream, through running capture, the UV filter-wheel cycling, the
custom UV meteor-detection logic, and finally what data is produced and where it is stored.

It reflects the **customisations made to this machine** (Lisbon location, uploads disabled, Optec
filter wheel integration, and the "detect meteors in UV even with no stars" logic).

---

## 0. System at a glance

```
  FLIR/Spinnaker camera (GigE)
        │  PySpin (Python 3.10.14)
        ▼
  spinnaker_to_rtsp.py ──► MediaMTX ──►  rtsp://127.0.0.1:8554/live
        │                                        │
   (RTSP/ folder)                                │  RMS reads this stream
                                                 ▼
                          start_nzxxuv.sh NZXXUV   (wrapper: wheel + capture)
                                                 │
                    ┌────────────────────────────┼───────────────────────────┐
                    ▼                             ▼                           ▼
       MultiCamLinux/StartCapture.sh     filter_cycle.py (UV/NL)     (logs to terminal
         └► python -m RMS.StartCapture    writes filter_history.txt    + log files)
            (vRMS venv, 3.13)
                    │
                    ▼  captures all night, then auto-reprocesses
        FF/FS/FT files ──► detection ──► ML filter ──► calibration ──► archive
                    │
                    ▼
        ~/RMS_data/NZXXUV/{CapturedFiles,ArchivedFiles,FramesFiles,TimeFiles,logs}
```

**One station runs on this Pi:** `NZXXUV` (UV), which has the filter wheel and the UV detection
behaviour. Its config is reachable as the Desktop shortcut `~/Desktop/NZXXUV.config`.

---

## 1. Components and where they live

| Component | Location | Runs on (interpreter) |
|---|---|---|
| Camera → RTSP streamer | `~/Desktop/Workspace/RTSP/spinnaker_to_rtsp.py` | pyenv **3.10.14** (has PySpin) |
| RTSP launcher | `~/Desktop/Workspace/RTSP/start_spinnaker_rtsp.sh` | bash |
| RTSP server | `~/Desktop/Workspace/Mediamtx/mediamtx` (+ `mediamtx.yml`) | binary |
| RMS capture code | `~/source/RMS` → symlink → `~/Desktop/Workspace/RMS` | **vRMS** venv (3.13) |
| NZXXUV launcher | `~/Desktop/Workspace/start_nzxxuv.sh` | bash |
| RMS capture launcher (called by the wrapper) | `RMS/Scripts/MultiCamLinux/StartCapture.sh` | bash |
| NZXXUV config (active) | `~/source/Stations/NZXXUV/.config` (= `~/Desktop/NZXXUV.config`) | — |
| Filter wheel control (in-capture) | `RMS/RMS/BufferedCapture.py` → `fw-python-main/fw.py` | **vRMS** venv (3.13) |
| Filter wheel driver classes | `fw-python-main/{fw,hsfw,ifw}.py` + `definition_file.csv` | — |
| Filter history log | `~/RMS_data/filter_history.txt` | written by filter_cycle |
| Detection logic | `RMS/RMS/DetectStarsAndMeteors.py` | vRMS venv |

---

## 2. Step 1 — Start the RTSP stream

**Run:**
```bash
~/Desktop/Workspace/RTSP/start_spinnaker_rtsp.sh
```

**What it triggers, in order:**
1. Optimises the network for GigE Vision: sets `eth0` MTU to **9000** (jumbo frames) and raises the
   kernel socket buffers (`net.core.rmem_max`/`wmem_max` = 16 MB). *(Requires `sudo`; it prompts.)*
2. Launches `spinnaker_to_rtsp.py` with the **3.10.14** Python (`~/.pyenv/versions/3.10.14/bin/python`).

**What `spinnaker_to_rtsp.py` does:**
- Reads `RTSP/spinnaker.config` (camera serial `26176619`, `3×3` binning, output `1280×720 @ 25 fps`,
  exposure `40 ms`, gain `24 dB`).
- Opens the FLIR camera via **PySpin**, applies binning/resize, and pushes frames into a locally-spawned
  **MediaMTX** server, publishing the stream at:
  ```
  rtsp://127.0.0.1:8554/live
  ```

**Terminal output (typical):**
```
Optimizing ethernet interface eth0 for GigE Vision...
Starting Spinnaker RTSP streamer...
[Config] ... camera opened, serial 26176619 ...
[MediaMTX] server started on :8554
... streaming 1280x720@25 ...
```

**How to confirm it is up:**
```bash
pgrep -af "spinnaker_to_rtsp|mediamtx"     # both processes present
ss -ltnp | grep 8554                       # MediaMTX listening on 8554
```

> ⚠️ **Common error:** `ModuleNotFoundError: No module named 'PySpin'`. PySpin is installed **only** in
> pyenv `3.10.14`. Running the script with any other Python (e.g. default `python3` = 3.13) fails.
> Always launch via `start_spinnaker_rtsp.sh` or with the 3.10.14 interpreter explicitly.

---

## 3. Step 2 — Start capture (NZXXUV)

**Run the wrapper** (starts the wheel *and* capture together):
```bash
~/Desktop/Workspace/start_nzxxuv.sh NZXXUV
```

> ⚠️ **Do not run `StartCapture.sh` directly** for NZXXUV. RMS's `StartCapture.sh` only runs capture —
> it does **not** launch the filter wheel (an RMS update overwrote the old in-launcher integration).
> The wheel launch now lives in the `start_nzxxuv.sh` wrapper, which survives RMS updates. Launch it
> **near/after dusk** so the wheel's start-calibration burst aligns with when capture actually records.

**What the wrapper does, in order:**
1. **Starts the filter wheel** (NZXXUV only — gated by `FILTERWHEEL_STATIONS="NZXXUV"`): launches
   `fw-python-main/filter_cycle.py` in the background with the **vRMS** venv Python and prints:
   ```
   Starting filter wheel scheduler for NZXXUV...
   Filter wheel scheduler started (PID 95896), logging to
     /home/rms/RMS_data/logs/<date>_NZXXUV_filterwheel.txt
   ```
2. Runs capture in the foreground by calling `StartCapture.sh NZXXUV`, which prints `Starting RMS...`,
   activates the **vRMS** venv, and runs `python -u -m RMS.StartCapture -c <NZXXUV config>`.
3. A `trap … EXIT` guarantees the wheel scheduler is signalled on exit — it runs its **end-calibration
   bracket** and **parks at UV** — whenever capture ends (dawn, Ctrl-C, or SIGTERM).

**What RMS StartCapture does at startup (from the real run):**
```
Loading config file: /home/rms/source/Stations/NZXXUV/.config
Creating directory: /home/rms/RMS_data/NZXXUV
...-INFO-StartCapture- Program start
...-INFO-StartCapture- Station code: NZXXUV
...-INFO-StartCapture- Program version: 20260525_...
...-INFO-EventMonitor- EventMonitor was started
```
- It computes the capture window from the **Lisbon** coordinates (38.6929 N, −9.2157 E). If it is
  night, capture starts immediately; if daytime, it waits until dusk.
- It connects to `rtsp://127.0.0.1:8554/live` and begins recording.

> ℹ️ **Uploads are disabled** for NZXXUV (`upload_enabled: false`), so no meteor data is sent to the
> GMN server. You may still see harmless warnings for **mask/platepar download** and the **event
> monitor**, which reach out to `gmn.uwo.ca` independently of uploads.

---

## 4. The filter wheel cycle (NZXXUV only)

`filter_cycle.py` drives the Optec HSFW wheel while capture runs. It no longer uses a fixed
UV-4-min / NL-1-min duty cycle — it now runs a **whole-night session** built around astrometry.

**Why the change:** stars are invisible in UV, so a debris/meteor streak in a UV frame cannot be
plate-solved on its own. But for a camera that does not move, the mapping *pixel → (azimuth, altitude)*
is **constant in time**, so a streak's sky position = its pixel coordinates + the frame's UTC + a plate
solution built from **Natural Light** frames taken at an *unrelated* time. Natural Light is therefore a
calibration task, not something that must coincide with a detection — which lets UV run almost the whole
night. (Full reasoning in **`fw-python-main/FILTER_CYCLE.md`**.)

Dwell durations are specified in **capture frames** (not seconds) and converted to time via the nominal
`--fps` (default **25.0**; keep in sync with the RMS capture `fps`). This lets the UV/NL cadence be
stated as a **frame ratio** — e.g. `--uv-frames 10 --check-frames 1` is a **10:1** UV-to-NL ratio.

**Session phases:**
1. **Start calibration burst** — Natural Light for `--calib-frames` (default **4500**): collect stars
   across the field to build the reference plate solution for the night.
2. **Observing loop** — UV for `--uv-frames` (default **2500**), then an optional short Natural Light
   **drift check** for `--check-frames` (default **250**; `0` disables checks), repeating until stopped.
   The default UV:NL frame ratio is **10:1**.
3. **End calibration burst** — Natural Light for `--end-calib-frames` (default **3000**) on shutdown,
   which **brackets** the night: if the start and end plate solutions agree, the pointing held all night
   and every UV detection in between is trustworthy on the one reference plate. The wheel is then parked
   (default **UV**, `--park-filter`). The bracket + park run even on Ctrl-C.

- On every successful move it appends a line to **`~/RMS_data/filter_history.txt`**:
  ```
  2026-07-06T21:00:03.512847 Natural Light   ← start calibration burst
  2026-07-06T21:03:03.771020 UV              ← observing block
  2026-07-06T22:03:04.004311 Natural Light   ← drift check
  2026-07-06T22:03:34.219880 UV
  ```
  Format: `<UTC ISO timestamp> <filter name>` — the exact time each filter became active. UV lines are
  science intervals; Natural Light lines are calibration / drift-check intervals.
- A no-hardware rehearsal mode (`--simulate`) exercises the whole schedule and history log without a
  wheel attached.

This history file is the bridge to the detection stage (below).

---

## 5. During capture — what is written

As capture runs, RMS produces, per ~256-frame block (≈10.24 s at 25 fps), into
`~/RMS_data/NZXXUV/CapturedFiles/NZXXUV_<start>/`:

| File | What it is |
|---|---|
| `FF_NZXXUV_YYYYMMDD_HHMMSS_mmm_<frame>.fits` | **FF** compressed frame — max/avg/std/maxframe images for the block (~3.7 MB) |
| `FS_..._fieldsum.bin` | **FS** field-sum (per-frame brightness) used for calibration/plots |
| `.config` | a copy of the config used for this night |

Frame snapshots (for the timelapse) are saved separately under
`~/RMS_data/NZXXUV/FramesFiles/<YEAR>/<DOY>/<DOY>_<HH>/NZXXUV_<time>_n.jpg`
(the `_n` suffix = night frame). Frame-time (**FT**) files go under `TimeFiles/`.

**FF file name decoded:** `FF_NZXXUV_20260706_013730_073_0000000.fits`
= station `NZXXUV`, UTC `2026-07-06 01:37:30.073`, first frame number `0000000`.

**Terminal / log during capture** is mostly RMS INFO lines (block saved, FPS, etc.). Detection output
(including `detecting meteors`) does **not** appear yet — it runs *after* the capture window ends.

---

## 6. Custom UV detection logic

Standard RMS only runs meteor detection on an FF file if it has **≥ `ff_min_stars`** stars
(NZXXUV threshold = **20**). In UV, stars are essentially invisible, so this would skip everything.

The customised `RMS/DetectStarsAndMeteors.py` changes the rule to:

```python
filter_name = getFilterForTime(config, capture_dt)   # looks up filter_history.txt by FF time
if (filter_name == 'UV') or (stars >= config.ff_min_stars):
    log.info('detecting meteors')
    print('detecting meteors', flush=True)            # also shown in the terminal
    ... run meteor detection ...
```

- `getFilterForTime()` reads **`~/RMS_data/filter_history.txt`** (fixed machine-wide path — one physical
  wheel serves the Pi) and returns the filter that was active **when that FF was captured**.
- If the filter was **UV** → meteor detection runs **regardless of star count**.
- For any other filter (e.g. Natural Light) the normal "≥ 20 stars" rule applies.
- Every time detection runs it logs **and prints** `detecting meteors`.

**What you see in the log/terminal for a UV frame with few stars:**
```
Detected stars: 6
detecting meteors                                     ← printed to terminal
UV filter in use, detecting meteors regardless of star count...
FF_NZXXUV_..._detected meteors: 0
```

---

## 7. After the capture session ends — auto reprocessing

When the capture window closes (dawn), or the process is stopped, RMS runs **Reprocess** on the night's
`CapturedFiles` directory. Observed sequence:

1. **Detection** — `DetectStarsAndMeteors` runs on all FF files across `num_cores` workers:
   `Finishing up the detection, N files to process...` → `Running the detection on 2 cores...`
   Produces `CALSTARS_*.txt` (extracted stars) and `FTPdetectinfo_*_unfiltered.txt` (raw detections).
2. **ML filtering** — `MLFilter` (TF-Lite) classifies detections as real meteors vs false positives:
   `FTPdetectinfo filtered, X/Y detections classified as real meteors`. Produces the filtered
   `FTPdetectinfo_*.txt`.
3. **Calibration artefacts** — platepar lookup, flat-field attempt, field-sum plots.
4. **Timelapse** — an `*.mp4` from the saved night frames.
5. **Config audit + observation summary** — `*_config_audit_report.txt`, `*_observation_summary.{txt,json}`.
6. **Archive** — `ArchiveDetections` copies the results into `ArchivedFiles/` and creates
   `*_imgdata.tar.bz2` and `*_metadata.tar.bz2`.
7. **Upload** — *would* happen here, but is **disabled** for NZXXUV.

If `reboot_after_processing: true`, the Pi reboots after this completes.

---

## 8. Where data is stored

Per-station root: **`~/RMS_data/NZXXUV/`**

```
~/RMS_data/
├── filter_history.txt          ← machine-wide filter wheel log (UV / Natural Light + timestamps)
├── logs/                       ← filter wheel logs: <date>_NZXXUV_filterwheel.txt
└── NZXXUV/
    ├── CapturedFiles/NZXXUV_<start>/   ← raw FF/FS files + reprocess outputs (kept until space needed)
    ├── ArchivedFiles/NZXXUV_<start>/   ← final results dir + *_imgdata.tar.bz2 / *_metadata.tar.bz2
    ├── FramesFiles/<year>/<doy>/...    ← saved night frame JPEGs (for timelapse)
    ├── TimeFiles/<year>/...            ← frame-time (FT) files
    └── logs/                           ← RMS logs: log_NZXXUV_<date>.log, detection_log_<date>.log
```

- **CapturedFiles** holds the heavy raw **FF** frames (~3.7 MB each). RMS's quota manager deletes the
  oldest of these automatically when disk fills; the derived results in ArchivedFiles are kept longer.
- **ArchivedFiles** is the "night result" — small summary/plots/detections plus the two `.tar.bz2`
  bundles that would normally be uploaded.

---

## 9. What the stored data looks like

### 9a. A finished ArchivedFiles night directory
```
CALSTARS_NZXXUV_<night>.txt                    extracted stars per FF
FTPdetectinfo_NZXXUV_<night>.txt               final (ML-filtered) meteor detections
FTPdetectinfo_NZXXUV_<night>_unfiltered.txt    raw detections before ML filter
FS_..._fieldsums.tar.bz2                       field sums (bundled)
NZXXUV_<night>_captured_stack.jpg              all-night max-pixel stack
NZXXUV_<night>_CAPTURED_thumbs.jpg             thumbnail grid of captured FFs
NZXXUV_<night>_DETECTED_thumbs.jpg             thumbnail grid of detected events
NZXXUV_<night>_ff_intervals.png                FF timing/coverage plot
NZXXUV_<night>_fieldsums.png / _noavg.png      sky brightness over the night
NZXXUV_<night>_timelapse.mp4                   night timelapse video
NZXXUV_<night>_config_audit_report.txt         config vs template audit
NZXXUV_<night>_observation_summary.{txt,json}  machine + session summary
NZXXUV_<night>_logs.tar.bz2                     bundled logs
mask.bmp, .config                              inputs used for the night
NZXXUV_<night>_imgdata.tar.bz2                 image bundle  (upload payload)
NZXXUV_<night>_metadata.tar.bz2               metadata bundle (upload payload)
```

### 9b. `FTPdetectinfo` (the detections list) — header
```
Meteor Count = 000000
Processed with RMS 1.0 20260525_... on 2026-07-06 01:30:11 UTC
FF  folder = /home/rms/RMS_data/NZXXUV/CapturedFiles/NZXXUV_20260706_012808_960600
Cam# Meteor# #Segments fps hnr mle bin Pix/fm Rho Phi
Per segment:  Frame# Col Row RA Dec Azim Elev Inten Mag Bcknd SNR NSatPx
```
`Meteor Count = 0` here because the test frames were blank — but detection **ran** (that's the point of
the UV fix). Real meteors would be listed with per-segment centroids.

### 9c. `observation_summary.txt` — excerpt
```
stationID          : NZXXUV
hardware_version   : raspberry pi 5 model b rev 11
start_time         : 2026-07-06 01:28:09+00:00
time_start_ephem   : 2026-07-06 01:28:21
time_end_ephem     : 2026-07-06 04:47:33
total_fits         : 6
clock_synchronized : True
storage_used_gb    : 42.72   storage_free_gb : 182.2
```

### 9d. `filter_history.txt` — the UV/Natural-Light record
```
2026-07-06T01:28:14.959462 UV
2026-07-06T01:41:20.836055 Natural Light
2026-07-06T01:42:25.895176 UV
```

---

## 10. Boot autostart (unattended)

On boot the whole stack now comes up on its own — you do **not** have to run anything by hand. The chain:

```
autostart .desktop → ~/Desktop/RMS_FirstRun.sh  (autorun flag = 1 → self-update, then:)
   → ~/Desktop/RMS_StartCapture.sh   (symlink, now points at ↓)
     → ~/Desktop/Workspace/boot_start_all.sh   (local orchestrator, outside the RMS repo)
         1. start Spinnaker→RTSP stream, then WAIT for :8554 to come up
            (this also lets eth0 settle at MTU 9000)
         2. NZXXUV  → start_nzxxuv.sh NZXXUV         (capture; the wheel is driven inside capture)
```

**Why the orchestrator exists:** the stock RMS multi-cam launcher (`RMS_StartCapture_MCP.sh`) loops
every station in `~/source/Stations/*` with plain `StartCapture.sh`, which for NZXXUV would (a) never
start its RTSP video source and (b) never start the filter wheel. `boot_start_all.sh` fixes both and
lives **outside** the RMS repo so RMS updates can't overwrite it.

- The change is just a repointed symlink: `~/Desktop/RMS_StartCapture.sh → boot_start_all.sh`.
- **To revert to stock behaviour:** `ln -sfn "$(cat ~/Desktop/Workspace/.RMS_StartCapture.sh.orig-target)" ~/Desktop/RMS_StartCapture.sh`
- **To dry-run the boot sequence** (launches nothing, no sleeps): `DRY_RUN=1 ~/Desktop/Workspace/boot_start_all.sh`
- Boot relies on **passwordless sudo** (present) for the RTSP launcher's eth0/sysctl tuning, so nothing
  prompts on a headless boot.

> ℹ️ **Manual start still works** and is unchanged — use it when you launch by hand near/after dusk
> (see §11). Boot autostart and manual start do the same thing; just don't run both at once.

---

## 11. Quick reference

**Start everything manually (order matters — stream first; boot does this for you, see §10):**
```bash
~/Desktop/Workspace/RTSP/start_spinnaker_rtsp.sh   # 1. camera → RTSP
~/Desktop/Workspace/start_nzxxuv.sh NZXXUV         # 2. wheel + capture (wrapper; NOT StartCapture.sh)
```

**Key logs:**
```bash
~/RMS_data/NZXXUV/logs/log_NZXXUV_<date>.log        # main capture + reprocess log
~/RMS_data/NZXXUV/logs/detection_log_<date>.log     # detection subprocess log
~/RMS_data/logs/<date>_NZXXUV_filterwheel.txt       # filter wheel cycle log
~/RMS_data/filter_history.txt                       # UV / Natural Light timeline
```

**Verify the UV detection is working:**
```bash
grep -nE "detecting meteors|UV filter in use|Detected stars:" \
  ~/RMS_data/NZXXUV/logs/detection_log_*.log
```
Success = `Detected stars: <under 20>` followed by `detecting meteors` / `UV filter in use...`.

**Key config values (NZXXUV):** station `NZXXUV`, lat `38.6929`, lon `-9.2157`, elev `3.58`,
`data_dir ~/RMS_data/NZXXUV`, `ff_min_stars 20`, `fps 25`, `1280×720`, `upload_enabled false`.

---

## 12. Customisations made to this station (summary)

| Change | File(s) |
|---|---|
| **Boot autostart** brings up the RTSP stream + wheel + capture unattended (RTSP first, then NZXXUV via the wrapper); survives RMS updates | `~/Desktop/Workspace/boot_start_all.sh` + repointed `~/Desktop/RMS_StartCapture.sh` symlink |
| Detect meteors in **UV regardless of star count**; log/print `detecting meteors` | `RMS/RMS/DetectStarsAndMeteors.py` |
| Filter looked up by **capture time** from a machine-wide history log | `DetectStarsAndMeteors.py` (`getFilterForTime`) + `~/RMS_data/filter_history.txt` |
| **Filter wheel cycler** — whole-night session: NL calibration bursts **bracket** the UV observing loop (+ optional drift checks) for astrometry; records history, parks at UV on exit | `fw-python-main/filter_cycle.py`, `FILTER_CYCLE.md` |
| Filter wheel **auto-starts with NZXXUV capture** via a wrapper (gated per station; survives RMS updates) | `~/Desktop/Workspace/start_nzxxuv.sh` |
| **Uploads disabled** to GMN server | `~/source/Stations/NZXXUV/.config` (`upload_enabled: false`) |
| Location set to **Lisbon** | `~/source/Stations/NZXXUV/.config` (lat/lon/elev) |
| **Desktop shortcut** to the live config; removed duplicate copies | `~/Desktop/NZXXUV.config` |

*Last verified end-to-end on 2026-07-06 by running the real StartCapture and reprocessing 6 captured
FF files: `detecting meteors` printed to the terminal for UV frames with 5–6 stars (below the 20
threshold).*
