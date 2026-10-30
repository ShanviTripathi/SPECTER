r"""
SPECTER - presentation rehearsal timer (target ~1 minute per slide).

Run it, then talk through your slides. Controls (type, then press Enter):
  (just Enter)  next slide
  b             back one slide
  p             pause / resume
  q             stop and show the results

Examples:
  python C:\specter\rehearsal_timer.py --slides 12
  python C:\specter\rehearsal_timer.py --slides 12 --target 60 --slide-targets 9=90,1=30

Each run is saved to rehearsal/rehearsal_<timestamp>.csv so you can compare runs.
"""
import argparse
import csv
import os
import queue
import threading
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))

ap = argparse.ArgumentParser()
ap.add_argument("--slides", type=int, default=12, help="number of slides in the deck")
ap.add_argument("--target", type=float, default=60.0, help="default seconds per slide")
ap.add_argument("--slide-targets", default="",
                help="per-slide overrides, e.g. 9=90,1=30 (slide number = seconds)")
ap.add_argument("--outdir", default=os.path.join(HERE, "rehearsal"))
args = ap.parse_args()

targets = [args.target] * args.slides
for part in filter(None, (p.strip() for p in args.slide_targets.split(","))):
    try:
        n, secs = part.split("=")
        targets[int(n) - 1] = float(secs)
    except (ValueError, IndexError):
        raise SystemExit(f"Bad --slide-targets entry '{part}'. Use slide=seconds, e.g. 9=90")
total_target = sum(targets)


def mmss(s):
    s = int(round(abs(s)))
    return f"{s // 60:02d}:{s % 60:02d}"


cmds = queue.Queue()


def reader():
    while True:
        try:
            cmds.put(input())
        except EOFError:
            cmds.put("q")
            return


threading.Thread(target=reader, daemon=True).start()

spent = [0.0] * args.slides
cur = 0
paused = False
finished = False
print(f"{args.slides} slides, target {mmss(total_target)} total. Press Enter to START.")
cmds.get()
last = time.time()

try:
    while not finished:
        now = time.time()
        if not paused:
            spent[cur] += now - last
        last = now

        while not cmds.empty():
            c = cmds.get().strip().lower()
            if c == "q":
                finished = True
            elif c == "p":
                paused = not paused
            elif c == "b":
                cur = max(0, cur - 1)
            else:
                if cur == args.slides - 1:
                    finished = True
                else:
                    cur += 1

        diff = spent[cur] - targets[cur]
        status = "PAUSED" if paused else (f"over +{mmss(diff)}" if diff > 0 else f"left {mmss(-diff)}")
        print(f"\rSlide {cur + 1}/{args.slides}  {mmss(spent[cur])} / {mmss(targets[cur])} ({status})"
              f"   total {mmss(sum(spent))} / {mmss(total_target)}      ", end="", flush=True)
        time.sleep(0.2)
except KeyboardInterrupt:
    pass

print("\n\n=== RESULTS ===")
print(f"{'slide':>5} {'time':>7} {'target':>7} {'diff':>8}")
rows = []
for i, (t, tg) in enumerate(zip(spent, targets), 1):
    if t < 1 and i - 1 > cur:
        continue    # never reached
    d = t - tg
    flag = "  <- long" if d > 15 else ("  <- rushed" if d < -25 else "")
    print(f"{i:>5} {mmss(t):>7} {mmss(tg):>7} {'+' if d >= 0 else '-'}{mmss(d):>7}{flag}")
    rows.append((i, round(t, 1), tg, round(d, 1)))

total = sum(r[1] for r in rows)
reached_target = sum(r[2] for r in rows)
print(f"\nTotal {mmss(total)} vs {mmss(reached_target)} target for the slides you covered "
      f"({'+' if total >= reached_target else '-'}{mmss(total - reached_target)})")
slowest = sorted(rows, key=lambda r: r[3], reverse=True)[:3]
if slowest and slowest[0][3] > 0:
    print("Slowest slides: " + ", ".join(f"#{r[0]} (+{mmss(r[3])})" for r in slowest if r[3] > 0))

os.makedirs(args.outdir, exist_ok=True)
path = os.path.join(args.outdir, f"rehearsal_{datetime.now():%Y%m%d_%H%M%S}.csv")
with open(path, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["slide", "seconds", "target_s", "diff_s"])
    w.writerows(rows)
print(f"Saved {path}")
