# SPECTER code (Phase 2 + Phase 3 tooling)

Drop everything into `C:\specter` (overwrite `analyze_csi.py` and `capture_csi.py`; `live_csi_visualizer.py` is unchanged).
Install once: `pip install -r requirements.txt`

| Script | What it does |
|---|---|
| `capture_csi.py` | Records one labeled CSV. New: `--list-ports`, clear errors, exit code 1 if no packets came in. |
| `run_session.py` | **New.** Guided multi-scenario recording (wall, fan low/high, AC, door) with per-scenario instructions, retry on failure and a notes log (`data/session_log.csv`). |
| `analyze_csi.py` | Upgraded: spike removal, ratio vs. the matching EMPTY baseline, motion-detector alarm rate, LOS-vs-WALL report, 2 extra plots. |
| `rehearsal_timer.py` | **New.** ~1 min/slide timer with per-slide results saved to `rehearsal/`. |
| `backup_specter.py` | **New.** Zips `C:\specter` + `esp-csi-master` to a USB/Drive folder, with SHA-256 manifest and verification. |
| `live_csi_visualizer.py` | Unchanged. |

## Recording the missing scenarios
```
python capture_csi.py --list-ports
python run_session.py --port COM5 --preset wall      # WALL_EMPTY, WALL_STATIONARY, WALL_MOVING (~5 min)
python run_session.py --port COM5 --preset env       # LOS_FAN_LOW, LOS_FAN_HIGH, LOS_AC, LOS_DOOR (~5 min)
python run_session.py --port COM5 --preset all --dry-run   # preview the plan
python analyze_csi.py
```
Rules that keep the comparison fair:
- Name scenarios `<LOS|WALL>_<TYPE>[_VARIANT]`. Each prefix is compared against its own `<PREFIX>_EMPTY`, so record a WALL_EMPTY first.
- Do not move the boards between recordings of the same set. Your current LOS data shows mean RSSI of -69 dBm for EMPTY but -77 to -85 dBm for the others; if the boards were not moved that is the person/fan in the path, but if they were, the variance comparison is not apples to apples. `analyze_csi.py` prints a note whenever the gap exceeds 5 dB.
- Re-record LOS_FAN_LOW/HIGH with nobody in the room, so any alarm is a true false alarm.
- If you can, record each scenario twice (different time of day) so a slide can say "repeatable".

## New analysis outputs (`results/`)
- `summary.csv` / `summary_table.txt`: old columns plus `amp_mean`, `spikes_removed`, `var_ratio_vs_empty`, `rssi_delta_vs_empty_dB`, `alarm_rate_%`.
- `motion_alarm_rate.png`: % of 1-second windows above the EMPTY-learned threshold. High on MOVING/STATIONARY = detection; high on FAN/AC/DOOR = false alarm. The EMPTY row itself is left blank (it would be circular).
- `rssi_by_scenario.png`, `wall_vs_los.txt` (wall attenuation and detection LOS vs WALL).
- Tune the detector with `--window` and `--k`; disable spike removal with `--no-despike`.

On your existing LOS data: LOS_MOVING alarms in 100% of windows, LOS_STATIONARY in about 45%, LOS_FAN in 0%.

## Rehearsal and backup
```
python rehearsal_timer.py --slides 12 --slide-targets 9=90
python backup_specter.py --src C:\specter C:\esp\esp-csi-master --dest "G:\My Drive\SPECTER"
python backup_specter.py --src C:\specter C:\esp\esp-csi-master --dest E:\backups
```
Use the real path of your `esp-csi-master` folder. Run the backup to both the USB stick and the Drive sync folder.

## Not in this zip
`build.py` and the pptx: I only received the CSI scripts and results, so the slide rendering/QA step is not covered. Send `build.py` and the current deck and I'll do that separately.
