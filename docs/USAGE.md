# M1 — Measurement Core: Usage

One script, `m1_stress_test.py`, no pip dependencies required
(matplotlib optional — used only for the two graphs).

## Two profiles

- **`--profile fast` (default, ~10–12 min real):** 5 levels (10/25/50/75/100 %),
  ascending ramp with **no cooldowns between levels** (steady state is a
  physics equilibrium — path-independent), statistics from **3 measurement
  windows on each plateau**, and **one final decay** at the end that fits the
  cooling time constant τ and returns the board to rest. For every scheduled
  run.
- **`--profile deep` (~1.5–2.5 h real):** the full protocol — 10 levels,
  3 independent restart trials, full cooldown after every trial with a τ fit
  each time. For the M3 calibration campaign and an occasional weekly deep
  check. Fast catches problems daily; deep keeps the reference honest.

All safety gates (95 °C instant stop, 90 °C sustained, throttle, cooldown
timeout) are identical and always active in both profiles.

## Today, on your laptop (robot occupied)

Full flow in simulator mode — synthetic but realistic thermal physics:

```bash
python3 m1_stress_test.py --dry-run --quick          # full 10..100% ramp, fast timings
python3 m1_stress_test.py --dry-run                  # realistic timings
```

Demonstrate the safety logic on purpose (great for the supervisor demo):

```bash
python3 m1_stress_test.py --dry-run --quick --sim-throttle   # clock-dip -> FAIL (throttle)
python3 m1_stress_test.py --dry-run --quick --sim-hot        # overheat -> 95 °C instant stop
python3 m1_stress_test.py --dry-run --quick --sim-warn       # unknown device -> WARN verdict
```

## On the Jetson (after M0 gives the green bench)

```bash
sudo apt install stress-ng python3-matplotlib   # if M0 checker flagged them

# short shakedown first (one level, one trial):
python3 m1_stress_test.py --ambient-c 24.5 --levels 10 --trials 1

# then the real thing (~35-60 min):
python3 m1_stress_test.py --ambient-c 24.5 --humidity 60
```

`--ambient-c` is the room thermometer reading — required for real runs
(the ΔT logic depends on it; the I2C sensor automates this in M2).

## What every run produces

`runs/run_YYYYMMDD_HHMMSS/` containing:

- `report.txt` — verdict PASS / FAIL (+ failing level and cause), metadata,
  per-level table (mean ± σ, hottest zone, min clock, margin to 90 °C)
- `samples.csv` — every second of the run: all zones, clocks, phase
- `levels.csv` — the per-level summary (this is future calibration data)
- `temp_vs_load.png`, `freq_vs_load.png` — the two functions f() and g()
- `metadata.json` — config, power/fan mode, and the trip points **read from
  the device**

Exit code: 0 = PASS, 1 = WARN, 2 = FAIL (usable in shell scripts later).

## Severity model (what aborts vs what continues)

- **Abort (FAIL):** any zone >= 95 °C (instant) or >= 90 °C sustained; the
  kernel actually capping frequency (passive cooling device active, or the
  frequency ceiling dropping below its start-of-test value); a sustained
  clock dip below the pinned max; cooldown timeout.
- **Warn + continue (WARN verdict):** over-current log events without any
  clock consequence; unknown cooling-device types activating.
- **Normal + logged as data:** the FAN. Fan spin-up is the first line of
  defense working, not throttling — its state and RPM are recorded per level
  and plotted in the third graph, fan_vs_load.png (speed vs load with the
  fan-mode zones shaded), because rising fan effort for the same load over
  weeks is an early cooling-degradation signal.

## Safety, in one paragraph

The load runs in its own process group and is killed on *every* exit path —
normal end, failure, Ctrl-C, crash of the sampling loop. Any zone at 95 °C
stops the test instantly; 90 °C sustained fails the level; a sustained clock
below 98 % of the pinned maximum is a throttle failure; cooldown back to
idle+2 °C must complete within 5 minutes. Per the roadmap, M1 has no
independent watchdog yet — the operator supervises every run (that is you,
sitting next to the board).

## What comes back to the project

Bring back (or commit) the whole `runs/` directory from the first real
sessions plus M0's two report files. The `levels.csv` rows are the seeds of
M3's golden fingerprint, and the metadata confirms the parser assumptions —
that closes the loop we opened by building M1 before M0.
