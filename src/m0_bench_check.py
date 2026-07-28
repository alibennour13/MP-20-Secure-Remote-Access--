#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
M0 Bench-Readiness Check — Jetson Orin Nano stress-test project
================================================================
READ-ONLY: this script changes nothing on the system. It verifies that
everything Milestone 1 needs is present and readable, and captures a raw
tegrastats sample that M1's parser will be written against.

Run on the Jetson:   python3 m0_bench_check.py
Outputs:             bench_report.txt  +  tegrastats_sample.txt
Then send both files back for M1 development.
"""

import glob
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime

OK, WARN, FAIL, INFO = "[ OK ]", "[ !! ]", "[FAIL]", "[ -- ]"
report_lines = []
summary = []          # (status, short label) for the final checklist
tegrastats_sample = ""


def echo(line=""):
    print(line)
    report_lines.append(line)


def run(cmd, timeout=10):
    """Run a command, return (returncode, stdout+stderr) — never raises."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, "(timed out)"
    except Exception as e:
        return -2, f"(error: {e})"


def read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return None


def section(title):
    echo()
    echo("=" * 62)
    echo(title)
    echo("=" * 62)


def check(status, label, detail=""):
    echo(f"{status} {label}" + (f" — {detail}" if detail else ""))
    summary.append((status, label))


# ---------------------------------------------------------------- header
echo("M0 BENCH-READINESS REPORT")
echo(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
echo(f"Host: {platform.node()}  |  Kernel: {platform.release()}")

# ---------------------------------------------------------------- 1. identity
section("1. BOARD IDENTITY")
model = read("/proc/device-tree/model")
if model:
    check(OK, "Board model", model.replace("\x00", ""))
    if "Orin" not in model:
        check(WARN, "Model is not an Orin", "verify this is the right board")
else:
    check(FAIL, "Board model unreadable",
          "not a Jetson? (running on a PC is fine for a dry run)")

l4t = read("/etc/nv_tegra_release")
if l4t:
    check(OK, "L4T / JetPack release", l4t.split(",")[0])
    echo(f"       full: {l4t}")
else:
    check(WARN, "L4T release file missing", "JetPack not detected")

# ---------------------------------------------------------------- 2. power mode
section("2. POWER MODE & CLOCK LOCK (must be FIXED and RECORDED)")
if shutil.which("nvpmodel"):
    rc, out = run("nvpmodel -q")
    if rc == 0 and out:
        check(OK, "Current power mode", " / ".join(out.splitlines()))
    else:
        rc2, out2 = run("sudo -n nvpmodel -q")
        if rc2 == 0:
            check(OK, "Current power mode", " / ".join(out2.splitlines()))
        else:
            check(WARN, "nvpmodel present but query failed",
                  "try: sudo nvpmodel -q")
else:
    check(FAIL, "nvpmodel not found", "is this a Jetson with JetPack?")

conf = read("/etc/nvpmodel.conf")
if conf:
    modes = [l.split(">")[-1].strip() for l in conf.splitlines()
             if l.strip().startswith("< POWER_MODEL")]
    if modes:
        echo(f"       available modes: {'; '.join(modes)}")

if shutil.which("jetson_clocks"):
    rc, out = run("jetson_clocks --show", timeout=15)
    src = out if rc == 0 else run("sudo -n jetson_clocks --show", timeout=15)[1]
    if "SOC family" in src or "cpu" in src.lower():
        check(OK, "jetson_clocks readable", "state captured below")
        echo("       --- jetson_clocks --show ---")
        for l in src.splitlines():
            echo("       " + l)
    else:
        check(WARN, "jetson_clocks present, needs sudo to show",
              "run once manually: sudo jetson_clocks --show")
else:
    check(FAIL, "jetson_clocks not found")

# ---------------------------------------------------------------- 3. thermal
section("3. THERMAL ZONES & TRIP POINTS (the test's eyes for heat)")
zones = sorted(glob.glob("/sys/class/thermal/thermal_zone*"))
if zones:
    readable = 0
    for z in zones:
        ztype = read(f"{z}/type") or "?"
        traw = read(f"{z}/temp")
        temp = f"{int(traw)/1000:.1f} °C" if traw and traw.lstrip("-").isdigit() else "unreadable"
        if traw:
            readable += 1
        echo(f"       {os.path.basename(z):16s} {ztype:20s} {temp}")
        trips = sorted(glob.glob(f"{z}/trip_point_*_temp"))
        for tp in trips:
            tv = read(tp)
            tt = read(tp.replace("_temp", "_type")) or "?"
            if tv and tv.lstrip("-").isdigit():
                echo(f"          trip {os.path.basename(tp).split('_')[2]:3s}"
                     f" {tt:10s} {int(tv)/1000:.1f} °C")
    if readable == len(zones) and readable > 0:
        check(OK, f"All {readable} thermal zones readable")
    elif readable:
        check(WARN, f"Only {readable}/{len(zones)} zones readable")
    else:
        check(FAIL, "No thermal zone temperatures readable")
else:
    check(FAIL, "No thermal zones found", "expected on a PC; a problem on the Jetson")

# ---------------------------------------------------------------- 4. clocks
section("4. CLOCK READINGS (the test's eyes for speed)")
cpus = sorted(glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq"))
if cpus:
    ok_cnt = 0
    for c in cpus:
        cur, mx = read(f"{c}/scaling_cur_freq"), read(f"{c}/cpuinfo_max_freq")
        if cur and mx:
            ok_cnt += 1
            echo(f"       {c.split('/')[-2]:6s} cur {int(cur)/1000:7.0f} MHz"
                 f"   max {int(mx)/1000:7.0f} MHz")
    check(OK if ok_cnt == len(cpus) else WARN,
          f"CPU frequency readable on {ok_cnt}/{len(cpus)} cores")
else:
    check(FAIL, "cpufreq interface not found")

devfreq = sorted(glob.glob("/sys/class/devfreq/*"))
if devfreq:
    for d in devfreq:
        cur, mx = read(f"{d}/cur_freq"), read(f"{d}/max_freq")
        if cur and mx:
            echo(f"       {os.path.basename(d):34s} cur {int(cur)/1e6:7.0f} MHz"
                 f"   max {int(mx)/1e6:7.0f} MHz")
    gpu_like = [d for d in devfreq if "gpu" in d.lower() or "gv" in d.lower()
                or "17000000" in d]
    check(OK if gpu_like else WARN,
          "GPU devfreq node " + ("found" if gpu_like else "not identified"),
          "" if gpu_like else "GPU freq will come from tegrastats instead")
else:
    check(WARN, "No devfreq nodes", "GPU/EMC freq will come from tegrastats")

# ---------------------------------------------------------------- 5. fan
section("5. FAN")
fans = []
for h in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
    name = read(f"{h}/name") or ""
    if "fan" in name.lower():
        pwm = read(f"{h}/pwm1")
        rpm = read(f"{h}/rpm") or read(f"{h}/fan1_input")
        fans.append((name, pwm, rpm))
        echo(f"       {name}: PWM={pwm or '?'} (0-255)  RPM={rpm or '?'}")
if fans:
    check(OK, "Fan interface readable")
else:
    check(WARN, "No fan hwmon found", "check nvfancontrol / cooling is present")
rc, out = run("cat /etc/nvfancontrol.conf 2>/dev/null | grep -m2 FAN_")
if out:
    echo("       nvfancontrol: " + " | ".join(out.splitlines()))

# ---------------------------------------------------------------- 6. tegrastats
section("6. TEGRASTATS SAMPLE (M1's parser is written against THIS)")
if shutil.which("tegrastats"):
    rc, out = run("timeout 6 tegrastats --interval 1000", timeout=9)
    lines = [l for l in out.splitlines() if l.strip()]
    if lines:
        tegrastats_sample = "\n".join(lines)
        check(OK, f"tegrastats captured ({len(lines)} samples)",
              "saved to tegrastats_sample.txt")
        echo("       first sample:")
        echo("       " + lines[0][:200])
    else:
        rc2, out2 = run("timeout 6 sudo -n tegrastats --interval 1000", timeout=9)
        lines2 = [l for l in out2.splitlines() if l.strip()]
        if lines2:
            tegrastats_sample = "\n".join(lines2)
            check(OK, f"tegrastats captured with sudo ({len(lines2)} samples)")
        else:
            check(FAIL, "tegrastats produced no output",
                  "try manually: tegrastats")
else:
    check(FAIL, "tegrastats not found", "core telemetry tool missing")

# ---------------------------------------------------------------- 7. tools
section("7. TOOLBOX FOR M1")
tools = [
    ("stress-ng", "CPU load generator — REQUIRED for M1",
     "sudo apt install stress-ng", True),
    ("python3", "test language — REQUIRED", "", True),
    ("git", "version control — REQUIRED", "sudo apt install git", True),
    ("jtop", "nice live monitor — optional",
     "sudo pip3 install jetson-stats && reboot", False),
    ("i2cdetect", "for the future ambient sensor — optional (M2)",
     "sudo apt install i2c-tools", False),
]
for name, why, fix, required in tools:
    if shutil.which(name):
        check(OK, f"{name} installed", why)
    else:
        check(FAIL if required else WARN, f"{name} MISSING", f"{why}. Fix: {fix}")

pyver = sys.version_info
check(OK if pyver >= (3, 8) else WARN, f"Python {platform.python_version()}")

cuda = read("/usr/local/cuda/version.json") or (
    run("nvcc --version")[1] if shutil.which("nvcc") else None)
check(OK if cuda else WARN, "CUDA " + ("detected" if cuda else "not detected"),
      "" if cuda else "not needed for M1 (CPU only); needed from M2")

# ---------------------------------------------------------------- 8. system
section("8. SYSTEM HYGIENE")
rc, out = run("df -h / | tail -1")
if out:
    parts = out.split()
    if len(parts) >= 5:
        used_pct = parts[4]
        check(OK if int(used_pct.rstrip("%")) < 85 else WARN,
              f"Disk usage {used_pct}", f"free: {parts[3]}")
rc, out = run("timedatectl show -p NTPSynchronized --value 2>/dev/null")
check(OK if out == "yes" else WARN,
      "Clock NTP-synchronised: " + (out or "unknown"),
      "" if out == "yes" else "timestamps in logs may drift")
rc, out = run("dmesg | tail -1 2>/dev/null")
check(OK if rc == 0 and out else WARN,
      "dmesg readable " + ("(throttle/OC events visible)" if rc == 0 and out
                           else "— needs sudo; fine, M1 will note it"))

# ---------------------------------------------------------------- verdict
section("FINAL CHECKLIST")
fails = [s for s in summary if s[0] == FAIL]
warns = [s for s in summary if s[0] == WARN]
for st, label in summary:
    if st != OK:
        echo(f"   {st} {label}")
if not fails and not warns:
    echo("   Everything green.")
echo()
if fails:
    echo(">>> NOT READY for M1 yet — fix the [FAIL] items above (install "
        "commands are listed next to each).")
elif warns:
    echo(">>> READY for M1 with notes — the [ !! ] items are worth a look "
        "but do not block the first script.")
else:
    echo(">>> READY FOR M1. Bench is fully green.")

# ---------------------------------------------------------------- write files
with open("bench_report.txt", "w") as f:
    f.write("\n".join(report_lines) + "\n")
if tegrastats_sample:
    with open("tegrastats_sample.txt", "w") as f:
        f.write(tegrastats_sample + "\n")
print()
print("Wrote: bench_report.txt" +
      (" + tegrastats_sample.txt" if tegrastats_sample else
       "  (no tegrastats sample — see section 6)"))
print("Send both files back to continue with M1.")
