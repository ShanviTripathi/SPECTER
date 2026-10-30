r"""
SPECTER - CSI capture script (runs on the laptop).
Saves lines from the RX ESP32 into a labeled CSV in a 'data' folder next to this file.

Example:
  python C:\specter\capture_csi.py --port COM5 --scenario LOS_EMPTY --minutes 2 --delay 20
  python C:\specter\capture_csi.py --list-ports

Scenario naming (the analysis script relies on this):
  <PREFIX>_<TYPE>[_<VARIANT>]   e.g. LOS_EMPTY, WALL_MOVING, LOS_FAN_HIGH
  PREFIX = LOS or WALL; every PREFIX should have its own <PREFIX>_EMPTY baseline.

Exit code is 1 if no CSI packets were received (so run_session.py can retry).
"""
import argparse
import csv
import os
import sys
import time
from datetime import datetime

try:
    import serial  # pip install pyserial
    from serial.tools import list_ports
except ImportError:
    sys.exit("pyserial is missing. Run: pip install pyserial")

parser = argparse.ArgumentParser()
parser.add_argument("--port", help="e.g. COM5")
parser.add_argument("--list-ports", action="store_true", help="print available serial ports and exit")
parser.add_argument("--scenario", help="label, e.g. LOS_EMPTY / WALL_MOVING")
parser.add_argument("--minutes", type=float, default=3.0, help="how long to record")
parser.add_argument("--baud", type=int, default=921600)
parser.add_argument("--outdir",
                    default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"),
                    help="where CSVs are saved (default: a 'data' folder next to this script)")
parser.add_argument("--delay", type=int, default=0,
                    help="seconds to wait before recording starts (time to leave the room)")
args = parser.parse_args()

if args.list_ports:
    ports = list(list_ports.comports())
    if not ports:
        print("No serial ports found.")
    for p in ports:
        print(f"{p.device}\t{p.description}")
    sys.exit(0)

if not args.port or not args.scenario:
    parser.error("--port and --scenario are required (or use --list-ports)")

os.makedirs(args.outdir, exist_ok=True)
start = datetime.now()
duration_s = int(args.minutes * 60)
fname = f"PHASE2_{args.scenario}_{start:%Y%m%d}_{start:%H%M%S}_{duration_s}s.csv"
path = os.path.join(args.outdir, fname)

if args.delay > 0:
    print(f"Get into position. Recording starts in {args.delay}s...")
    for s in range(args.delay, 0, -1):
        print(f"  {s}...   ", end="\r", flush=True)
        time.sleep(1)
    print()

try:
    ser = serial.Serial(args.port, args.baud, timeout=1)
except serial.SerialException as e:
    print(f"Could not open {args.port}: {e}")
    print("Close idf.py monitor / live_csi_visualizer.py (only one program can hold the port).")
    print("Run with --list-ports to check the COM number.")
    sys.exit(2)
ser.reset_input_buffer()

print(f"Recording '{args.scenario}' for {duration_s}s -> {path}")
print("Ctrl+C to stop early.")

n_packets = 0
t0 = time.time()
last_print = t0

try:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["host_time", "scenario", "raw_csi_line"])
        while time.time() - t0 < duration_s:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if not line.startswith("CSI_DATA"):
                continue
            w.writerow([datetime.now().isoformat(timespec="milliseconds"), args.scenario, line])
            n_packets += 1
            if time.time() - last_print >= 5:
                rate = n_packets / (time.time() - t0)
                print(f"  {n_packets} packets so far (~{rate:.0f}/s)")
                last_print = time.time()
except KeyboardInterrupt:
    print("Stopped early.")
finally:
    ser.close()

elapsed = time.time() - t0
rate = n_packets / elapsed if elapsed > 0 else 0
print(f"Done. {n_packets} packets in {elapsed:.0f}s = {rate:.1f} packets/s")

if n_packets == 0:
    print("WARNING: no CSI_DATA lines received. Check the TX board is powered and the RX firmware is running.")
    try:
        os.remove(path)
    except OSError:
        pass
    sys.exit(1)
