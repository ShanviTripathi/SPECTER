r"""
SPECTER - live motion detector (demo).

Calibrates on the empty room for a few seconds, then prints one line per second:
QUIET or MOTION. It is the same detector analyze_csi.py uses: each 1-second window is scored by the
amplitude std (mean over subcarriers); the threshold is learned from the calibration period as
mean + k * std of those scores.

Live, with the RX board:
  python C:\specter\live_detect.py --port COM5

No hardware (replays recorded CSVs at real speed; the first file is the calibration "empty room"):
  python C:\specter\live_detect.py --replay data\PHASE2_LOS_EMPTY_20261027_092157_120s.csv data\PHASE2_LOS_MOVING_20260919_081717_60s.csv
  add --speed 5 to play it 5x faster

Stay out of the sensing path (and keep still) while it calibrates. Ctrl+C stops it and prints a summary.
Close idf.py monitor / live_csi_visualizer.py first: only one program can hold the serial port.
"""
import argparse
import csv
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime

import numpy as np

QUOTED = re.compile(r'"\[([^\]]*)\]"')

ap = argparse.ArgumentParser()
ap.add_argument("--port", help="RX board serial port, e.g. COM5")
ap.add_argument("--baud", type=int, default=921600)
ap.add_argument("--replay", nargs="+", metavar="CSV", help="replay recorded CSV file(s) instead of using the board")
ap.add_argument("--speed", type=float, default=1.0, help="replay speed multiplier")
ap.add_argument("--calib", type=float, default=30.0, help="calibration length in seconds (default 30)")
ap.add_argument("--window", type=float, default=1.0, help="window length in seconds")
ap.add_argument("--k", type=float, default=3.0, help="threshold = calibration mean + k * std")
ap.add_argument("--hold", type=int, default=2, help="keep showing MOTION for this many windows after the last alarm")
ap.add_argument("--no-color", action="store_true")
args = ap.parse_args()

if not args.replay and not args.port:
    ap.error("give --port COM5 (live) or --replay file.csv [file2.csv ...]")

if os.name == "nt":
    os.system("")          # enables ANSI colours in the Windows terminal
USE_COLOR = not args.no_color and sys.stdout.isatty()
GREEN, RED, DIM, RESET = ("\033[92m", "\033[91m", "\033[2m", "\033[0m") if USE_COLOR else ("", "", "", "")


def parse_csi_line(line):
    m = QUOTED.search(line)
    if not m:
        return None
    fields = line[: m.start()].rstrip(",").split(",")
    try:
        rssi = int(fields[3])
        data = np.array(m.group(1).split(","), dtype=float)
    except (ValueError, IndexError):
        return None
    if len(data) < 8:
        return None
    body = data[4: 4 + ((len(data) - 4) // 2) * 2]
    return rssi, np.sqrt(body[0::2] ** 2 + body[1::2] ** 2)


def serial_source():
    try:
        import serial
    except ImportError:
        sys.exit("pyserial is missing. Run: pip install pyserial")
    try:
        ser = serial.Serial(args.port, args.baud, timeout=1)
    except serial.SerialException as e:
        sys.exit(f"Could not open {args.port}: {e}\nCheck the port (python capture_csi.py --list-ports) "
                 "and close anything else using it.")
    ser.reset_input_buffer()
    t0 = None
    try:
        while True:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if not line.startswith("CSI_DATA"):
                continue
            p = parse_csi_line(line)
            if p is None:
                continue
            now = time.time()
            t0 = now if t0 is None else t0
            yield now - t0, p[0], p[1], ""
    finally:
        ser.close()


def replay_source():
    offset, wall0 = 0.0, time.time()
    for path in args.replay:
        if not os.path.exists(path):
            sys.exit(f"File not found: {path}")
        first, last_t = None, offset
        with open(path, newline="") as f:
            r = csv.reader(f)
            next(r, None)
            for row in r:
                if len(row) < 3:
                    continue
                p = parse_csi_line(row[2])
                if p is None:
                    continue
                try:
                    dt = datetime.fromisoformat(row[0])
                except ValueError:
                    continue
                first = dt if first is None else first
                t = offset + (dt - first).total_seconds()
                wait = wall0 + t / args.speed - time.time()
                if wait > 0:
                    time.sleep(wait)
                last_t = t
                yield t, p[0], p[1], row[1]
        offset = last_t + 1.0


def window_score(Aa):
    return float(Aa.std(axis=0).mean())


def bar(score, thr, width=24):
    filled = int(min(score / (2 * thr), 1.0) * width) if thr > 0 else 0
    marker = width // 2
    cells = ["#" if i < filled else "." for i in range(width)]
    cells[marker] = "|" if cells[marker] == "." else "#"
    return "".join(cells)


# ------------------------------------------------------------------ calibration
source = serial_source() if not args.replay else replay_source()
print("CALIBRATING - keep the room empty and still "
      f"for {args.calib:.0f} s ...")
calib = []        # (t, rssi, amps)
pending = None    # first packet after calibration
last_print = -1
for t, rssi, amps, label in source:
    if t >= args.calib:
        pending = (t, rssi, amps, label)
        break
    calib.append((t, rssi, amps))
    if int(t) != last_print and int(t) % 5 == 0:
        last_print = int(t)
        print(f"  {int(t)}/{args.calib:.0f} s  ({len(calib)} packets)")

if len(calib) < 200:
    sys.exit("Too few packets during calibration. Is the TX board on and the RX firmware running?")

modal = Counter(len(a) for _, _, a in calib).most_common(1)[0][0]
calib = [(t, r, a) for t, r, a in calib if len(a) == modal]
CA = np.array([a for _, _, a in calib])
means = CA.mean(axis=1)
med = float(np.median(means))
sig = max(1.4826 * float(np.median(np.abs(means - med))), 0.5)
ok = np.abs(means - med) <= 6 * sig
active = np.median(CA[ok], axis=0) > 2.0
secs = np.array([t for t, _, _ in calib])
scores = []
for w in np.unique(np.floor(secs / args.window).astype(int)):
    idx = np.flatnonzero((np.floor(secs / args.window).astype(int) == w) & ok)
    if len(idx) >= 10:
        scores.append(window_score(CA[idx][:, active]))
scores = np.array(scores)
if len(scores) < 5:
    sys.exit("Not enough clean windows to calibrate. Try again with --calib 40.")
thr = float(scores.mean() + args.k * scores.std())
rssi_ref = float(np.mean([r for _, r, _ in calib]))
print(f"\nCalibrated: {int(active.sum())} active subcarriers, empty-room RSSI {rssi_ref:.1f} dBm, "
      f"threshold {thr:.2f} (empty-room score {scores.mean():.2f} +/- {scores.std():.2f})")
print("LIVE - walk through the path to trigger it. Ctrl+C to stop.\n")

# ------------------------------------------------------------------ live loop
cur, buf_a, buf_r, buf_label = None, [], [], ""
hold_left = 0
stats = Counter()
stats_by_label = {}


def flush(win_id):
    global hold_left
    if len(buf_a) < 10:
        return
    Aa = np.array(buf_a)[:, active]
    score = window_score(Aa)
    rssi = float(np.mean(buf_r))
    alarm = score > thr
    if alarm:
        hold_left = args.hold
        shown = True
    elif hold_left > 0:
        hold_left -= 1
        shown = True
    else:
        shown = False
    stats["windows"] += 1
    stats["alarm"] += int(alarm)
    if buf_label:
        s = stats_by_label.setdefault(buf_label, [0, 0])
        s[0] += 1
        s[1] += int(alarm)
    status = f"{RED}MOTION{RESET}" if shown else f"{GREEN}quiet {RESET}"
    tag = f"  {DIM}[{buf_label}]{RESET}" if buf_label else ""
    print(f"{int((win_id + 1) * args.window):>4}s  RSSI {rssi:6.1f}  score {score:5.2f} /{thr:5.2f}  "
          f"{bar(score, thr)}  {status}{tag}", flush=True)


def packets():
    if pending is not None:
        yield pending
    yield from source


try:
    for t, rssi, amps, label in packets():
        if len(amps) != modal:
            continue
        if abs(float(amps.mean()) - med) > 6 * sig * 2:     # lone spike packet
            continue
        w = int(t // args.window)
        if cur is None:
            cur = w
        if w != cur:
            flush(cur)
            buf_a, buf_r = [], []
            cur = w
        buf_a.append(amps)
        buf_r.append(rssi)
        buf_label = label
except KeyboardInterrupt:
    pass

print("\n=== SUMMARY ===")
if stats["windows"]:
    print(f"{stats['windows']} windows, {stats['alarm']} above threshold "
          f"({100 * stats['alarm'] / stats['windows']:.0f}%)")
    for lab, (n, a) in stats_by_label.items():
        print(f"  {lab:<18} {a}/{n} windows alarmed ({100 * a / n:.0f}%)")
else:
    print("No live windows were scored.")
