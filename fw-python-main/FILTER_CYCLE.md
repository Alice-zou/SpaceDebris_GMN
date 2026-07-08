# Filter cycle: UV space-debris observing with Natural Light astrometry

`filter_cycle.py` drives the Optec filter wheel through a **whole-night observing session** so that
space-debris streaks captured in **UV** can be given precise sky coordinates using stars captured in
**Natural Light**. This document explains the reasoning behind the design, not just how to run it.

---

## 1. The problem

The camera detects space debris by the aluminium spectral signature, which shows up through a **UV
filter**. But stars are essentially invisible in UV. So when a debris streak lands in a UV frame, that
frame contains **no reference stars**, and you cannot plate-solve it to find out *where on the sky* the
streak was. Without a sky position, a detected streak is nearly useless.

The naive fix — periodically switch to Natural Light and "compare the location" (the original 4 min UV
/ 1 min NL cycle) — is both too costly (20% of observing time lost) and conceptually wrong: the debris
is long gone by the time the wheel finishes moving, so you never get debris and stars in the same
frame anyway.

## 2. The key insight

> **For a camera that does not move, the mapping `pixel → (azimuth, altitude)` is constant in time.**

A fixed camera always maps a given pixel to the same point on the local sky dome (same azimuth and
altitude), regardless of *when* the frame was taken or *what* is in it. The stars drift through the
field as the Earth rotates, but the pixel→(az, alt) relationship — the **plate solution**, stored in an
RMS "platepar" — does not.

Therefore the sky position of a debris streak is fully determined by:

```
streak sky position  =  f( streak pixel coordinates,     # measured in the UV frame
                            frame UTC timestamp,          # from the capture system
                            plate solution )              # built from Natural Light stars
```

The stars used to *build* the plate solution can be captured at a **completely unrelated time** from
the debris. We do **not** need stars in the same frame as the streak. We only need enough Natural Light
frames to (a) establish the plate solution and (b) confirm the camera did not move.

To turn `(az, alt)` into `(RA, Dec)` you also need the timestamp — that is the only time-dependent
step, and it is pure arithmetic. This is why **accurate time is critical**: a 1-second clock error is
~15 arcseconds of position error near the equator.

## 3. Two shared-optics caveats

The UV and Natural Light channels are **filters on one wheel, sharing one lens**, so plate scale and
distortion are common to both. Two second-order effects remain:

1. **Filter registration offset `(dx, dy)`** — a filter's wedge/non-parallelism can shift the image by
   a small, *constant* amount (sub-pixel to a few pixels). Measure it once (image a source visible
   through both filters, or take it from the filter spec) and subtract it from UV pixel coordinates
   before applying the NL-derived plate solution.
2. **Focus offset** — different glass thickness can shift focus between filters. This blurs streak
   *endpoints* rather than moving them, so it degrades measurement precision, not accuracy. If UV
   defocus turns out to be significant, add a per-filter focus offset in the capture setup.

Neither affects the core scheme; both are one-time calibrations.

## 4. Session model (implemented by this script)

The camera is set up and left **fixed for the whole ~10-hour night**. The wheel runs three phases:

Dwell durations are specified in **capture frames**, not seconds. The scheduler drives the wheel on a
wall clock and is decoupled from the capture system, so a frame count is converted to a dwell time
using the nominal `--fps` (keep it in sync with the RMS capture `fps`). Working in frames lets the
UV/Natural-Light cadence be stated as a **frame ratio** — e.g. `--uv-frames 10 --check-frames 1` is a
**10:1** UV-to-NL ratio.

| Phase | Filter | Duration flag | Purpose |
|-------|--------|---------------|---------|
| 1. Start calibration burst | Natural Light | `--calib-frames` (def 4500) | Collect stars across the field to build the **reference plate solution** for the night. |
| 2. Observing loop | UV, with short NL checks | `--uv-frames` (def 2500) / `--check-frames` (def 250) | Spend almost all night in UV. Optional short NL "drift checks" between UV blocks re-verify the pointing. The default UV:NL frame ratio is **10:1** (`uv-frames:check-frames`). |
| 3. End calibration burst | Natural Light | `--end-calib-frames` (def 3000) | A closing NL burst that **brackets** the night. |

(At the default 25 fps these frame counts equal 180 s calib / 100 s UV / 10 s check / 120 s end-calib.)

**Why bracket the night?** If the plate solutions from the start burst and the end burst agree, the
camera held its pointing for the entire session, so **every** UV detection in between is trustworthy on
the single reference plate. If they disagree, the mount moved and the affected data can be flagged.
On a genuinely rigid mount you can lean on the brackets alone and disable the periodic drift checks
with `--check-frames 0`, maximizing UV uptime (~99%).

The end bracket and the final park run even on Ctrl+C (they are in a `finally` block), so a session is
always closed out cleanly and always bracketed.

## 5. The filter history log (downstream contract)

Every filter change is timestamped into a history file (default `~/RMS_data/filter_history.txt`):

```
<UTC ISO timestamp> <filter name>
2026-07-06T21:00:03.512847 Natural Light
2026-07-06T21:03:03.771020 UV
2026-07-06T22:03:04.004311 Natural Light
2026-07-06T22:03:34.219880 UV
...
```

Each line records the instant a filter **became active**; that filter stays active until the next line.
A consumer (e.g. RMS `DetectStarsAndMeteors`) splits on the first space, parses the timestamp, and for
any captured frame determines:

- **which filter was in place** at the frame's timestamp,
- therefore whether the frame is **UV science data** (run debris/streak extraction) or **Natural Light
  calibration data** (feed the plate-solving / drift-monitoring pipeline).

This log is the only coupling between the wheel scheduler and the astrometry pipeline. Keep its path in
sync with the RMS data directory when wiring detection up. (The timestamp format is intentionally
unchanged from the previous version so any existing consumer keeps working.)

## 6. End-to-end procedure to locate a streak

1. Set up the camera and leave it fixed for the night. Ensure the clock is disciplined (NTP/GPS).
2. Run `filter_cycle.py` for the session. It brackets the night with NL and spends the middle in UV.
3. Offline, build the reference plate solution from the NL calibration frames (blind plate solve so no
   pointing needs to be entered by hand). Compare start vs end bracket to confirm no drift.
4. For each UV streak: measure its endpoint pixel coordinates and per-frame UTC → apply the constant
   filter offset `(dx, dy)` → apply the plate solution to get `(az, alt)` → convert to `(RA, Dec)` with
   the timestamp. The per-frame positions also give the angular velocity / sky-track, which helps
   distinguish debris from meteors and aircraft.

## 7. Usage

```bash
# Real hardware, default night cadence (frame counts converted at the default 25 fps):
python3 filter_cycle.py

# 10:1 UV-to-NL frame ratio in the observing loop (10 UV frames per 1 NL check frame):
python3 filter_cycle.py --uv-frames 10 --check-frames 1

# Rigid mount, 20 fps capture, longer UV blocks, no periodic checks (brackets only):
python3 filter_cycle.py --fps 20 --calib-frames 6000 --uv-frames 72000 --check-frames 0

# Rehearse the whole schedule with NO hardware attached, sped up, to inspect the history log:
python3 filter_cycle.py --simulate \
    --calib-frames 75 --uv-frames 125 --check-frames 50 --end-calib-frames 75 \
    --history-file /tmp/filter_history_test.txt
```

Stop a running session with **Ctrl+C**: it finishes the current step, runs the end calibration bracket,
parks the wheel (default UV, `--park-filter`), and exits.

### Flags

| Flag | Default | Meaning |
|------|---------|---------|
| `--fps` | 25.0 | Capture frame rate used to convert frame counts to dwell time; keep in sync with the RMS capture `fps`. |
| `--calib-frames` | 4500 | Natural Light calibration burst at session start, frames. |
| `--uv-frames` | 2500 | UV observing block between drift checks, frames. |
| `--check-frames` | 250 | Natural Light drift check between UV blocks, frames; `0` disables periodic checks. |
| `--end-calib-frames` | 3000 | Natural Light burst at session end (brackets the night), frames. |
| `--park-filter` | `UV` | Filter to leave the wheel on at exit. |
| `--definition-file` | `definition_file.csv` | Filter definition CSV (names must match). |
| `--history-file` | `~/RMS_data/filter_history.txt` | Filter history log for downstream astrometry. |
| `--simulate` | off | No hardware; exercise the schedule and history log only. |

## 8. Assumptions and limits

- **Fixed mount for the session.** The whole method rests on `pixel → (az, alt)` being constant during
  the night. This scheduler does not detect drift itself; it only *enables* detection via the NL
  brackets/checks. A prototype that gets bumped mid-session needs more frequent checks (lower
  `--uv-frames`) and per-session re-solving — do not reuse a plate across setups.
- **Accurate UTC.** Clock error maps directly into position error. Run NTP, ideally GPS-disciplined.
- **Same lens, filters only.** Plate scale/distortion are shared; the constant `(dx, dy)` filter offset
  and any focus offset are handled as one-time calibrations, not by this script.
- **This script schedules the wheel and logs history.** Plate solving, drift comparison, and the
  pixel→RA/Dec transform live in the astrometry/RMS pipeline that consumes the history log.
