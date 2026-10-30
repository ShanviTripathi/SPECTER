r"""
SPECTER Phase 3 - guided recording session.

Runs capture_csi.py for a whole list of scenarios, one after another, telling you what to
set up before each one. Every recording is logged (with an optional note) to
data/session_log.csv so you remember the geometry later.

Examples:
  python C:\specter\run_session.py --port COM5 --preset wall
  python C:\specter\run_session.py --port COM5 --preset env
  python C:\specter\run_session.py --port COM5 --preset all --delay 30
  python C:\specter\run_session.py --port COM5 --preset env --only LOS_AC
  python C:\specter\run_session.py --port COM5 --preset all --dry-run
  python C:\specter\run_session.py --list

Presets
  los   re-record the Phase 2 line-of-sight set
  wall  through-wall set: WALL_EMPTY / WALL_STATIONARY / WALL_MOVING
  env   environment set: LOS_FAN_LOW / LOS_FAN_HIGH / LOS_AC / LOS_DOOR
  all   wall + env

Keep the TX and RX boards in the SAME positions for every recording of a preset
(only the activity should change), otherwise RSSI/variance comparisons are not fair.
"""
import argparse
import csv
import os
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))

# (scenario label, minutes, what to do)
LOS = [
    ("LOS_EMPTY", 2.0, "Room empty, boards in line of sight. Leave the room (the delay lets you get out)."),
    ("LOS_STATIONARY", 1.0, "Stand still at your marked spot between/near the boards. Breathe normally."),
    ("LOS_MOVING", 1.0, "Walk continuously around the same area for the whole recording."),
    ("LOS_FAN", 1.0, "Fan ON (one setting), nobody in the room. Leave the room."),
]
WALL = [
    ("WALL_EMPTY", 2.0, "Boards on opposite sides of the wall, nobody in either room's sensing area. "
                        "Note wall type/thickness in the note."),
    ("WALL_STATIONARY", 1.0, "Same board positions. Stand still at your marked spot (note where) - "
                             "use the same spot every time."),
    ("WALL_MOVING", 1.0, "Same board positions. Walk continuously around the same area as LOS_MOVING."),
]
ENV = [
    ("LOS_EMPTY", 1.0, "Baseline for THIS session: line-of-sight positions, nobody in the room. Leave the room. "
                      "Do not move the boards for the rest of the set."),
    ("LOS_FAN_LOW", 1.0, "Back in line-of-sight positions. Fan on LOW, nobody in the room. Leave the room."),
    ("LOS_FAN_HIGH", 1.0, "Fan on HIGH, same fan position as LOW, nobody in the room. Leave the room."),
    ("LOS_AC", 1.0, "AC ON (note temperature/fan setting), nobody in the room. Leave the room."),
    ("LOS_DOOR", 1.0, "Door closed at start. From OUTSIDE the sensing path: open it fully, hold ~3 s, "
                      "close it; repeat about every 10 s for the whole recording."),
]
PRESETS = {"los": LOS, "wall": WALL, "env": ENV, "all": WALL + ENV}

ap = argparse.ArgumentParser(description="Guided CSI recording session")
ap.add_argument("--port", help="RX board serial port, e.g. COM5")
ap.add_argument("--preset", choices=sorted(PRESETS), default="all")
ap.add_argument("--only", nargs="+", metavar="SCENARIO", help="run just these scenario names from the preset")
ap.add_argument("--delay", type=int, default=20, help="seconds before each recording starts (default 20)")
ap.add_argument("--minutes", type=float, help="override the recording length for every scenario")
ap.add_argument("--outdir", default=os.path.join(HERE, "data"))
ap.add_argument("--no-pause", action="store_true", help="do not wait for Enter before each scenario")
ap.add_argument("--dry-run", action="store_true", help="print the plan and commands, record nothing")
ap.add_argument("--list", action="store_true", help="list presets and exit")
args = ap.parse_args()

if args.list:
    for name, items in PRESETS.items():
        print(f"[{name}]")
        for sc, mins, text in items:
            print(f"  {sc:<18}{mins:>4.1f} min  {text}")
    sys.exit(0)

if not args.port and not args.dry_run:
    ap.error("--port is required (find it with: python capture_csi.py --list-ports)")

plan = PRESETS[args.preset]
if args.only:
    wanted = set(args.only)
    plan = [p for p in plan if p[0] in wanted]
    missing = wanted - {p[0] for p in plan}
    if missing:
        ap.error(f"not in preset '{args.preset}': {', '.join(sorted(missing))}")
if not plan:
    ap.error("nothing to record")

total_min = sum((args.minutes or m) for _, m, _ in plan) + len(plan) * args.delay / 60
print(f"Preset '{args.preset}': {len(plan)} recording(s), about {total_min:.0f} min including delays.\n")

if not args.dry_run:
    os.makedirs(args.outdir, exist_ok=True)
log_path = os.path.join(args.outdir, "session_log.csv")
new_log = not os.path.exists(log_path)


def log(scenario, minutes, status, note):
    with open(log_path, "a", newline="") as f:
        w = csv.writer(f)
        if new_log_flag[0]:
            w.writerow(["logged_at", "scenario", "minutes", "status", "note"])
            new_log_flag[0] = False
        w.writerow([datetime.now().isoformat(timespec="seconds"), scenario, minutes, status, note])


new_log_flag = [new_log]

for i, (scenario, minutes, text) in enumerate(plan, 1):
    minutes = args.minutes or minutes
    cmd = [sys.executable, os.path.join(HERE, "capture_csi.py"), "--port", args.port or "COMx",
           "--scenario", scenario, "--minutes", str(minutes), "--delay", str(args.delay),
           "--outdir", args.outdir]
    print(f"=== [{i}/{len(plan)}] {scenario}  ({minutes:g} min) ===")
    print(text)
    if args.dry_run:
        print("  would run: " + " ".join(cmd) + "\n")
        continue

    note = ""
    if not args.no_pause:
        ans = input("Set up, then press Enter to start  (s = skip, q = quit): ").strip().lower()
        if ans == "q":
            print("Quit.")
            break
        if ans == "s":
            log(scenario, minutes, "skipped", "")
            print()
            continue
        note = input("Note for the log (wall type, positions, fan/AC setting...; Enter for none): ").strip()

    while True:
        rc = subprocess.call(cmd)
        if rc == 0:
            log(scenario, minutes, "ok", note)
            break
        print(f"\nRecording failed (exit code {rc}).")
        ans = input("Retry (r), skip (s) or quit (q)? ").strip().lower()
        if ans == "r":
            continue
        log(scenario, minutes, "failed", note)
        if ans == "q":
            print("Quit.")
            sys.exit(1)
        break
    print()

if not args.dry_run:
    print(f"Done. Notes are in {log_path}")
    print("Next: python analyze_csi.py")
