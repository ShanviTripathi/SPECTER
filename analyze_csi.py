"""
SPECTER - analysis of recorded CSI files (Phase 2 line-of-sight + Phase 3 through-wall / environment).

Reads every PHASE2_*.csv made by capture_csi.py and writes summary + plots
into a 'results' folder next to this script.

Run:  python C:/specter/analyze_csi.py
Needs: pip install numpy matplotlib

Scenario names are <PREFIX>_<TYPE>[_<VARIANT>] (LOS_EMPTY, WALL_MOVING, LOS_FAN_HIGH ...).
Each PREFIX is compared against its own <PREFIX>_EMPTY recording (the baseline).

What is new compared with the Phase 2 version:
  * isolated one-packet spikes are removed before statistics (see --no-despike)
  * variance ratio and RSSI change relative to the matching EMPTY baseline
  * a simple motion detector: 1-second windows scored by amplitude std, threshold
    learned from the EMPTY baseline; "alarm rate" = % of windows above threshold
    (high on MOVING/STATIONARY = detection, high on FAN/AC/DOOR = false alarm)
  * LOS vs WALL attenuation report (wall_vs_los.txt)
  * extra plots: motion_alarm_rate.png, rssi_by_scenario.png
"""
import argparse
import csv
import glob
import os
import re
from collections import Counter
from datetime import datetime

import matplotlib
matplotlib.use("Agg")  # save PNGs, no window needed
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
QUOTED = re.compile(r'"\[([^\]]*)\]"')

ap = argparse.ArgumentParser()
ap.add_argument("--data", default=os.path.join(HERE, "data"))
ap.add_argument("--out", default=os.path.join(HERE, "results"))
ap.add_argument("--pattern", default="PHASE2_*.csv", help="file glob inside --data")
ap.add_argument("--send-rate", type=float, default=100.0)
ap.add_argument("--window", type=float, default=1.0, help="detector window length in seconds")
ap.add_argument("--k", type=float, default=3.0,
                help="detector threshold = baseline mean + k * baseline std (of window scores)")
ap.add_argument("--no-despike", action="store_true", help="keep isolated spike packets")
ap.add_argument("--despike-sigma", type=float, default=6.0,
                help="a packet is a spike if its mean amplitude is this many robust sigmas from the median")
args = ap.parse_args()
os.makedirs(args.out, exist_ok=True)

PREFIX_COLORS = {"LOS": "#3b6fb6", "WALL": "#d9822b"}
PREFIX_ORDER = {"LOS": 0, "WALL": 1}
TYPE_ORDER = ["EMPTY", "FAN", "AC", "DOOR", "STATIONARY", "MOVING"]


def prefix_of(scenario):
    return scenario.split("_")[0]


def type_of(scenario):
    return "_".join(scenario.split("_")[1:])


def sort_key(scenario):
    t = type_of(scenario)
    t_rank = next((i for i, name in enumerate(TYPE_ORDER) if t.startswith(name)), len(TYPE_ORDER))
    return (PREFIX_ORDER.get(prefix_of(scenario), 9), t_rank, scenario)


def parse_csi_line(line):
    """CSI_DATA line -> (rssi, amplitude array) or None."""
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
    # first 4 values are invalid; the rest are (imaginary, real) pairs
    body = data[4: 4 + ((len(data) - 4) // 2) * 2]
    imag, real = body[0::2], body[1::2]
    return rssi, np.sqrt(imag ** 2 + real ** 2)


def load(path):
    times, rssis, amps = [], [], []
    scenario = "?"
    with open(path, newline="") as f:
        r = csv.reader(f)
        next(r, None)  # header
        for row in r:
            if len(row) < 3:
                continue
            p = parse_csi_line(row[2])
            if p is None:
                continue
            try:
                times.append(datetime.fromisoformat(row[0]))
            except ValueError:
                continue
            scenario = row[1]
            rssis.append(p[0])
            amps.append(p[1])
    if not amps:
        return None
    # Packets can arrive with different CSI lengths (different frame types). Keep the most common
    # length and drop the rest; truncating everything to the shortest packet would silently throw
    # away most subcarriers for the whole recording.
    lengths = Counter(len(a) for a in amps)
    modal = lengths.most_common(1)[0][0]
    keep = [i for i, a in enumerate(amps) if len(a) == modal]
    mixed = len(amps) - len(keep)
    A = np.array([amps[i] for i in keep])
    times = np.array([times[i] for i in keep])
    rssis = np.array([rssis[i] for i in keep])
    return scenario, times, rssis, A, mixed, lengths


def despike(A, sigma_k):
    """Boolean keep-mask: drop packets whose mean amplitude is a robust outlier."""
    m = A.mean(axis=1)
    med = np.median(m)
    sigma = 1.4826 * np.median(np.abs(m - med))
    if sigma <= 0:
        return np.ones(len(A), dtype=bool)
    return np.abs(m - med) <= sigma_k * sigma


def window_scores(secs, Aa, win, min_pkts=10):
    """Per-window motion score = mean over subcarriers of the amplitude std inside the window."""
    ids = np.floor(secs / win).astype(int)
    scores = []
    for w in np.unique(ids):
        idx = np.flatnonzero(ids == w)
        if len(idx) >= min_pkts:
            scores.append(Aa[idx].std(axis=0).mean())
    return np.array(scores)


# ---------------------------------------------------------------- load + per-recording stats
recs = []
for path in sorted(glob.glob(os.path.join(args.data, args.pattern))):
    res = load(path)
    if res is None:
        print(f"skipped (no valid CSI lines): {os.path.basename(path)}")
        continue
    scenario, times, rssi, A, mixed, lengths = res
    dur = max((times[-1] - times[0]).total_seconds(), 1e-9)
    n_raw = len(A) + mixed          # every CSI packet received
    rate = n_raw / dur

    if args.no_despike:
        keep = np.ones(n_raw, dtype=bool)
    else:
        keep = despike(A, args.despike_sigma)
    removed = int((~keep).sum())
    times, rssi, A = times[keep], rssi[keep], A[keep]

    active = np.median(A, axis=0) > 2.0    # ignore unused (all-zero) subcarriers
    Aa = A[:, active]
    secs = np.array([(x - times[0]).total_seconds() for x in times])
    var_per_sc = Aa.var(axis=0)
    cv_per_sc = Aa.std(axis=0) / np.maximum(Aa.mean(axis=0), 1e-9)
    recs.append({
        "file": os.path.basename(path),
        "scenario": scenario,
        "times": times, "secs": secs, "rssi": rssi, "Aa": Aa,
        "scores": window_scores(secs, Aa, args.window),
        "row": {
            "file": os.path.basename(path),
            "scenario": scenario,
            "packets": n_raw,
            "duration_s": round(dur, 1),
            "rate_pps": round(rate, 1),
            "delivery_vs_send_rate_%": round(100 * rate / args.send_rate, 1),
            "active_subcarriers": int(active.sum()),
            "rssi_mean_dBm": round(float(rssi.mean()), 1),
            "rssi_std_dB": round(float(rssi.std()), 2),
            "amp_variance": round(float(var_per_sc.mean()), 2),
            "amp_cv": round(float(cv_per_sc.mean()), 4),
            "amp_mean": round(float(Aa.mean()), 2),
            "spikes_removed": removed,
            "other_length_dropped": mixed,
        },
    })
    print(f"read {os.path.basename(path)}: {n_raw} packets, {rate:.1f}/s"
          + (f", {removed} spike packet(s) removed" if removed else ""))
    if mixed:
        print(f"    NOTE: mixed CSI packet lengths {dict(lengths)} - kept the most common, dropped {mixed}. "
              f"Other frame types are reaching the receiver; check the TX/RX filtering.")

if not recs:
    raise SystemExit(f"No {args.pattern} files found in {args.data}")

recs.sort(key=lambda r: sort_key(r["scenario"]))   # stable: same scenario keeps filename order

# ---------------------------------------------------------------- baselines + detector
# Each recording is compared with the <PREFIX>_EMPTY recording closest to it IN TIME, so a
# recording made weeks later with the boards in a different spot is not judged against an old room.
empties = {}   # prefix -> list of EMPTY records
for r in recs:
    if type_of(r["scenario"]) == "EMPTY":
        empties.setdefault(prefix_of(r["scenario"]), []).append(r)
empty_files = {b["file"] for lst in empties.values() for b in lst}


def baseline_for(r):
    cands = empties.get(prefix_of(r["scenario"]), [])
    if not cands:
        return None
    t0 = r["times"][0]
    return min(cands, key=lambda b: abs((b["times"][0] - t0).total_seconds()))


thresholds = {}   # baseline file -> detector threshold
for lst in empties.values():
    for b in lst:
        if len(b["scores"]) >= 2:
            thresholds[b["file"]] = float(b["scores"].mean() + args.k * b["scores"].std())

for r in recs:
    row = r["row"]
    b = baseline_for(r)
    row["baseline_file"] = ""
    row["var_ratio_vs_empty"] = ""
    row["rssi_delta_vs_empty_dB"] = ""
    row["alarm_rate_%"] = ""
    if b is None:
        continue
    row["baseline_file"] = b["file"]
    if r is b:
        row["var_ratio_vs_empty"] = 1.0
        row["rssi_delta_vs_empty_dB"] = 0.0
        continue          # alarm rate on the baseline itself would be circular, leave blank
    bv = max(b["row"]["amp_variance"], 1e-9)
    row["var_ratio_vs_empty"] = round(row["amp_variance"] / bv, 2)
    row["rssi_delta_vs_empty_dB"] = round(row["rssi_mean_dBm"] - b["row"]["rssi_mean_dBm"], 1)
    if b["file"] in thresholds and len(r["scores"]):
        row["alarm_rate_%"] = round(100 * float((r["scores"] > thresholds[b["file"]]).mean()), 1)

rows = [r["row"] for r in recs]

# ---------------------------------------------------------------- summary files
keys = list(rows[0].keys())
with open(os.path.join(args.out, "summary.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=keys)
    w.writeheader()
    w.writerows(rows)

with open(os.path.join(args.out, "summary_table.txt"), "w") as f:
    for r in rows:
        f.write(" | ".join(f"{k}={r[k]}" for k in keys[1:]) + "\n")

print("\n=== SUMMARY ===")
print(f"{'scenario':<18}{'pkts':>7}{'rate/s':>8}{'RSSI':>8}{'RSSI sd':>9}{'amp var':>10}"
      f"{'amp CV':>9}{'var x':>8}{'alarm %':>9}")
for r in rows:
    if r["file"] in empty_files:
        alarm = "base"
    else:
        alarm = r["alarm_rate_%"] if r["alarm_rate_%"] != "" else "-"
    print(f"{r['scenario']:<18}{r['packets']:>7}{r['rate_pps']:>8}{r['rssi_mean_dBm']:>8}"
          f"{r['rssi_std_dB']:>9}{r['amp_variance']:>10}{r['amp_cv']:>9}"
          f"{str(r['var_ratio_vs_empty']):>8}{str(alarm):>9}")

if thresholds:
    print("\nDetector thresholds (window score = mean amplitude std per window; k=%g, window=%gs):" % (args.k, args.window))
    for f_, t_ in thresholds.items():
        print(f"  {t_:6.2f}  from {f_}")
for p in sorted({prefix_of(r["scenario"]) for r in recs}):
    if p not in empties:
        print(f"Note: no {p}_EMPTY recording found, so {p}_* scenarios have no baseline comparison.")

# baseline quality: an unstable EMPTY recording inflates the threshold and hides real motion
for lst in empties.values():
    for b in lst:
        br = b["row"]
        if br["rssi_std_dB"] > 2 or br["delivery_vs_send_rate_%"] < 60:
            print(f"WARNING: baseline {b['file']} looks unstable (RSSI std {br['rssi_std_dB']} dB, "
                  f"delivery {br['delivery_vs_send_rate_%']}%). Someone may have been moving, or the link is too "
                  f"weak. Its detector threshold will be inflated - consider re-recording it.")

# RSSI-vs-baseline sanity note: a big gap means the geometry may have changed, not just the activity
for r in rows:
    d = r["rssi_delta_vs_empty_dB"]
    if d != "" and abs(d) > 5:
        print(f"Note: {r['scenario']} mean RSSI is {d:+.1f} dB vs its EMPTY baseline ({r['baseline_file']}) - a "
              f"person/fan in the path can do that, but also check the board positions were not moved between recordings.")

# ---------------------------------------------------------------- LOS vs WALL attenuation
if "LOS" in empties and "WALL" in empties:
    wall_b = max(empties["WALL"], key=lambda b: b["times"][0])          # newest WALL_EMPTY
    los_b = min(empties["LOS"], key=lambda b: abs((b["times"][0] - wall_b["times"][0]).total_seconds()))
    los, wall = los_b["row"], wall_b["row"]
    d_rssi = wall["rssi_mean_dBm"] - los["rssi_mean_dBm"]
    d_amp_db = 20 * np.log10(max(wall["amp_mean"], 1e-9) / max(los["amp_mean"], 1e-9))
    lines = [
        "Through-wall vs line-of-sight (EMPTY baselines)",
        f"  LOS baseline : {los_b['file']}",
        f"  WALL baseline: {wall_b['file']}",
        f"  mean RSSI : LOS {los['rssi_mean_dBm']} dBm -> WALL {wall['rssi_mean_dBm']} dBm  ({d_rssi:+.1f} dB)",
        f"  mean CSI amplitude : LOS {los['amp_mean']} -> WALL {wall['amp_mean']}  ({d_amp_db:+.1f} dB)"
        "  [receiver gain control can hide path loss here - trust RSSI for attenuation]",
        f"  amplitude variance : LOS {los['amp_variance']} -> WALL {wall['amp_variance']}",
        f"  packet delivery    : LOS {los['delivery_vs_send_rate_%']}% -> WALL {wall['delivery_vs_send_rate_%']}%",
    ]
    for t in ("STATIONARY", "MOVING"):
        lr = next((r for r in rows if r["scenario"] == f"LOS_{t}" and r["baseline_file"] == los_b["file"]), None)
        wr = next((r for r in rows if r["scenario"] == f"WALL_{t}" and r["baseline_file"] == wall_b["file"]), None)
        if lr and wr:
            lines.append(f"  {t.lower()} detection (alarm rate): LOS {lr['alarm_rate_%']}% -> WALL {wr['alarm_rate_%']}%"
                         f"   | variance ratio: LOS {lr['var_ratio_vs_empty']}x -> WALL {wr['var_ratio_vs_empty']}x")
    text = "\n".join(lines)
    print("\n" + text)
    with open(os.path.join(args.out, "wall_vs_los.txt"), "w") as f:
        f.write(text + "\n")

# ---------------------------------------------------------------- plots
labels = [f"{r['scenario']}\n#{i + 1}" for i, r in enumerate(rows)]
colors = [PREFIX_COLORS.get(prefix_of(r["scenario"]), "#777777") for r in rows]
width = max(6, 1.3 * len(rows))


def legend_for_prefixes(ax):
    present = [p for p in PREFIX_COLORS if any(prefix_of(r["scenario"]) == p for r in rows)]
    if len(present) > 1:
        handles = [plt.Rectangle((0, 0), 1, 1, color=PREFIX_COLORS[p]) for p in present]
        ax.legend(handles, present, fontsize=8)


# plot 1: variance per recording
fig, ax = plt.subplots(figsize=(width, 4.5))
bars = ax.bar(labels, [r["amp_variance"] for r in rows], color=colors)
ax.bar_label(bars, fmt="%.1f", fontsize=8)
ax.set_ylabel("CSI amplitude variance\n(mean over active subcarriers)")
ax.set_title("SPECTER: amplitude variance per scenario")
ax.tick_params(axis="x", labelsize=7)
legend_for_prefixes(ax)
plt.tight_layout()
fig.savefig(os.path.join(args.out, "variance_by_scenario.png"), dpi=160)
plt.close(fig)

# plot 2: mean amplitude over time
fig, axes = plt.subplots(len(recs), 1, figsize=(10, 2.2 * len(recs)),
                         sharey=True, squeeze=False)
for ax, r in zip(axes[:, 0], recs):
    ax.plot(r["secs"], r["Aa"].mean(axis=1), lw=0.8, color=PREFIX_COLORS.get(prefix_of(r["scenario"]), "#1f77b4"))
    ax.set_ylabel(r["scenario"], rotation=0, ha="right", va="center", fontsize=8)
axes[-1, 0].set_xlabel("time (s)")
fig.suptitle("Mean CSI amplitude over time (all active subcarriers)")
plt.tight_layout()
fig.savefig(os.path.join(args.out, "amplitude_over_time.png"), dpi=160)
plt.close(fig)

# plot 3: waterfalls (columns decimated to <= ~3000 so long recordings stay quick)
fig, axes = plt.subplots(len(recs), 1, figsize=(10, 2.6 * len(recs)), squeeze=False)
vmax = max(np.percentile(r["Aa"], 99) for r in recs)
for ax, r in zip(axes[:, 0], recs):
    step = max(1, len(r["Aa"]) // 3000)
    im = ax.imshow(r["Aa"][::step].T, aspect="auto", origin="lower", cmap="viridis",
                   vmin=0, vmax=vmax, interpolation="nearest")
    ax.set_ylabel(f"{r['scenario']}\nsubcarrier", fontsize=8)
axes[-1, 0].set_xlabel("packets (time ->)" if all(max(1, len(r['Aa']) // 3000) == 1 for r in recs)
                       else "packets / decimation step (time ->)")
fig.colorbar(im, ax=axes[:, 0].tolist(), label="amplitude")
fig.suptitle("CSI amplitude waterfalls (same colour scale)")
fig.savefig(os.path.join(args.out, "waterfalls.png"), dpi=160)
plt.close(fig)

# plot 4: motion detector alarm rate
det = [(lab, r) for lab, r in zip(labels, rows) if r["alarm_rate_%"] != ""]
if det:
    fig, ax = plt.subplots(figsize=(max(6, 1.3 * len(det)), 4.5))
    bars = ax.bar([d[0] for d in det], [d[1]["alarm_rate_%"] for d in det],
                  color=[PREFIX_COLORS.get(prefix_of(d[1]["scenario"]), "#777777") for d in det])
    ax.bar_label(bars, fmt="%.0f%%", fontsize=8)
    ax.set_ylim(0, 105)
    ax.set_ylabel(f"% of {args.window:g}-s windows above threshold")
    ax.set_title("Motion detector alarm rate\n(threshold learned from the matching EMPTY recording; "
                 "high on FAN/AC/DOOR = false alarm)", fontsize=10)
    ax.tick_params(axis="x", labelsize=7)
    legend_for_prefixes(ax)
    plt.tight_layout()
    fig.savefig(os.path.join(args.out, "motion_alarm_rate.png"), dpi=160)
    plt.close(fig)

# plot 5: RSSI mean +/- std
fig, ax = plt.subplots(figsize=(width, 4.5))
ax.bar(labels, [r["rssi_mean_dBm"] for r in rows], yerr=[r["rssi_std_dB"] for r in rows],
       color=colors, capsize=3)
ax.set_ylabel("RSSI (dBm), mean +/- std")
ax.set_title("SPECTER: RSSI per scenario")
ax.tick_params(axis="x", labelsize=7)
legend_for_prefixes(ax)
plt.tight_layout()
fig.savefig(os.path.join(args.out, "rssi_by_scenario.png"), dpi=160)
plt.close(fig)

print(f"\nSaved results to: {args.out}")
