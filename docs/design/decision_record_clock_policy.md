# Decision Record — Clock Policy & Throttle Detection
**Addendum to:** `stress_test_decisions.md` / Design Dossier
**Status:** Decided — pinned clocks, four-signal throttle detection
**Date:** July 2026

## The observation
During M1 shakedown preparation, CPU clock speed was observed to be variable,
not constant. This contradicted the test's assumption that any clock drop
indicates throttling.

## The investigation (sources in dossier bibliography)
1. **The variability is factory behaviour, not a fault.** NVIDIA's Jetson
   Linux Developer Guide: the default CPU frequency governor is *schedutil*,
   "primarily aimed at power saving" — it scales frequency **with** load by
   design. At low load the chip deliberately runs slow.
2. **An expected-frequency law exists.** Kernel documentation gives
   schedutil's selection formula: f = min(f_max, 1.25 × load × f_max),
   saturating at f_max from ~80 % load. A governor-mode test comparing the
   observed curve against this law (with tolerance for scheduler-average lag,
   frequency-step quantisation, and I/O boost) is feasible.
3. **Throttling is a separate, directly observable mechanism.** NVIDIA:
   "CPU thermal management can override the target frequency of cpufreq."
   The kernel exposes it: cooling devices (`cur_state` > 0 = actively
   throttling; state 0 = max frequency), lowered frequency ceilings
   (`scaling_max_freq` below its start-of-test value), and over-current
   events in the kernel log. Throttle detection therefore never needs to be
   *inferred* from the raw clock.

## Alternatives considered
- **A — Pinned mode** (`jetson_clocks`, min = max on every core): clocks flat
  at the mode maximum; g(load) is a horizontal reference line; one fingerprint
  per power mode; NVIDIA-endorsed configuration for deterministic
  benchmarking.
- **B — Governor mode**: schedutil left in charge; observed f(load) judged
  against the kernel-law band; throttling by kernel signals only. More
  deployment-realistic; adds curve tolerance-tuning, doubles the M3
  calibration campaign if fingerprinted, weakens run-to-run comparability.
- **C — Both modes**: maximum coverage; per-run duration identical, but
  routine use and calibration effort roughly double.

## Decision
**Pinned mode only (A).** Rationale: comparability is the core asset of a
scheduled QA test — the golden fingerprint, trend rules, and week-over-week
drift detection all assume a fixed configuration. One mode = one calibration
campaign in M3. The realism argument for B is outweighed because the
quantity QA protects (the thermal envelope and the chip's protective
behaviour) is fully observable under pinned clocks via the kernel signals.
Governor mode and the throughput witness (work-delivered-per-second decline,
as measured by phone throttling benchmarks) are **shelved, documented, and
re-openable** in a later milestone if deployment-behaviour testing is wanted.

## Implementation state
Already implemented — no code change required by this decision:
- Startup gate: the test refuses to run unless min = max on every core, and
  prints the fix (`sudo nvpmodel` then `sudo jetson_clocks`).
- Throttle detection, four signals: (1) kernel cooling-device state,
  (2) frequency-ceiling drop, (3) over-current events in the kernel log
  (power throttling, reported as a distinct cause), (4) sustained dip below
  the pinned maximum as a cross-check.

## Operational consequences
1. Order matters at the bench: `sudo nvpmodel -m <N>` **then**
   `sudo jetson_clocks` — changing the power mode resets the pinning.
2. `jetson_clocks` does **not persist across reboots**: re-run it after every
   boot of the Jetson before testing. M4 (automation) will make this part of
   the scheduled run's pre-flight.
3. Every report records the governor found and the pinned state, so any run
   executed in the wrong configuration is self-documenting.
