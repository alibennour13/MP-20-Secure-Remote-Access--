# Changelog / Development log

One entry per push. Newest first. Each entry says what changed, why, and
what state the project is in afterwards.

---

## 2026-07-28 — Initial import (M0–M1)

**What was pushed**

The project as it stands after milestone M1, reorganized for this repo:

- `src/m1_stress_test.py` — the master test script (laptop build with a
  built-in physics simulator for development without hardware).
- `src/m1_stress_test_jetson.py` — the deployment build for the board,
  derived from the master (never edited by hand).
- `src/m0_bench_check.py` — read-only bench readiness checker (M0).
- `docs/` — usage guide, acceptance criteria with NVIDIA sources, design
  decision records, workflow diagrams (PNG + editable Mermaid sources).
- `ops/` — bench and SSH command references.
- `PROJECT_CONTEXT.md` — the complete handoff context (decisions, hardware
  facts, bugs found, measured data, open questions).

**State of the work at this point**

- M1 ran on the real board on 2026-07-15. The board itself looked healthy
  (idle 28 °C over room, clocks perfectly flat, ~35 °C of margin at half
  load), but the run ended with a false FAIL: the detector counted the
  **fan turning on** as thermal throttling. The severity model was revised
  (fan = normal behaviour, only real frequency capping = FAIL) and the code
  updated; a clean re-run on the board is still pending.
- M0 bench-check reports were skipped by decision; the checker script is
  kept in `src/`.

**Known open questions**

1. The board reports a pinned CPU clock of **1344 MHz** in 25 W mode, while
   published figures suggest ~1728 MHz. Must be resolved before calibration.
2. The cooling-device keyword classification has not yet been validated
   against the board's real 13-device inventory.

**Next planned pushes**

1. Decision record resolving the 1344 MHz question.
2. M2 script: GPU + memory targets, automatic environment reading over I2C
   with manual fallback, automatic clock pinning/restore around each run.
