#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
M1 — Measurement Core: staged CPU stress test for Jetson Orin Nano
===================================================================
Project: Automated Stress Test — Security Robot QA
Milestone: M1 (first working version — CPU target, manual launch)

What it does (per the design dossier):
  1. Records metadata (board, power/fan mode, trip points read from device)
  2. Checks sensors are readable (abort if not)
  3. Measures a 30 s idle baseline (temperature relative to the room)
  4. Ramps CPU load 10% -> 100% in steps; at each level runs N trials,
     holds to steady state, logs every sample to CSV
  5. Safety (Layer 0, always active):
       - any zone >= CRITICAL_C  -> instant emergency stop (kill load)
       - any zone >= FAIL_C sustained > FAIL_SUSTAIN_S -> level FAILs
       - sustained clock below CLOCK_FLOOR of the pinned max -> throttle FAIL
       - cooldown to (idle + COOLDOWN_EPS_C) must finish within timeout
  6. Verdict PASS / FAIL with the failing stage and cause
  7. Outputs one run directory: metadata.json, samples.csv, levels.csv,
     report.txt, temp_vs_load.png, freq_vs_load.png

Build:
  JETSON-ONLY — the simulator has been removed from this file. Every run
  is a REAL stress test: stress-ng loads the cores, sysfs is read live,
  the safety gates act on real silicon. Keep the full version
  (m1_stress_test.py) on the laptop for logic dry-runs and demos.

Safety design notes:
  - stress-ng runs in its own process group; it is killed on ANY exit path
    (normal, failure, Ctrl-C, unhandled exception) via signal handlers +
    try/finally. The operator supervises every M1 run (no watchdog yet —
    that arrives in M2, per the roadmap).
  - This script never changes power mode / fan mode / clocks. Fixing those
    is an M0 manual step; the script only RECORDS them.

Usage examples (Jetson):
  python3 m1_stress_test_jetson.py --ambient-c 24.5 --levels 10 --trials 1   # shakedown
  python3 m1_stress_test_jetson.py --ambient-c 24.5 --humidity 60            # fast run
  python3 m1_stress_test_jetson.py --ambient-c 24.5 --profile deep           # calibration
"""

import argparse
import csv
import glob
import json
import os
import re
import shutil
import signal
import statistics
import subprocess
import sys
import time
from datetime import datetime

# ============================================================ configuration
CFG = {
    # ---- Layer 0 absolute limits (researched — see cahier de référence) --
    "FAIL_C": 90.0,           # qualified ceiling: sustained breach fails level
    "FAIL_SUSTAIN_S": 5.0,    # how long above FAIL_C counts as sustained
    "CRITICAL_C": 95.0,       # instant emergency stop (NVIDIA design headroom)
    "CLOCK_FLOOR": 0.98,      # sustained freq below 98% of pinned max = throttle
    "CLOCK_DIP_SUSTAIN_S": 4.0,
    # ---- ramp shape ------------------------------------------------------
    "LEVELS": list(range(10, 101, 10)),     # deep profile (full curve)
    "FAST_LEVELS": [10, 25, 50, 75, 100],   # fast profile (scheduled runs)
    "TRIALS_PER_LEVEL": 3,                  # deep: independent restart trials
    "PLATEAU_WINDOWS": 3,                   # fast: stat windows on ONE plateau
    # ---- steady state & timing ------------------------------------------
    "SAMPLE_PERIOD_S": 1.0,
    "MIN_HOLD_S": 45,         # minimum time at a level before steady check
    "MAX_HOLD_S": 150,        # give up waiting for steady after this
    "STEADY_WINDOW_S": 15,    # compare mean of last window vs previous window
    "STEADY_DELTA_C": 0.4,    # steady when windows differ by less than this
    "IDLE_BASELINE_S": 30,
    # ---- cooldown (M1 = generous fixed timeout; tau-based comes in M3) ---
    "COOLDOWN_EPS_C": 2.0,    # 'recovered' = within eps of idle baseline
    "COOLDOWN_TIMEOUT_S": 300,
    # ---- misc -------------------------------------------------------------
    "CPU_WORKERS": 0,         # 0 = all cores
    "OUT_ROOT": "runs",
}

STOP = {"requested": False}          # set by signal handlers
LOAD_PROC = {"p": None}              # current stress process (for cleanup)


# ============================================================ small helpers
def now_s():
    return time.monotonic()


def read_file(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return None


def run_cmd(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return -1, str(e)


def log(msg):
    try:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)
    except OSError:      # terminal gone (SSH drop) — files still get written
        pass


# ============================================================ sensor layer
class RealSensors:
    """Reads temperatures and CPU frequencies straight from sysfs.
    Zone names are DISCOVERED at runtime — nothing hardcoded."""

    def __init__(self):
        self.zones = {}                       # name -> temp path
        for z in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
            ztype = read_file(f"{z}/type")
            if ztype and read_file(f"{z}/temp"):
                self.zones[ztype] = f"{z}/temp"
        self.cpufreq = sorted(
            glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq"))
        # junction zone: prefer a 'tj' zone, else hottest reading wins later
        self.tj_name = next((n for n in self.zones if "tj" in n.lower()), None)
        # kernel cooling devices, CLASSIFIED:
        #   fan      = active cooling (fan spinning up) -> NORMAL, logged as data
        #   throttle = passive cooling (kernel capping frequency) -> real throttle
        #   other    = unknown types -> WARN, never abort (conservative)
        self.cooling = {}       # name -> (path, category)
        self.cooling_map = {"fan": [], "throttle": [], "other": []}
        THROTTLE_KEYS = ("cpu", "gpu", "freq", "emc", "dram", "balanced",
                         "throttle", "cap")
        for c in sorted(glob.glob("/sys/class/thermal/cooling_device*")):
            ctype = read_file(f"{c}/type")
            if not ctype or read_file(f"{c}/cur_state") is None:
                continue
            name = f"{ctype}({os.path.basename(c)})"
            low = ctype.lower()
            if "fan" in low:
                cat = "fan"
            elif any(k in low for k in THROTTLE_KEYS):
                cat = "throttle"
            else:
                cat = "other"
            self.cooling[name] = (f"{c}/cur_state", cat)
            self.cooling_map[cat].append(name)
        # fan tachometer / PWM via hwmon (discovered, not hardcoded)
        self.fan_paths = {"rpm": None, "pwm": None}
        for h in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
            nm = (read_file(f"{h}/name") or "").lower()
            if "fan" in nm or "tach" in nm:
                for cand in (f"{h}/rpm", f"{h}/fan1_input"):
                    if read_file(cand) is not None:
                        self.fan_paths["rpm"] = self.fan_paths["rpm"] or cand
                if read_file(f"{h}/pwm1") is not None:
                    self.fan_paths["pwm"] = self.fan_paths["pwm"] or f"{h}/pwm1"

    def cooling_snapshot(self):
        """Categorised view: {'throttle': {name: state>0}, 'other': {...},
        'fan': {name: state}} — fan states reported even at 0 (it's data)."""
        snap = {"fan": {}, "throttle": {}, "other": {}}
        for name, (path, cat) in self.cooling.items():
            raw = read_file(path)
            if raw is None or not raw.lstrip("-").isdigit():
                continue
            st = int(raw)
            if cat == "fan":
                snap["fan"][name] = st
            elif st > 0:
                snap[cat][name] = st
        return snap

    def fan_reading(self):
        out = {}
        for k, p in self.fan_paths.items():
            raw = read_file(p) if p else None
            out[k] = int(raw) if raw and raw.lstrip("-").isdigit() else None
        return out

    def governor(self):
        return (read_file(f"{self.cpufreq[0]}/scaling_governor")
                if self.cpufreq else None)

    def pinned_check(self):
        """Clocks are pinned when min == max on every core (jetson_clocks).
        Without pinning, the governor scales freq with load and speed
        readings reflect power management, not board health."""
        pairs = []
        for c in self.cpufreq:
            mn = read_file(f"{c}/scaling_min_freq")
            mx = read_file(f"{c}/scaling_max_freq")
            if mn and mx and mn.isdigit() and mx.isdigit():
                pairs.append((int(mn), int(mx)))
        pinned = bool(pairs) and all(mn == mx for mn, mx in pairs)
        return pinned, pairs

    def ceiling_khz(self):
        """Current allowed max — thermal capping LOWERS this below the
        value captured at test start."""
        vals = []
        for c in self.cpufreq:
            raw = read_file(f"{c}/scaling_max_freq")
            if raw and raw.isdigit():
                vals.append(int(raw))
        return max(vals) if vals else None

    def ok(self):
        return bool(self.zones) and bool(self.cpufreq)

    def temps(self):
        out = {}
        for name, path in self.zones.items():
            raw = read_file(path)
            if raw and raw.lstrip("-").isdigit():
                out[name] = int(raw) / 1000.0
        return out

    def junction(self, temps):
        if self.tj_name and self.tj_name in temps:
            return temps[self.tj_name]
        return max(temps.values()) if temps else float("nan")

    def freqs_khz(self):
        out = []
        for c in self.cpufreq:
            raw = read_file(f"{c}/scaling_cur_freq")
            if raw and raw.isdigit():
                out.append(int(raw))
        return out

    def pinned_max_khz(self):
        vals = []
        for c in self.cpufreq:
            raw = read_file(f"{c}/scaling_max_freq")
            if raw and raw.isdigit():
                vals.append(int(raw))
        return max(vals) if vals else None

    def trip_points(self):
        trips = []
        for z in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
            ztype = read_file(f"{z}/type") or "?"
            for tp in sorted(glob.glob(f"{z}/trip_point_*_temp")):
                tv = read_file(tp)
                tt = read_file(tp.replace("_temp", "_type")) or "?"
                if tv and tv.lstrip("-").isdigit():
                    trips.append(
                        {"zone": ztype, "type": tt, "temp_c": int(tv) / 1000.0})
        return trips


# ============================================================ load layer
class RealLoad:
    """stress-ng in its own process group; killable from any exit path."""

    def __init__(self, workers):
        self.workers = workers or (os.cpu_count() or 6)

    def start(self, level_pct):
        self.stop()
        cmd = ["stress-ng", "--cpu", str(self.workers),
               "--cpu-load", str(level_pct), "--quiet"]
        LOAD_PROC["p"] = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)

    def stop(self):
        p = LOAD_PROC["p"]
        if p and p.poll() is None:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
        LOAD_PROC["p"] = None


# ============================================================ run logic
class Abort(Exception):
    def __init__(self, cause, detail):
        super().__init__(detail)
        self.cause, self.detail = cause, detail


def read_oc_events():
    """Count over-current throttle lines in the kernel log (POWER throttling,
    a different diagnosis from thermal). Returns an int, or None when dmesg
    isn't readable without sudo (detection then reported as unavailable)."""
    rc, out = run_cmd(
        "dmesg 2>&1 | grep -ci -e over-current -e 'soctherm.*oc'", timeout=5)
    low = out.lower()
    if "not permitted" in low or "denied" in low:
        return None
    return int(out) if out.strip().isdigit() else (0 if rc == 1 else None)


def install_signal_handlers(load):
    def handler(signum, frame):
        STOP["requested"] = True
        log(f"signal {signum} received — stopping load and aborting safely")
        load.stop()
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
    if hasattr(signal, "SIGHUP"):        # Linux: terminal/SSH session died
        signal.signal(signal.SIGHUP, handler)


def sample_once(sensors, writer, run_t0, level, trial, phase):
    temps = sensors.temps()
    tj = sensors.junction(temps)
    freqs = sensors.freqs_khz()
    snap = sensors.cooling_snapshot()
    fan = sensors.fan_reading()
    fan_state = max(snap["fan"].values()) if snap["fan"] else ""
    thr_state = max(snap["throttle"].values()) if snap["throttle"] else 0
    row = {"t_s": round(now_s() - run_t0, 1), "level_pct": level,
           "trial": trial, "phase": phase, "tj_c": round(tj, 2),
           "freq_min_khz": min(freqs) if freqs else "",
           "freq_mean_khz": int(statistics.mean(freqs)) if freqs else "",
           "fan_rpm": fan.get("rpm") if fan.get("rpm") is not None else "",
           "fan_pwm": fan.get("pwm") if fan.get("pwm") is not None else "",
           "fan_state": fan_state, "throttle_state": thr_state}
    for z, v in temps.items():
        row[f"T_{z}"] = round(v, 2)
    writer.writerow(row)
    return temps, tj, freqs, snap, fan


def hold_at_level(sensors, load, writer, run_t0, level, trial, pinned, cfg,
                  windows=1, tctx=None):
    """Apply load, hold to steady state, enforce Layer 0 continuously.

    windows=1 (deep): returns [stats] for this one trial.
    windows=N (fast): after steady state is declared, keeps holding for
    N-1 further windows and returns [stats_1..stats_N] — N measurement
    windows carved out of ONE plateau. Steady-state temperature is a
    physics equilibrium, so the windows sample the same state the
    restart-trials would, without paying N ramps and N cooldowns.
    Safety gates stay active during the extension."""
    load.start(level)
    t_start = now_s()
    tctx = tctx or {}
    warns = tctx.setdefault("warnings", [])
    tj_hist, hot_hist, freq_mins = [], [], []
    fan_states, fan_rpms = [], []
    over_fail_since, dip_since, cool_since, other_since = None, None, None, None
    thr_peak = 0
    warned_other = warned_oc = False
    steady_idx = None            # sample count when steady was declared
    win = max(2, int(cfg["STEADY_WINDOW_S"] / cfg["SAMPLE_PERIOD_S"]))
    try:
      while True:
        if STOP["requested"]:
            raise Abort("operator", "stopped by operator (signal)")
        temps, tj, freqs, snap, fan = sample_once(
            sensors, writer, run_t0, level, trial, "stress")
        tj_hist.append(tj)
        hottest = max(temps.values())
        hot_hist.append(hottest)
        fmin = min(freqs) if freqs else 0
        freq_mins.append(fmin)
        fan_states.append(max(snap["fan"].values()) if snap["fan"] else 0)
        if fan.get("rpm") is not None:
            fan_rpms.append(fan["rpm"])
        elif fan.get("pwm") is not None:
            fan_rpms.append(fan["pwm"])

        # ---- Layer 0: temperature ----
        if hottest >= cfg["CRITICAL_C"]:
            raise Abort("temperature-critical",
                        f"{hottest:.1f} °C >= {cfg['CRITICAL_C']} °C "
                        f"(instant stop) at level {level}%")
        if hottest >= cfg["FAIL_C"]:
            over_fail_since = over_fail_since or now_s()
            if now_s() - over_fail_since > cfg["FAIL_SUSTAIN_S"]:
                raise Abort("temperature",
                            f"sustained {hottest:.1f} °C >= {cfg['FAIL_C']} °C "
                            f"at level {level}%")
        else:
            over_fail_since = None

        # ---- Layer 0: throttle, four signals (fan is NOT one of them) ----
        # (1) AUTHORITATIVE — passive (frequency-capping) cooling engaged
        thr = snap["throttle"]
        if thr:
            thr_peak = max(thr_peak, max(thr.values()))
            cool_since = cool_since or now_s()
            if now_s() - cool_since > 2.0:
                raise Abort("throttle-thermal",
                            "kernel frequency-capping active at level "
                            f"{level}%: " + ", ".join(
                                f"{k}={v}" for k, v in thr.items()))
        else:
            cool_since = None
        # unknown cooling device types -> WARN once, never abort
        if snap["other"]:
            other_since = other_since or now_s()
            if now_s() - other_since > 2.0 and not warned_other:
                warned_other = True
                warns.append(
                    f"level {level}%: unclassified cooling device active "
                    "(save the device list to classify it): " + ", ".join(
                        f"{k}={v}" for k, v in snap["other"].items()))
        else:
            other_since = None
        # (2) AUTHORITATIVE — the kernel lowered the allowed frequency ceiling
        ceil0 = tctx.get("ceiling0")
        ceil = sensors.ceiling_khz()
        if ceil0 and ceil and ceil < ceil0 * 0.995:
            raise Abort("throttle-thermal",
                        f"frequency ceiling lowered by the kernel: "
                        f"{ceil/1000:.0f} MHz < initial {ceil0/1000:.0f} MHz "
                        f"at level {level}%")
        # (3) over-current events -> WARN + continue; the CONSEQUENCE
        #     signals (ceiling drop / sustained dip) decide any abort
        if tctx.get("oc0") is not None and len(tj_hist) % 5 == 0:
            oc = read_oc_events()
            if oc is not None and oc > tctx["oc0"]:
                tctx["oc0"] = oc
                if not warned_oc:
                    warned_oc = True
                    warns.append(
                        f"level {level}%: over-current event in the kernel "
                        "log (power budget); clocks were NOT capped — "
                        "recorded, test continued")
        # (4) cross-check — sustained dip below the pinned max
        #     (only meaningful when clocks are pinned)
        if tctx.get("pinned", True) and pinned and \
                fmin < pinned * cfg["CLOCK_FLOOR"]:
            dip_since = dip_since or now_s()
            if now_s() - dip_since > cfg["CLOCK_DIP_SUSTAIN_S"]:
                raise Abort("throttle-dip",
                            f"clock {fmin/1000:.0f} MHz < "
                            f"{cfg['CLOCK_FLOOR']*100:.0f}% of pinned "
                            f"{pinned/1000:.0f} MHz at level {level}%")
        else:
            dip_since = None

        # ---- steady-state detection, then window extension ----
        held = now_s() - t_start
        if steady_idx is None:
            if held >= cfg["MIN_HOLD_S"] and len(tj_hist) >= 2 * win:
                a = statistics.mean(tj_hist[-win:])
                b = statistics.mean(tj_hist[-2 * win:-win])
                if abs(a - b) < cfg["STEADY_DELTA_C"] or held >= cfg["MAX_HOLD_S"]:
                    steady_idx = len(tj_hist)
            elif held >= cfg["MAX_HOLD_S"]:
                steady_idx = len(tj_hist)
        else:
            if len(tj_hist) - steady_idx >= (windows - 1) * win:
                break
        time.sleep(cfg["SAMPLE_PERIOD_S"])
    except Abort as e:
        load.stop()
        e.level = level
        n = min(win, len(tj_hist))
        if n >= 3:
            hz = max(hot_hist[-n:])
            e.partial = {
                "tj_c": round(statistics.mean(tj_hist[-n:]), 2),
                "hottest_zone_c": round(hz, 2),
                "freq_min_khz": min(freq_mins[-n:]),
                "margin_to_90_c": round(90.0 - hz, 2),
                "throttle_peak": thr_peak,
                "fan_state": max(fan_states[-n:]) if fan_states else 0,
                "fan_rpm": (round(statistics.mean(fan_rpms[-min(n, len(fan_rpms)):]))
                            if fan_rpms else None),
                "held_s": round(now_s() - t_start, 1)}
        raise

    load.stop()
    total_held = round(now_s() - t_start, 1)

    # slice the plateau tail into `windows` equal windows
    need = windows * win
    seg_tj = tj_hist[-need:]
    seg_hot = hot_hist[-need:]
    seg_fmn = freq_mins[-need:]
    stats_list = []
    for i in range(windows):
        a, b = i * win, (i + 1) * win
        hz = max(seg_hot[a:b])
        stats_list.append({
            "tj_c": round(statistics.mean(seg_tj[a:b]), 2),
            "hottest_zone_c": round(hz, 2),
            "freq_min_khz": min(seg_fmn[a:b]),
            "margin_to_90_c": round(90.0 - hz, 2),
            "throttle_peak": thr_peak,
            "fan_state": max(fan_states[-need:]) if fan_states else 0,
            "fan_rpm": (round(statistics.mean(fan_rpms[-min(need, len(fan_rpms)):]))
                        if fan_rpms else None),
            "held_s": total_held})
    return stats_list


def fit_tau(ts, tjs, asymptote_c):
    """Log-linear least-squares fit of an exponential decay toward the
    asymptote (Newton cooling): T(t) = asym + dT0 * exp(-t/tau).
    Uses only points still >= 1 °C above the asymptote (log validity).
    Returns tau in seconds, or None if the data can't support a fit."""
    import math
    xs, ys = [], []
    for t, tj in zip(ts, tjs):
        d = tj - asymptote_c
        if d >= 1.0:
            xs.append(t)
            ys.append(math.log(d))
    if len(xs) < 6:
        return None
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0 or sxy >= 0:          # slope must be negative for a decay
        return None
    return round(-1.0 / (sxy / sxx), 1)


def cooldown(sensors, writer, run_t0, level, trial, idle_tj, cfg,
             phase="cooldown"):
    """Wait for recovery to idle+eps; also fit the cooling time constant
    tau from the decay curve. Returns (elapsed_s, tau_s_or_None)."""
    t0 = now_s()
    target = idle_tj + cfg["COOLDOWN_EPS_C"]
    ts, tjs = [], []
    while True:
        if STOP["requested"]:
            raise Abort("operator", "stopped by operator during cooldown")
        temps, tj, _, _, _ = sample_once(
            sensors, writer, run_t0, level, trial, phase)
        ts.append(now_s() - t0)
        tjs.append(tj)
        if tj <= target:
            return round(now_s() - t0, 1), fit_tau(ts, tjs, idle_tj)
        if now_s() - t0 > cfg["COOLDOWN_TIMEOUT_S"]:
            raise Abort("cooling",
                        f"did not return to {target:.1f} °C within "
                        f"{cfg['COOLDOWN_TIMEOUT_S']} s after level {level}%")
        time.sleep(cfg["SAMPLE_PERIOD_S"])


# ============================================================ reporting
def write_graphs(outdir, level_rows, fail_cause=None):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        log("matplotlib not available — skipping graphs (CSV data is complete)")
        return []
    ok = [r for r in level_rows if r.get("status") != "FAILED"]
    bad = [r for r in level_rows if r.get("status") == "FAILED"]
    made = []

    def annotate_fail(ax, x, y):
        ax.plot([x], [y], marker="x", markersize=13, markeredgewidth=3,
                color="#993C1D", linestyle="none", zorder=5,
                label="aborted here")
        ax.annotate(f"ABORT: {fail_cause or 'failure'}", (x, y),
                    textcoords="offset points", xytext=(8, 10),
                    fontsize=9, color="#993C1D", fontweight="bold")

    # ---- f(load) = temperature ----
    fig, ax = plt.subplots(figsize=(7, 4.2))
    if ok:
        ax.errorbar([r["level_pct"] for r in ok],
                    [r["tj_mean_c"] for r in ok],
                    yerr=[r["tj_std_c"] for r in ok],
                    marker="o", capsize=4, color="#0F6E56",
                    label="junction (tj)")
    for r in bad:
        annotate_fail(ax, r["level_pct"], r["tj_mean_c"])
    ax.axhline(90, color="#993C1D", ls="--", lw=1.2, label="90 °C fail line")
    ax.axhline(95, color="#6E2A12", ls=":", lw=1.2, label="95 °C emergency stop")
    ax.set_xlabel("stress level (%)"); ax.set_ylabel("temperature (°C)")
    ax.set_title("f(load) = steady-state temperature"); ax.legend()
    ax.grid(alpha=0.3)
    p = os.path.join(outdir, "temp_vs_load.png")
    fig.tight_layout(); fig.savefig(p, dpi=150); plt.close(fig); made.append(p)

    # ---- g(load) = frequency ----
    fig, ax = plt.subplots(figsize=(7, 4.2))
    if ok:
        ax.plot([r["level_pct"] for r in ok],
                [r["freq_min_mhz"] for r in ok],
                marker="s", color="#185FA5", label="min sustained CPU clock")
    for r in bad:
        annotate_fail(ax, r["level_pct"], r["freq_min_mhz"])
    if level_rows and level_rows[0].get("pinned_mhz"):
        ax.axhline(level_rows[0]["pinned_mhz"], color="#5F5E5A", ls="--",
                   lw=1.2, label="pinned max")
    ax.set_xlabel("stress level (%)"); ax.set_ylabel("frequency (MHz)")
    ax.set_title("g(load) = sustained clock (flat = healthy)"); ax.legend()
    ax.grid(alpha=0.3)
    p = os.path.join(outdir, "freq_vs_load.png")
    fig.tight_layout(); fig.savefig(p, dpi=150); plt.close(fig); made.append(p)

    # ---- fan(load) = fan speed + cooling state zones ----
    rows_fan = [r for r in level_rows if r.get("fan_rpm") is not None
                or r.get("fan_state") is not None]
    if rows_fan:
        fig, ax = plt.subplots(figsize=(7, 4.2))
        xs = [r["level_pct"] for r in rows_fan]
        ys = [r.get("fan_rpm") or 0 for r in rows_fan]
        states = [r.get("fan_state", 0) for r in rows_fan]
        # background zones per fan state (mode 0, 1, 2, ...)
        zone_cols = ["#F1EFE8", "#FAEEDA", "#FAD9C4", "#F0997B", "#E1F5EE"]
        zones_drawn = []
        i = 0
        while i < len(xs):
            j = i
            while j + 1 < len(xs) and states[j + 1] == states[i]:
                j += 1
            x0 = xs[i] - 4 if i == 0 else (xs[i - 1] + xs[i]) / 2
            x1 = xs[j] + 4 if j == len(xs) - 1 else (xs[j] + xs[j + 1]) / 2
            ax.axvspan(x0, x1, color=zone_cols[states[i] % len(zone_cols)],
                       alpha=0.55, zorder=0)
            zones_drawn.append((x0, x1, states[i]))
            i = j + 1
        ax.plot(xs, ys, marker="o", color="#0F6E56", zorder=3,
                label="fan speed")
        ylo, yhi = ax.get_ylim()
        for x0, x1, st in zones_drawn:
            ax.text((x0 + x1) / 2, yhi - 0.04 * (yhi - ylo),
                    f"fan mode {st}", ha="center", va="top",
                    fontsize=8.5, color="#5F5E5A", zorder=4)
        for x, y, st in zip(xs, ys, states):
            ax.annotate(f"S{st}", (x, y), textcoords="offset points",
                        xytext=(0, -14), ha="center", fontsize=8.5,
                        color="#04342C")
        for r in bad:
            if r in rows_fan:
                annotate_fail(ax, r["level_pct"], r.get("fan_rpm") or 0)
        unit = "RPM" if any(r.get("fan_rpm") for r in rows_fan) else "PWM"
        ax.set_xlabel("stress level (%)")
        ax.set_ylabel(f"fan speed ({unit})")
        ax.set_title("fan(load) = fan speed and cooling mode")
        ax.grid(alpha=0.3, zorder=1)
        p = os.path.join(outdir, "fan_vs_load.png")
        fig.tight_layout(); fig.savefig(p, dpi=150); plt.close(fig)
        made.append(p)
    return made


def write_report(outdir, meta, level_rows, verdict, cause, detail, notes,
                 warnings=None):
    lines = []
    a = lines.append
    a("=" * 66)
    a("STRESS TEST REPORT — M1 measurement core (CPU target)")
    a("=" * 66)
    a(f"VERDICT: {verdict}" + (f"  |  cause: {cause}" if cause else ""))
    if detail:
        a(f"         {detail}")
    a("")
    a("--- metadata " + "-" * 51)
    for k, v in meta.items():
        a(f"{k:22s}: {v}")
    a("")
    a("--- results per level (mean of trials, steady-state) " + "-" * 11)
    a(f"{'level':>6} {'tj °C':>8} {'±σ':>6} {'hottest °C':>11} "
      f"{'min clock MHz':>14} {'margin→90 °C':>13} {'fan':>5}")
    for r in level_rows:
        fan = (f"S{r.get('fan_state', 0)}"
               + (f"/{r['fan_rpm']}" if r.get('fan_rpm') else ""))
        line = (f"{r['level_pct']:>5}% {r['tj_mean_c']:>8.1f} "
                f"{r['tj_std_c']:>6.2f} {r['hottest_mean_c']:>11.1f} "
                f"{r['freq_min_mhz']:>14.0f} {r['margin_mean_c']:>13.1f} "
                f"{fan:>5}")
        if r.get("status") == "FAILED":
            line += "   <-- ABORTED AT THIS LEVEL"
        a(line)
    if warnings:
        a("")
        a("--- warnings (recorded, test continued) " + "-" * 24)
        for w in warnings:
            a("  ! " + w)
    if notes:
        a("")
        a("--- notes " + "-" * 54)
        for n in notes:
            a("  * " + n)
    a("")
    a("Files: samples.csv (every second), levels.csv (summary), graphs (.png)")
    a("=" * 66)
    txt = "\n".join(lines)
    with open(os.path.join(outdir, "report.txt"), "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    try:
        print("\n" + txt)
    except UnicodeEncodeError:  # exotic redirected consoles
        print("\n" + txt.encode("ascii", "replace").decode())


# ============================================================ main
def main():
    ap = argparse.ArgumentParser(description="M1 staged CPU stress test")
    ap.add_argument("--ambient-c", type=float, required=False,
                    help="room temperature in °C (manual input for M1)")
    ap.add_argument("--humidity", type=float, default=None,
                    help="room relative humidity %% (optional, recorded)")
    ap.add_argument("--levels", type=str, default=None,
                    help="comma list, e.g. 10,50,100 (default 10..100)")
    ap.add_argument("--trials", type=int, default=None)
    ap.add_argument("--profile", choices=["fast", "deep"], default="fast",
                    help="fast: 5 levels, no per-level cooldowns, 3 windows "
                         "on one plateau, one final decay for tau (~10-12 min)"
                         " | deep: full 10-level, 3 restart trials, full "
                         "cooldowns (calibration & weekly)")
    args = ap.parse_args()

    cfg = dict(CFG)
    profile = args.profile
    if args.levels:
        cfg["LEVELS"] = [int(x) for x in args.levels.split(",")]
    elif profile == "fast":
        cfg["LEVELS"] = cfg["FAST_LEVELS"]
    if args.trials:
        cfg["TRIALS_PER_LEVEL"] = args.trials    # deep: restart trials
        cfg["PLATEAU_WINDOWS"] = args.trials     # fast: plateau windows

    if args.ambient_c is None:
        ap.error("--ambient-c is required (read the room thermometer)")

    # ---- sensors & load (real hardware only) ----
    if not shutil.which("stress-ng"):
        sys.exit("stress-ng not found — run M0 setup first "
                 "(sudo apt install stress-ng)")
    sensors = RealSensors()
    load = RealLoad(cfg["CPU_WORKERS"])
    mode = "REAL"

    install_signal_handlers(load)

    # ---- pre-flight: sensor check (abort-if-unreadable, per the flow) ----
    if not sensors.ok():
        sys.exit("SENSOR CHECK FAILED: thermal zones or cpufreq not readable. "
                 "Test abandoned (couldn't be done) — fix the bench first.")
    pinned_ok, freq_pairs = sensors.pinned_check()
    gov = sensors.governor()
    if not pinned_ok:
        seen = ", ".join(f"({mn//1000}-{mx//1000} MHz)"
                         for mn, mx in freq_pairs[:6])
        sys.exit(
            "CLOCKS NOT PINNED — the CPU governor "
            f"('{gov}') is scaling frequency with load, so speed readings "
            "would reflect power management, not board health.\n"
            "This is normal Linux behaviour, not a fault. Fix (M0 step 3):\n"
            "    sudo nvpmodel -q          # confirm the chosen mode\n"
            "    sudo jetson_clocks        # pin clocks at the mode maximum\n"
            "then re-run the test. Per-core (min-max) seen: " + seen)
    pinned = sensors.pinned_max_khz()
    oc0 = read_oc_events()
    tctx = {"ceiling0": sensors.ceiling_khz(), "oc0": oc0,
            "pinned": pinned_ok, "warnings": []}

    # ---- run directory ----
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = os.path.join(cfg["OUT_ROOT"], f"run_{stamp}")
    os.makedirs(outdir, exist_ok=True)

    # ---- metadata (recorded, never assumed) ----
    rc, nvp = run_cmd("nvpmodel -q 2>/dev/null")
    fanmode = run_cmd(
        "grep -m1 FAN_DEFAULT_PROFILE /etc/nvfancontrol.conf 2>/dev/null")[1]
    meta = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "board_model": (read_file("/proc/device-tree/model") or "n/a (sim)"
                        ).replace("\x00", ""),
        "l4t_release": (read_file("/etc/nv_tegra_release") or "n/a"
                        ).split(",")[0],
        "power_mode": nvp.replace("\n", " / ") if rc == 0 and nvp else "n/a",
        "fan_mode": fanmode or "n/a",
        "pinned_max_mhz": round(pinned / 1000) if pinned else "n/a",
        "ambient_c": args.ambient_c,
        "humidity_pct": args.humidity if args.humidity is not None else "n/a",
        "profile": profile,
        "levels": ",".join(map(str, cfg["LEVELS"])),
        "trials_per_level": (cfg["TRIALS_PER_LEVEL"] if profile == "deep"
                             else f"{cfg['PLATEAU_WINDOWS']} plateau windows"),
        "limits": f"fail>={cfg['FAIL_C']}°C sustained; "
                  f"critical>={cfg['CRITICAL_C']}°C instant; "
                  f"clock floor {cfg['CLOCK_FLOOR']*100:.0f}%",
        "zones_found": ",".join(sorted(sensors.temps().keys())),
        "cpu_governor": gov or "n/a",
        "clocks_pinned": pinned_ok,
        "cooling_devices": " ".join(
            f"{k}:{len(v)}" for k, v in sensors.cooling_map.items()),
        "throttle_signals": ("kernel-cooling + ceiling-drop + dip"
                             + (" + over-current(dmesg)" if oc0 is not None
                                else " | over-current: unavailable "
                                     "(dmesg needs sudo)")),
    }
    with open(os.path.join(outdir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta,
                   "trip_points_from_device": sensors.trip_points(),
                   "cooling_device_classification": sensors.cooling_map,
                   "config": cfg}, f, indent=2)
    log(f"mode: {mode} | output: {outdir}")
    log(f"zones: {meta['zones_found']}")
    log(f"pinned max: {meta['pinned_max_mhz']} MHz | ambient {args.ambient_c} °C")

    # ---- CSV sample log ----
    zone_cols = [f"T_{z}" for z in sorted(sensors.temps().keys())]
    fcsv = open(os.path.join(outdir, "samples.csv"), "w", newline="", encoding="utf-8")
    writer = csv.DictWriter(fcsv, fieldnames=[
        "t_s", "level_pct", "trial", "phase", "tj_c",
        "freq_min_khz", "freq_mean_khz", "fan_rpm", "fan_pwm",
        "fan_state", "throttle_state"] + zone_cols)
    writer.writeheader()
    run_t0 = now_s()

    verdict, cause, detail = "PASS", None, None
    level_rows, notes = [], []

    try:
        # ---- idle baseline ----
        log(f"measuring idle baseline ({cfg['IDLE_BASELINE_S']} s)...")
        idle_tjs = []
        t0 = now_s()
        while now_s() - t0 < cfg["IDLE_BASELINE_S"]:
            _, tj, _, _, _ = sample_once(sensors, writer, run_t0, 0, 0, "idle")
            idle_tjs.append(tj)
            time.sleep(cfg["SAMPLE_PERIOD_S"])
        idle_tj = statistics.mean(idle_tjs)
        idle_dT = idle_tj - args.ambient_c
        meta["idle_tj_c"] = round(idle_tj, 2)
        meta["idle_dT_c"] = round(idle_dT, 2)
        log(f"idle junction {idle_tj:.1f} °C  (ΔT over room {idle_dT:+.1f} °C)")
        if not (10 <= idle_dT <= 45):
            notes.append(f"idle ΔT {idle_dT:+.1f} °C is outside the plausible "
                         "25-30 °C neighbourhood — check fan/heatsink/ambient "
                         "value before trusting results (info only in M1).")

        # ---- the ramp ----
        for level in cfg["LEVELS"]:
            if profile == "fast":
                # ascending ramp, no cooldown between levels: steady state
                # is path-independent, so each plateau is measured directly
                log(f"level {level:3d}% — stressing to plateau "
                    f"({cfg['PLATEAU_WINDOWS']} windows)...")
                trial_stats = hold_at_level(sensors, load, writer, run_t0,
                                            level, 1, pinned, cfg,
                                            windows=cfg["PLATEAU_WINDOWS"],
                                            tctx=tctx)
                for i, st in enumerate(trial_stats, 1):
                    log(f"  window {i}: tj {st['tj_c']:.1f} °C | hottest "
                        f"{st['hottest_zone_c']:.1f} °C | min clock "
                        f"{st['freq_min_khz']/1000:.0f} MHz | margin→90 "
                        f"{st['margin_to_90_c']:.1f} °C")
            else:
                trial_stats = []
                for trial in range(1, cfg["TRIALS_PER_LEVEL"] + 1):
                    log(f"level {level:3d}%  trial {trial}/"
                        f"{cfg['TRIALS_PER_LEVEL']} — stressing...")
                    st = hold_at_level(sensors, load, writer, run_t0,
                                       level, trial, pinned, cfg,
                                       windows=1, tctx=tctx)[0]
                    log(f"  steady: tj {st['tj_c']:.1f} °C | hottest "
                        f"{st['hottest_zone_c']:.1f} °C | min clock "
                        f"{st['freq_min_khz']/1000:.0f} MHz | margin→90 "
                        f"{st['margin_to_90_c']:.1f} °C | held {st['held_s']} s")
                    cd, tau = cooldown(sensors, writer, run_t0, level, trial,
                                       idle_tj, cfg)
                    log(f"  cooled back in {cd} s"
                        + (f" (τ ≈ {tau} s)" if tau else ""))
                    st["cooldown_s"] = cd
                    st["tau_s"] = tau
                    trial_stats.append(st)

            row = {
                "level_pct": level,
                "tj_mean_c": round(statistics.mean(
                    [t["tj_c"] for t in trial_stats]), 2),
                "tj_std_c": round(statistics.pstdev(
                    [t["tj_c"] for t in trial_stats]), 2),
                "hottest_mean_c": round(statistics.mean(
                    [t["hottest_zone_c"] for t in trial_stats]), 2),
                "freq_min_mhz": round(min(
                    t["freq_min_khz"] for t in trial_stats) / 1000),
                "pinned_mhz": round(pinned / 1000) if pinned else None,
                "margin_mean_c": round(statistics.mean(
                    [t["margin_to_90_c"] for t in trial_stats]), 2),
                "throttle_peak": max(
                    t.get("throttle_peak", 0) for t in trial_stats),
                "fan_state": max(
                    t.get("fan_state", 0) for t in trial_stats),
                "fan_rpm": (round(statistics.mean(
                    [t["fan_rpm"] for t in trial_stats
                     if t.get("fan_rpm") is not None]))
                    if any(t.get("fan_rpm") is not None
                           for t in trial_stats) else None),
                "status": "ok",
            }
            if profile == "deep":
                row["cooldown_mean_s"] = round(statistics.mean(
                    [t["cooldown_s"] for t in trial_stats]), 1)
                taus = [t["tau_s"] for t in trial_stats if t.get("tau_s")]
                row["tau_mean_s"] = (round(statistics.mean(taus), 1)
                                     if taus else "")
            level_rows.append(row)

        # ---- fast profile: one final decay = tau fit + return to rest ----
        if profile == "fast":
            log("final decay — fitting τ and returning the board to rest...")
            cd, tau = cooldown(sensors, writer, run_t0, cfg["LEVELS"][-1], 0,
                               idle_tj, cfg, phase="final-decay")
            meta["final_recovery_s"] = cd
            meta["tau_s"] = tau if tau else "n/a"
            log(f"recovered in {cd} s" + (f" | τ ≈ {tau} s" if tau else ""))
            notes.append(
                f"fast profile: cooling time constant τ ≈ {tau} s, full "
                f"recovery in {cd} s (one decay measurement — τ is a "
                f"property of the cooling hardware, not of the load level)"
                if tau else
                f"fast profile: recovered in {cd} s (decay too short for a "
                f"reliable τ fit)")
    except Abort as e:
        verdict, cause, detail = "FAIL", e.cause, e.detail
        log(f"ABORT ({e.cause}): {e.detail}")
        p = getattr(e, "partial", None)
        if p:
            level_rows.append({
                "level_pct": getattr(e, "level", 0),
                "tj_mean_c": p["tj_c"], "tj_std_c": 0.0,
                "hottest_mean_c": p["hottest_zone_c"],
                "freq_min_mhz": round(p["freq_min_khz"] / 1000),
                "pinned_mhz": round(pinned / 1000) if pinned else None,
                "margin_mean_c": p["margin_to_90_c"],
                "throttle_peak": p.get("throttle_peak", 0),
                "fan_state": p.get("fan_state", 0),
                "fan_rpm": p.get("fan_rpm"),
                "status": "FAILED"})
    finally:
        load.stop()                      # the load dies on EVERY path
        fcsv.close()

    # ---- levels.csv ----
    if level_rows:
        with open(os.path.join(outdir, "levels.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(level_rows[0].keys()),
                               restval="", extrasaction="ignore")
            w.writeheader()
            w.writerows(level_rows)

    warnings = tctx.get("warnings", [])
    if verdict == "PASS" and warnings:
        verdict = "WARN"
    graphs = write_graphs(outdir, level_rows, cause) if level_rows else []
    write_report(outdir, meta, level_rows, verdict, cause, detail, notes,
                 warnings)
    log(f"done — everything in {outdir}" +
        (f" ({len(graphs)} graphs)" if graphs else ""))
    sys.exit({"PASS": 0, "WARN": 1}.get(verdict, 2))


if __name__ == "__main__":
    main()
