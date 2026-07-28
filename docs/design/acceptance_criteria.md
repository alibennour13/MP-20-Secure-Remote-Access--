# Cahier de Référence — Acceptance Criteria for the Automated Stress Test
**Target:** NVIDIA Jetson Orin Nano Developer Kit (8 GB module)
**Purpose:** Defines, with sources, what "normal" is for this board, and the exact rules that decide PASS / WARN / FAIL for every metric, every stress level, and every ambient condition.
**Companion documents:** `stress_test_decisions.md` (strategy), `master_flow.mmd` / `stress_block.mmd` (workflow charts).

---

## 1. Researched hardware facts (with sources)

### 1.1 Thermal limits — the fixed lines (NVIDIA official)

| Line | Value | Meaning | Source |
|---|---|---|---|
| Qualified operating range (Tj) | **−25 °C to 90 °C** | The module's datasheet operating envelope. Staying below 90 °C is operating as designed. | Orin Nano Series Datasheet DS-11105 |
| NVIDIA design target | **≤ 95 °C** | NVIDIA's own thermal-design examples target T.SoC = 95 °C, keeping 4 °C headroom for sensor inaccuracy and workload-induced Tj fluctuation. | TDG-11127 §3 (design examples) |
| Max operating temperature | **99 °C** | Below this, the SoC runs at specified clock speeds. Above it, temporary clock reductions occur (software thermal management). | TDG-11127 Table 2-1 |
| Hardware throttling | between 99 °C and 105 °C | Last-resort hardware clock throttling to avoid shutdown; settings cannot be altered. | TDG-11127 §5.4 |
| Shutdown | **105 °C** | Hardware halt. Reaching it means a major cooling fault. | TDG-11127 Table 2-1, §5.5 |

Interpretation for QA (three-line structure used throughout this document):
- **90 °C = QA ceiling.** Any zone at/above 90 °C during our test → the level FAILS (we left the qualified envelope).
- **95 °C = critical abort.** Immediate safe-stop of the run (we consumed NVIDIA's own design headroom).
- **99 / 105 °C = the chip's own defenses.** Our test must be designed so these are never reached; seeing them means the test's abort logic itself failed.

The LPDDR5 memory chips are separate packages on the module with their own, lower, maximum temperatures (TDG-11127 Table 3-1, component de-rated limits). They do not expose a dedicated user-visible thermal zone; their thermal stress is observed indirectly through the soc zones and EMC activity, and the module-level limits above already account for them.

### 1.2 Thermal sensors available to the test

Six on-die zones reported by `tegrastats` / sysfs (`/sys/class/thermal/thermal_zone*/`):
`cpu`, `gpu`, `soc0`, `soc1`, `soc2`, `tj` — where `tj` is the junction (hottest) figure that drives the fan controller (`nvfancontrol`). Real capture on a dev kit (Super mode, idle, indoor ambient):
`cpu@51.5 soc2@50.5 soc0@50.8 gpu@50.7 tj@51.5 soc1@51.5` (°C).

Fan: step-based speed control with hysteresis, two modes — **Quiet (default)** and **Cool** — PWM on a 0–255 scale. TMARGIN (used by fan logic) = 105 °C − average(CPU, GPU, SoC zones).

**Rule: the test reads the actual trip-point temperatures from the device at startup** (`/sys/class/thermal/thermal_zone*/trip_point_*_temp`) and logs them, instead of hardcoding values. Firmware updates can move trip points; the log must show what the board actually enforced that day.

### 1.3 Expected clocks per power mode (the "speed" reference)

Measured on the dev kit (tegrastats), matching NVIDIA's published Super-mode figures:

| Mode | CPU (6 cores) | GPU | EMC (memory) | Peak mem bandwidth |
|---|---|---|---|---|
| 15 W (legacy default) | 1497 MHz | 611–625 MHz | 2133 MHz | 68 GB/s |
| 25 W (Super) / MAXN SUPER | ~1728 MHz | 1007–1020 MHz | 3199 MHz | 102 GB/s |
| 7 W | lower caps (per nvpmodel table) | — | — | — |

With `jetson_clocks` engaged, clocks are pinned at the mode maximum. Therefore the **expected speed at every stress level is a constant: the mode's pinned max.** Speed is not supposed to rise with load; it is supposed to *not fall*. Any sustained dip below the pinned frequency is a throttle event — which is a result, not noise.

### 1.4 Two distinct throttle causes (both must be logged)

1. **Thermal throttling** — DVFS reduces clocks when a zone crosses its trip point. Fan ramps first ("first line of defense"), throttling second.
2. **Over-current (power) throttling** — "System throttled due to over-current": module power exceeded the budget. Common on MAXN SUPER even with light loads; appears in `dmesg` and desktop notifications, independent of temperature.

Consequence: the block chart's "Chip stayed at full speed?" gate carries **two flags** — `throttle_thermal` and `throttle_power` — read from dmesg/sysfs, because the diagnosis differs completely (cooling problem vs. power-budget/supply problem).

**Mode policy:** the scheduled QA test runs in a **fixed named mode (15 W or 25 W)** matching the robot's deployment mode. MAXN SUPER is excluded from scheduled testing: NVIDIA labels it experimental, advises against prolonged heavy workloads in it, and it is prone to over-current throttling that would contaminate results.

---

## 2. Ambient physics — how room conditions enter the model

### 2.1 Temperature: the linear ΔT model

Steady-state chip temperature obeys the thermal-resistance relation NVIDIA itself designs with:

> **T_zone(steady) = T_ambient + θ × P(load)**

where θ (°C/W) is the junction-to-ambient thermal resistance of the whole cooling chain (die → heatsink → fan → air) and P is dissipated power. NVIDIA's worked example: T.amb = 55 °C, target T.SoC = 95 °C, requiring a ~1.60 °C/W solution.

Consequence — the single most important rule in this document:

> **All calibrated limits are defined on ΔT = T_zone − T_ambient, never on absolute temperature.**
> ΔT at a given stress level, power mode, and fan mode is a property of the *board's health*, independent of the room. Absolute caps (90/95 °C) sit on top as fixed lines.

ΔT(s) as a function of stress level s is approximately affine (power scales roughly linearly with utilization at pinned clocks), but the test does not assume linearity — it fits the observed curve during calibration (§4) and uses the fitted band.

### 2.2 Cooling: the exponential recovery model

After load is removed, temperature decays toward baseline per Newton's law of cooling:

> **T(t) = T_amb + ΔT_peak · e^(−t/τ)**

τ (the time constant, in seconds) is set by the heatsink's thermal mass and the fan's airflow — **it is a property of the cooling hardware and is nearly independent of ambient temperature**, which makes it the ideal cooling-health metric:

- Measured each cooldown by a log-linear fit of (T − T_amb) vs. time.
- "Cooled down" is defined as ΔT ≤ ΔT_idle + ε (ε = 2 °C margin), never as "equals baseline" — recovery is asymptotic and never exactly arrives.
- Cooldown timeout (the hard gate) = t_expect × 1.5, where t_expect = τ_golden · ln(ΔT_peak / ε), computed per level from the calibrated τ.
- A **rising τ across scheduled runs is the earliest fan/heatsink degradation signal** — it moves before any peak temperature does.

### 2.3 Humidity: gate and annotation, not a correction

Within normal indoor ranges, humidity changes air's cooling capacity by only ~1–2 % — far below run-to-run noise — so **no humidity correction is applied to temperatures.** Humidity matters for two real risks:

1. **Condensation.** Compute dew point from (T_amb, RH) with the Magnus approximation:
   γ = ln(RH/100) + 17.62·T/(243.12+T); T_dew = 243.12·γ/(17.62−γ).
   **Gate:** the test only starts if T_board(idle) > T_dew + 2 °C. A board colder than the dew point risks condensation → run refused, environment fault (not a board fault).
2. **Long-term corrosion.** Sustained RH > 85 % is annotated as an environment WARN in the trend history. RH is logged with every run regardless.

### 2.4 Ambient validity window for comparability

Calibration (§4) is performed within a declared ambient window — recommended **T_amb ∈ [15, 35] °C** for an indoor lab in Tunisia (covers seasonal swing). Runs inside the window are compared to the fingerprint normally. Runs outside it still execute with all absolute caps active, but their results are **flagged "out of calibration envelope"** and excluded from fingerprint drift verdicts (they still append to the trend history, tagged).

---

## 3. The acceptance framework — Layer 0 and Layer 1

Two independent layers; a run must satisfy both.

### Layer 0 — absolute, fixed, from NVIDIA (never recalibrated)

| # | Condition (any zone, any trial) | Verdict |
|---|---|---|
| A0-1 | T_zone ≥ 95 °C | **FAIL + immediate safe-stop of the whole run** |
| A0-2 | T_zone ≥ 90 °C sustained (> 5 s) | **FAIL** the level; abort per flow |
| A0-3 | Thermal-throttle event (trip crossed / clock dip with high temp) | **FAIL**, cause = cooling |
| A0-4 | Over-current-throttle event (dmesg OC message / clock dip with normal temp) | **FAIL**, cause = power |
| A0-5 | Cooldown timeout exceeded (§2.2) | **FAIL**, cause = cooling |
| A0-6 | Idle gate: ΔT_idle outside calibrated band before stressing | **FAIL**, cause = cooling (pre-test) |
| A0-7 | T_board ≤ T_dew + 2 °C | **Run refused**, cause = environment (not a board FAIL) |

### Layer 1 — calibrated statistical bands (from golden runs, §4)

For each (power mode, fan mode, target, stress level s), calibration produces mean and standard deviation of:
ΔT_steady(s) per zone, sustained clock f(s) per domain, throttle margin m(s) = 90 − T_hottest(s), memory bandwidth B(s) (memory targets only), cooldown constant τ, and idle offset ΔT_idle.

Decision rule per metric, per level (applied to the **mean of the 3 trials**; any *single* trial breaching Layer 0 fails regardless):

| Zone of the measurement | Verdict |
|---|---|
| within μ ± 2σ | **PASS** |
| between 2σ and 3σ from μ | **WARN** ("in between") |
| beyond 3σ from μ | **FAIL** (deviation from known-good) |

Clock-specific floor: sustained f(s) must additionally be ≥ 98 % of the mode's pinned maximum (allows governor jitter, catches soft degradation even inside σ bands).

Trend rules (evaluated on the history log, catches slow drift that never breaches 3σ in one run):
- **7 consecutive runs on the same side of μ** for any metric → WARN (Western-Electric-style run rule).
- **τ increasing monotonically over 5 consecutive runs** → WARN, cause = cooling degradation.
- **Throttle margin m(s) decreasing monotonically over 5 runs** → WARN, cause = approaching thermal limit.

### Verdict synthesis (three states)

- **FAIL** — any Layer 0 breach, any metric beyond 3σ, any throttle event, cooldown timeout, or fingerprint drift (below). Report localises the cause (which target, which level, which flag) and raises the alert.
- **WARN** — no FAIL, but ≥ 1 metric in the 2σ–3σ band, a trend rule fired, or the run executed outside the ambient calibration envelope. Logged prominently, no alert storm; two consecutive WARNs on the same metric escalate to an alert.
- **PASS** — everything within 2σ, no events, cooldown on time, environment valid.

The "in between" state the strategy called for is the WARN band: it exists precisely so that a board drifting toward failure is caught and investigated *before* it fails, without crying wolf on ordinary noise.

---

## 4. Calibration protocol — how the numbers are actually obtained

The reference values are **not taken from the internet**; published temperatures vary with fan mode, enclosure, airflow and ambient, so they cannot define this bench's normal. They are measured on this board, on this bench, in this enclosure:

1. Fix configuration: power mode (15 W or 25 W), fan mode (Quiet or Cool), `jetson_clocks` on. Log firmware/JetPack version, board serial.
2. Confirm board health by inspection (fan spins, heatsink seated, no dust) — golden runs on a sick board poison everything.
3. Run the complete flow (combined + full sweep) **N = 5 times minimum**, spread across different days/times inside the ambient window, recording every metric in §3-Layer-1.
4. Compute per-(target, level, zone) μ and σ. Where σ is implausibly small (< 0.5 °C), floor it at 0.5 °C so the 3σ band is never narrower than sensor noise.
5. Freeze the result as the **golden fingerprint** (versioned file, committed to the repo). Fingerprint comparisons and Layer-1 verdicts activate only after this point; earlier runs report Layer-0 only, tagged "calibration".
6. Recalibrate (new fingerprint version) after any of: JetPack/firmware update, power- or fan-mode change, thermal-paste/heatsink/fan intervention, enclosure change, or relocation of the bench.

Sanity anchor from published data (not a limit, only a plausibility check): a healthy dev kit at indoor ambient idles in the high-40s/low-50s °C on the internal zones — i.e., an idle ΔT of roughly 25–30 °C over the room with the default Quiet fan. If calibration produces an idle ΔT wildly outside that neighbourhood, suspect the setup before trusting the fingerprint.

---

## 5. Per-target specifics

| Target | Load generator | Primary zones | "Speed" metric | Notes |
|---|---|---|---|---|
| CPU | stress-ng, load fraction = s | cpu, tj | per-core MHz vs pinned max | per-core spread > 10 °C between hottest/coolest core pattern → annotate |
| GPU | gpu_burn / CUDA kernel, duty-cycled to s | gpu, tj | GR3D MHz vs pinned max | GPU throttles first on many workloads; watch margin m(s) |
| Memory (CPU-driven) | STREAM-style, throttled to s | soc0-2, cpu | achieved GB/s vs mode ceiling (68 / 102) | bandwidth is the speed metric here, not MHz |
| Memory (GPU-driven) | CUDA bandwidthTest loop | soc0-2, gpu | achieved GB/s | reported separately from CPU-driven, per decision |
| Combined | all of the above simultaneously | all six | all domains | expects *lower* per-domain ΔT ceilings than solo targets (shared power budget) — combined gets its own calibrated bands, never reuses solo bands |

The last cell is essential: because the power budget is shared, combined-load clocks and temperatures are *legitimately different* from solo runs. Each of the five targets owns its own fingerprint section.

---

## 6. Changes applied to the previous design (review outcome)

1. **Over-current throttling added** as a second, distinct throttle flag (`throttle_power`) alongside thermal — discovered during research; it is a documented, common event on this board and has a completely different diagnosis. The block chart's throttle gate now reads both dmesg OC events and thermal trips.
2. **MAXN SUPER excluded** from scheduled testing; QA runs in the robot's fixed named mode. (NVIDIA: experimental, not for prolonged heavy loads, OC-prone.)
3. **Fan mode (Quiet/Cool) added to fixed configuration** — it changes the thermal resistance θ and therefore every band; it is now logged and frozen exactly like the power mode.
4. **Trip points read from the device at startup** rather than hardcoded, and logged per run.
5. **"Derive safe ranges" made concrete:** all calibrated limits are ΔT-relative (chip − room); the absolute lines 90 °C (FAIL) and 95 °C (critical abort) are fixed and researched, not guessed.
6. **Cooldown metric upgraded** from a raw timeout to the fitted time constant τ, with the timeout derived from τ and ΔT_peak — more robust, ambient-independent, and the earliest fan-degradation indicator.
7. **Verdict expanded from PASS/FAIL to PASS/WARN/FAIL** — the 2σ–3σ "in between" band plus trend rules (7-run sidedness, 5-run monotonic drift) so degradation is flagged before it becomes failure.
8. **Fingerprint upgraded from "first run" to a proper calibration protocol** — N ≥ 5 golden runs, per-level μ/σ, σ floored at sensor noise, versioned and recalibrated on any hardware/firmware/config change.
9. **Humidity given its correct role:** dew-point gate (run refused if condensation risk) and high-RH annotation — no pseudo-scientific temperature "correction".
10. **Ambient validity window defined** ([15, 35] °C recommended): runs outside it execute with absolute caps but are excluded from fingerprint verdicts and tagged in the trend history.
11. **Memory targets get bandwidth (GB/s) as their speed metric** instead of MHz, against the mode ceiling (68 or 102 GB/s), reported separately for CPU-driven and GPU-driven as decided.
12. **Combined target owns separate calibrated bands** — solo-run bands must never be applied to combined runs (shared power budget makes them incomparable).
13. **Environment faults separated from board faults** in reporting (dew-point refusal and out-of-envelope ambient are not board FAILs).

Flow-chart impact: the structure of both charts stands. Three boxes gain richer meaning rather than new shapes — "Load settings" now includes fan mode + trip-point read-out; "Set safe limits for this room temp" is the ΔT band computation of §3; "Chip stayed at full speed?" carries the two throttle flags; and the final verdict is three-state. If you want, I can re-issue the .mmd files with these labels updated.

---

## 7. Sources

- NVIDIA Jetson Orin NX Series and Orin Nano Series Thermal Design Guide, TDG-11127-001 (v1.1 Jan 2023 / v1.5 May 2025) — Tables 2-1, 3-1, §3 design examples, §5.3–5.5, fan tables 5-1/5-2.
- NVIDIA Jetson Orin Nano Series Data Sheet, DS-11105-001 v1.1 — Tj operating range −25…90 °C; LPDDR5 68 GB/s.
- NVIDIA Jetson Linux Developer Guide (r36.x) — thermal zones, trip-point classes, nvfancontrol, PID throttling governor, MAXN guidance, nvpmodel/jetson_clocks.
- NVIDIA Technical Blog: "JetPack 6.2 Brings Super Mode…" — 25 W / MAXN SUPER modes, clock increases, TDP throttling behaviour.
- RidgeRun wiki: Super-mode exploration — real tegrastats captures (clocks and zone temperatures, both modes).
- NVIDIA Developer Forums — over-current throttling reports on Orin Nano (MAXN SUPER); Orin NX/Nano thermal threads.
- Standard heat-transfer theory: thermal-resistance steady-state model; Newton's law of cooling; Magnus dew-point approximation.
