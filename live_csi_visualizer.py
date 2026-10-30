"""
live_csi_visualizer.py

Reads raw CSI_DATA lines straight from the RX ESP32's serial port and shows
a live view instead of scrolling numbers:

  - Top panel : amplitude "waterfall" (time on x-axis, subcarrier index on
                y-axis, color = signal amplitude). Motion in the room shows
                up as visible streaks / shifting bands.
  - Bottom panel: RSSI over the last N seconds, so you can watch signal
                  stability at a glance.

Usage:
    python live_csi_visualizer.py --port COM5

Requirements (install once, inside the ESP-IDF venv terminal):
    pip install pyserial matplotlib numpy

Close the plot window or press Ctrl+C in the terminal to stop.
Only one program can use the serial port at a time, so make sure
idf.py monitor is NOT running when you launch this.
"""

import argparse
import re
import sys
import time
from collections import deque

import numpy as np
import serial
import matplotlib.pyplot as plt
import matplotlib.animation as animation

CSI_LINE_RE = re.compile(r'"(\[[^\]]*\])"')


def parse_csi_line(line):
    """Return (rssi, amplitudes) for a CSI_DATA line, or None if unparseable."""
    if not line.startswith("CSI_DATA"):
        return None

    m = CSI_LINE_RE.search(line)
    if not m:
        return None

    prefix = line[: m.start()].rstrip(",")
    fields = prefix.split(",")
    if len(fields) < 4:
        return None

    try:
        rssi = int(fields[3])
    except ValueError:
        return None

    try:
        data = [int(x) for x in m.group(1).strip("[]").split(",")]
    except ValueError:
        return None

    # First 4 values are junk (first_word_invalid), rest are
    # (imaginary, real) pairs -> amplitude = sqrt(im^2 + re^2)
    amplitudes = []
    for i in range(4, len(data) - 1, 2):
        im, re_ = data[i], data[i + 1]
        amplitudes.append((im * im + re_ * re_) ** 0.5)

    return rssi, np.array(amplitudes)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True, help="e.g. COM5")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--history", type=int, default=200,
                     help="number of packets kept on screen (default 200)")
    args = ap.parse_args()

    try:
        ser = serial.Serial(args.port, args.baud, timeout=1)
    except serial.SerialException as e:
        print(f"Could not open {args.port}: {e}")
        print("Is idf.py monitor still running on this port? Close it first.")
        sys.exit(1)

    print(f"Listening on {args.port} @ {args.baud} baud. Waiting for CSI_DATA...")

    n_subcarriers = None
    waterfall = None
    rssi_hist = deque(maxlen=args.history)
    rate_hist = deque(maxlen=50)  # for a rough packets/sec readout
    last_count_time = time.time()
    packet_counter = 0

    fig, (ax_wf, ax_rssi) = plt.subplots(
        2, 1, figsize=(10, 7), gridspec_kw={"height_ratios": [3, 1]}
    )
    fig.suptitle("Live CSI — waterfall (top) and RSSI (bottom)")
    im = None
    (rssi_line,) = ax_rssi.plot([], [])
    ax_rssi.set_ylabel("RSSI (dBm)")
    ax_rssi.set_xlabel("packets (most recent →)")

    def init_waterfall(n_sub):
        nonlocal waterfall, im
        waterfall = np.zeros((n_sub, args.history))
        im = ax_wf.imshow(
            waterfall, aspect="auto", origin="lower", cmap="viridis",
            interpolation="nearest",
        )
        ax_wf.set_ylabel("subcarrier index")
        ax_wf.set_xlabel("packets (most recent →)")
        fig.colorbar(im, ax=ax_wf, label="amplitude")

    def update(_frame):
        nonlocal n_subcarriers, waterfall, packet_counter, last_count_time
        updated = False

        # Drain whatever is waiting in the serial buffer this tick
        while ser.in_waiting:
            raw = ser.readline().decode(errors="ignore").strip()
            parsed = parse_csi_line(raw)
            if parsed is None:
                continue
            rssi, amps = parsed

            if n_subcarriers is None:
                n_subcarriers = len(amps)
                init_waterfall(n_subcarriers)
            elif len(amps) != n_subcarriers:
                continue  # skip malformed/short packets

            waterfall[:, :-1] = waterfall[:, 1:]
            waterfall[:, -1] = amps
            rssi_hist.append(rssi)
            packet_counter += 1
            updated = True

        if not updated or im is None:
            return []

        im.set_data(waterfall)
        im.set_clim(vmin=waterfall.min(), vmax=max(waterfall.max(), 1))

        rssi_line.set_data(range(len(rssi_hist)), list(rssi_hist))
        ax_rssi.set_xlim(0, args.history)
        if rssi_hist:
            ax_rssi.set_ylim(min(rssi_hist) - 3, max(rssi_hist) + 3)

        now = time.time()
        if now - last_count_time >= 1.0:
            rate_hist.append(packet_counter / (now - last_count_time))
            packet_counter = 0
            last_count_time = now
            avg_rate = sum(rate_hist) / len(rate_hist)
            ax_wf.set_title(f"~{avg_rate:.0f} packets/sec")

        return [im, rssi_line]

    ani = animation.FuncAnimation(fig, update, interval=100, cache_frame_data=False)
    plt.tight_layout()
    try:
        plt.show()
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()


if __name__ == "__main__":
    main()
