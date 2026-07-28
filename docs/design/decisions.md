# Automated Stress Test — Design Decisions & Strategy

**Target hardware:** NVIDIA Jetson Orin Nano Developer Kit
**Purpose:** Scheduled, automated QA stress test of the compute board used in the security-robot project
**Status:** Design agreed; thresholds to be finalised from baseline runs

---

## 1. Platform and why it shapes everything

The Orin Nano dev kit is a single Tegra system-on-chip: a 6-core Arm Cortex-A78AE CPU, a 1024-core Ampere GPU, and 8 GB of LPDDR5 memory on a 128-bit bus. The CPU, GPU, and memory are all on one die, the memory is a **unified pool shared** between CPU and GPU, and they share **one thermal solution** and **one power budget**.

This single fact drives the whole strategy. The three subsystems cannot be thermally or electrically isolated — heat from the GPU raises the whole die, and all three compete for the same wattage ceiling. So "test each part separately" is never true isolation; it is a way to push each part *hardest in turn* for fault attribution, while the combined test remains the only realistic worst case.

**Decision:** Fix and log the SoC power mode for every run. The board supports 7 W / 15 W / 25 W-class modes, and the "Super" firmware update raises all clocks at once (memory bandwidth rises from 68 GB/s to 102 GB/s). Results are only comparable across runs if the power mode is held constant, so it is treated as fixed configuration, recorded in every report.

---

## 2. Test type and tooling

**Decision:** An automated, scheduled stress test using a staged load ramp — start at 10 %, increase in 10 % steps — rather than a single all-out load. The gradual ramp lets the test stop at the first sign of trouble and report *at which level* the problem appeared.

**Decision:** Reuse proven tools rather than build load generators from scratch:
- Telemetry: `tegrastats` / `jtop` (clocks, per-zone temperatures, power, memory).
- CPU load: `stress-ng`.
- GPU load: `gpu_burn` or a CUDA compute kernel.
- Memory load: a STREAM-style CPU-driven bandwidth test **and** a CUDA GPU-driven bandwidth test.

**Decision:** At each stress level, hold the load until temperature reaches steady state before recording, rather than taking an instantaneous reading — temperature lags load, so a snapshot measures ramp-up, not real behaviour.

**Decision:** Run each level **three times** and report mean and standard deviation. Thermal results vary enough (airflow, prior heat soak) that a single reading per level is a weak sample.

---

## 3. Safety measures

**Decision — independent watchdog:** An auto-shutoff (hardware watchdog) is armed *before* any load touches the board and disarmed on both a clean pass and a graceful, detected abort. It exists as a failsafe independent of the test script, so that if the script itself crashes or hangs mid-load, the board is still protected. This is the one protection the flowchart cannot represent, because it fires precisely when the flow stops responding.

**Decision — rely on the SoC's own protection for damage safety:** The chip's automatic frequency scaling and thermal throttling downclock it as it nears its thermal limit, and it hardware-shuts-down before any destructive temperature. Software cannot push it past that ceiling. This is why a full-load stress test carries effectively zero *damage* risk (see §8).

**Decision — quantified pass/fail, not judgement:** Every abort condition is a defined number set before the run, not "looks off". The two independent failure signals are: (a) a **threshold breach** (temperature or clock outside the calibrated safe range) and (b) a **throttle event** (the chip downclocking under sustained load). A throttle is a failure even if absolute temperature is still under the ceiling, so the two are logged as separate flags.

---

## 4. Environment and calibration

**Decision — local sensor, not a weather API:** Ambient temperature and humidity come from a local I2C sensor at the test bench, not an online weather service, because what matters is the actual air around the board, not outdoor conditions. The sensor is sanity-checked once against a reference thermometer, and its accuracy is noted in the report.

**Decision — safe ranges are relative to ambient, never hardcoded:** The board's expected temperatures depend on room conditions, so the safe limits for a run are computed from that run's ambient reading.

**Decision — cooling validation (Basic level):** Two concrete cooling gates, both judged against the live ambient reading:
1. **Idle-vs-ambient check**, run *before* stressing. If the board sits too hot relative to the room at rest, cooling is already failing and the run stops before wasting a full ramp.
2. **Cooldown timeout**, run *after* each level. If the board cannot return toward baseline within a time limit, that is a cooling failure. "Returned to baseline" is defined as *within a small margin* of baseline, because thermal recovery is asymptotic and never exactly reaches it.

Cooldown *time* is still logged every run to feed trend tracking (see §5) — a slowly-dying fan shows up here first — but it is not itself a hard per-level gate at the Basic level.

---

## 5. Advanced measurement ideas (all four adopted)

**Trend tracking across runs.** Because the test runs on a schedule, every run appends its key metrics to a history log, giving a health-over-time picture. Slow degradation (rising temperatures, lengthening cooldowns, shrinking throttle margin) appears as drift over days or weeks — the single most valuable output of running this repeatedly.

**Known-good fingerprint.** The first fully healthy run is saved as a reference "golden sample" of the temperature and clock curves. Later runs are compared against it, and deviation beyond tolerance is treated as a **failure** (silent drift should not pass a QA test). The tolerance is a tunable number.

**Throttle-margin logging.** Instead of only recording whether the chip throttled, the test records *how many degrees of headroom* remained before the throttle point. Shrinking margin over weeks predicts a future failure before it actually throttles.

**Separate CPU / GPU / memory checks.** Each subsystem is stressed on its own as well as together, so a localised problem surfaces and can be attributed to a specific part.

---

## 6. Test structure

**Decision — one master flow, one reusable stress block.** The master flow (scheduler, safety, calibration, reporting) calls a single reusable stress-block routine with a *target* parameter: `combined`, `cpu`, `gpu`, `mem-cpu-driven`, or `mem-gpu-driven`. The ramp logic, safety gates, and cooldown check are identical each time; only the load generator changes. This keeps the design maintainable and makes per-subsystem trend and fingerprint data automatic. It also mirrors how the code is actually written — one function, called five times.

**Decision — the memory test runs both drivers, reported separately.** Memory can only be reached *through* the CPU or the GPU, so a CPU-driven (STREAM-style) and a GPU-driven (CUDA) bandwidth test are both run and reported as distinct results.

---

## 7. Ordering: combined-first

**Decision — run the combined test first every cycle.** The combined load is both the harshest case and the robot's real operating condition (perception on the GPU, control on the CPU, sensor data through memory, all at once). Testing what actually matters first means that on a healthy board the combined test passes and the three separate runs can be skipped, cutting most of the test time out of every healthy cycle. Isolation is only paid for when there is a real fault to diagnose.

**Decision — on combined failure, run the full diagnostic sweep with "log and continue".** When combined fails, the test drops into a sweep of all separate blocks and logs *every* result rather than stopping at the first, because the **pattern of failures is the diagnosis**. CPU-only fails but GPU-only passes points to a CPU-side issue; CPU-only and both memory tests failing points to a shared memory-controller or board-level thermal problem.

**Known blind spot (accepted, with mitigation).** Combined load is *not* a strict superset of the separate tests. Because the three share the power budget, the chip downclocks under combined load, so no single subsystem ever reaches its individual peak clock during a combined run. A defect that only appears at a subsystem's *maximum* clock could therefore pass combined. Conversely, memory contention is *worse* under combined load, since CPU and GPU hammer the shared controller together. The two orderings stress genuinely different failure modes.

**Decision — periodic full sweep to cover the blind spot.** Combined runs every cycle; additionally, a full separate sweep runs on a slower cadence (e.g. daily or weekly) *regardless of pass/fail*. Combined catches everyday operating-condition failures fast; the periodic sweep catches peak-per-unit faults that combined structurally cannot, and enriches the per-subsystem trend data.

---

## 8. Lifespan and wear

Damage risk is effectively zero: the SoC's own throttling and hardware shutdown make it physically impossible to cook the board in software. Wear is a real but small cost, from two mechanisms:

- **Silicon aging (electromigration):** a function of *time spent hot*. The test spends minutes hot per cycle, not hours, so the effect is negligible against the board's rated life.
- **Thermal cycling:** repeated heat-up/cool-down fatigues solder joints and the die-to-heatsink interface. This — not peak temperature — is the wear vector that matters, and a scheduled repeating stress test is effectively a thermal-cycling machine, so it is respected directly.

**Decisions to limit wear:**
- **Minimum-interval guard** in the scheduler: the test refuses to run if the board was stressed too recently, so wear protection is built into the flow rather than left to configuration.
- **Test frequency** is the biggest lever — a few times a day is trivially safe; running back-to-back every few minutes is not. Combined-first already minimises hot-time.
- **Cooldown depth** is a tunable trade-off: cool enough for clean data, but not necessarily all the way to cold-idle every cycle, since deeper cycles fatigue solder more.
- The **fan** is the part that genuinely wears out; cooldown-time tracking detects its decline early as a useful side effect.

---

## 9. Reporting and traceability

**Decision — standardised, auditable report per run**, containing: metadata (board serial/revision, firmware version, fixed power mode, ambient conditions, timestamp); the pass/fail verdict with fault localisation; the two graphs — temperature vs stress % and clock (GHz) vs stress %; the statistical summary (mean and standard deviation per level); and a raw-data appendix. A failure additionally raises an alert.

**Decision — version control.** The test script, its configuration, and results are committed to git with a README and dependency list, so runs are reproducible and reviewable. Every run — pass or fail — commits its data and appends to the health-trend history.

---

## Decisions at a glance

| Area | Decision |
|---|---|
| Platform | Orin Nano dev kit; fixed & logged power mode |
| Ramp | 10 % start, +10 % steps, steady-state hold, 3× per level |
| Safety | Independent watchdog + SoC self-protection; threshold **and** throttle as separate flags |
| Ambient | Local I2C sensor, calibrated; safe ranges relative to ambient |
| Cooling | Basic: idle-vs-ambient pre-check + cooldown timeout |
| Advanced | Trend tracking + fingerprint + throttle margin + separate subsystem tests (all) |
| Structure | One master flow, one reusable stress block (target parameter) |
| Memory test | Both CPU-driven and GPU-driven, reported separately |
| Ordering | Combined-first; sweep on failure (log-and-continue) + periodic full sweep |
| Wear | Minimum-interval guard; frequency and cooldown depth as levers |
| Reporting | Standardised report, graphs, git version control, trend history |
