# SPECTER

**Wi-Fi sensing toolkit that detects human motion from Channel State Information (CSI) captured on an ESP32.**

SPECTER records how a Wi-Fi signal changes as it travels through a room, then analyzes those changes to decide whether something is moving in the signal's path. It works in line-of-sight and through-wall setups, and it measures how often everyday interference (fans, air conditioning, doors) triggers false alarms.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Features](#features)
- [Project Structure](#project-structure)
- [Installation](#installation)
- [Usage](#usage)
- [Naming Scenarios](#naming-scenarios)
- [Recording Guidelines](#recording-guidelines)
- [Analysis Output](#analysis-output)
- [Interpreting Results](#interpreting-results)

---

## How It Works

Wi-Fi signals reach a receiver along many paths: directly, and bounced off walls, furniture, and people. **Channel State Information (CSI)** describes how each Wi-Fi subcarrier was altered along those paths. When a person moves, the paths change, and the CSI fluctuates far more than it does in an empty room.

SPECTER turns that idea into a measurable pipeline:

1. **Capture.** An ESP32 running Espressif's [esp-csi](https://github.com/espressif/esp-csi) firmware streams CSI over USB serial. SPECTER records it as a labeled CSV file, one per scenario.
2. **Clean.** Isolated spikes in the CSI amplitude are detected and removed so single glitches do not look like motion.
3. **Establish a baseline.** A recording of the empty space (`EMPTY`) defines what "no motion" looks like, and a detection threshold is learned from it.
4. **Detect.** Every other recording is split into 1-second windows. A window is flagged as an alarm when its variability exceeds the learned threshold.
5. **Compare.** The share of flagged windows per scenario shows what the detector catches (people moving) and what fools it (fans, AC, doors).

---

## Features

- Guided, repeatable recording sessions with on-screen instructions per scenario
- Automatic retry and a session log when a recording fails
- Spike removal, baseline-relative statistics, and a tunable motion detector
- Line-of-sight (LOS) vs. through-wall (WALL) comparison
- Automatic warning when signal strength differs between recordings enough to make the comparison unfair
- Summary tables and plots generated in one command
- Live CSI visualizer for checking the hardware setup

---

## Project Structure

| File | Purpose |
|---|---|
| `capture_csi.py` | Records one labeled CSV from the ESP32. Includes `--list-ports` and exits with code 1 if no packets arrive. |
| `run_session.py` | Guided multi-scenario recording with instructions, retries, and a notes log at `data/session_log.csv`. |
| `analyze_csi.py` | Cleans data, builds the baseline, runs the detector, and writes tables and plots to `results/`. |
| `live_csi_visualizer.py` | Real-time CSI plot for verifying the setup. |
| `requirements.txt` | Python dependencies. |

Folders created as you work: `data/` (recordings and session log) and `results/` (analysis output).

---

## Installation

**Requirements**

- Python 3.9 or newer
- An ESP32 flashed with the `esp-csi` firmware and connected over USB

```bash
git clone https://github.com/EchoInSilicon/specter.git
cd specter
pip install -r requirements.txt
```

---

## Usage

**1. Find your ESP32's serial port**

```bash
python capture_csi.py --list-ports
```

**2. Record scenarios**

```bash
# Through-wall set: WALL_EMPTY, WALL_STATIONARY, WALL_MOVING (about 5 min)
python run_session.py --port COM5 --preset wall

# Interference set: LOS_FAN_LOW, LOS_FAN_HIGH, LOS_AC, LOS_DOOR (about 5 min)
python run_session.py --port COM5 --preset env

# Preview a session without recording
python run_session.py --port COM5 --preset all --dry-run
```

To record a single scenario manually, use `capture_csi.py` directly.

**3. Analyze**

```bash
python analyze_csi.py
```

**Detector options**

| Flag | Effect |
|---|---|
| `--window` | Length of the analysis window. |
| `--k` | Sensitivity: how far above the baseline a window must be to count as an alarm. |
| `--no-despike` | Skip spike removal. |

---

## Naming Scenarios

Recordings are named `<LOS|WALL>_<TYPE>[_VARIANT]`, for example `LOS_MOVING`, `WALL_STATIONARY`, or `LOS_FAN_HIGH`.

Each prefix is compared against its own empty-room recording, so every set needs a matching baseline: `LOS_*` scenarios use `LOS_EMPTY`, and `WALL_*` scenarios use `WALL_EMPTY`.

| Preset | Scenarios |
|---|---|
| `wall` | `WALL_EMPTY`, `WALL_STATIONARY`, `WALL_MOVING` |
| `env` | `LOS_FAN_LOW`, `LOS_FAN_HIGH`, `LOS_AC`, `LOS_DOOR` |
| `all` | Both sets |

---

## Recording Guidelines

Results are only meaningful if the recordings are comparable:

- **Keep the boards fixed** between recordings in the same set. If signal strength (RSSI) differs from the empty baseline by more than 5 dB, `analyze_csi.py` prints a warning, because a moved board and a person in the signal path look identical in that number.
- **Record interference scenarios in an empty room** (fan, AC, door), so any alarm counts as a genuine false alarm.
- **Repeat each scenario** at a different time of day to confirm the result is repeatable.

---

## Analysis Output

Everything is written to `results/`.

| File | Contents |
|---|---|
| `summary.csv` and `summary_table.txt` | Per-scenario statistics: mean amplitude, spikes removed, variance ratio vs. empty, RSSI difference vs. empty (dB), and alarm rate (%). |
| `motion_alarm_rate.png` | Percentage of 1-second windows flagged as motion, per scenario. |
| `rssi_by_scenario.png` | Signal strength per scenario. |
| `wall_vs_los.txt` | Wall attenuation and a LOS vs. WALL detection comparison. |

---

## Interpreting Results

The **alarm rate** is the percentage of 1-second windows that exceed the threshold learned from the empty-room baseline.

- **High for `MOVING` and `STATIONARY`:** the detector is picking up the person.
- **High for `FAN`, `AC`, or `DOOR`:** the detector is being fooled by non-human interference.
- **The `EMPTY` row is left blank.** The threshold was learned from that recording, so scoring it would be circular.
- A **variance ratio above 1** means the scenario fluctuates more than the empty room; the larger the ratio, the stronger the disturbance.

In an early line-of-sight test, `LOS_MOVING` triggered alarms in 100% of windows, `LOS_STATIONARY` in about 45%, and the fan in 0%. These figures come from a single session per scenario and are indicative only.
