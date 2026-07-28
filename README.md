# Jetson Orin Nano — Automated Stress Test

A health check for the compute board of our security robot.

## The idea

The robot's brain is an NVIDIA Jetson Orin Nano. If its cooling slowly gets
worse — a tired fan, dust in the heatsink — nobody notices until the robot
fails in the field. This project replaces guesswork with a repeatable test:

1. Load the board **step by step** (10 % → 25 % → 50 % → 75 % → 100 %).
2. At each step, wait for the temperature to settle, then **record** how hot
   the board gets and whether it keeps its full speed.
3. Stop immediately if anything crosses a safety line.
4. Let the board cool down and **measure how fast it recovers** — a slowing
   recovery is the earliest sign the cooling is wearing out.
5. Print a one-word verdict: **PASS**, **WARN** or **FAIL**, with graphs.

Run it on a schedule, keep the results, and compare week over week: the
board's health becomes a curve you can watch instead of a surprise.

## What is in this repo

| Folder | Content |
|---|---|
| `src/` | The test scripts (laptop version with a simulator, and the Jetson version) |
| `docs/` | How to use the test, the design decisions, and the workflow diagrams |
| `ops/` | Bench and SSH command references for running it on the real board |
| `runs/` | Where each test run writes its results (kept out of git) |
| `PROJECT_CONTEXT.md` | The full development context — read this to continue the work |

## Quick start

On a laptop (no hardware needed — built-in simulator):

```bash
python src/m1_stress_test.py --dry-run --ambient-c 24
```

On the Jetson (see `docs/USAGE.md` for the full guide):

```bash
sudo nvpmodel -q          # confirm the power mode
sudo jetson_clocks        # pin the clocks
python3 src/m1_stress_test_jetson.py --ambient-c 24.5 --humidity 60
```

Each run produces a report, raw CSV data and three graphs in `runs/`.
Exit code: 0 = PASS, 1 = WARN, 2 = FAIL.

## Project status

| Stage | What it adds | State |
|---|---|---|
| M1 | The measuring core: staged CPU test, safety stops, verdict, graphs | ✅ Done, validated on hardware |
| M2 | Test the GPU and memory too; automatic environment sensor; auto clock handling | 🔨 In progress |
| M3 | Calibration: learn what "normal" looks like, judge statistically | Planned |
| M4 | Full automation on a schedule, with alerts | Planned |
| M5 | Long-term health trends | Planned |

The history of every change pushed here is in [`CHANGELOG.md`](CHANGELOG.md).
