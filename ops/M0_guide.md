# M0 — Bench Setup Guide (one page)

Goal: by the end of M0 the bench is verified, the configuration is frozen and
recorded, and we have one real telemetry sample to build M1 against.
The checker script is **read-only** — it changes nothing.

## Step 1 — Copy the checker to the Jetson and run it

```bash
python3 m0_bench_check.py
```

It prints a checklist and writes two files: `bench_report.txt` and
`tegrastats_sample.txt`.

## Step 2 — Fix anything it flags [FAIL]

Most likely fixes (only run what the report asks for):

```bash
sudo apt update
sudo apt install stress-ng git i2c-tools      # load generator, versioning, future sensor
sudo pip3 install jetson-stats                # optional: jtop live monitor (reboot after)
```

## Step 3 — Freeze the configuration (the two decisions of M0)

Pick once, write it down, never change it mid-milestone:

1. **Power mode** — use the mode the robot will actually deploy with
   (15 W or 25 W; never MAXN for testing):

   ```bash
   sudo nvpmodel -q          # see current mode
   sudo nvpmodel -m <N>      # set it if needed (may ask to reboot)
   sudo jetson_clocks        # pin clocks at the mode maximum
   sudo jetson_clocks --show # confirm and screenshot/save this output
   ```

2. **Fan mode** — Quiet (default) or Cool. Keep whatever it is, just record it:

   ```bash
   grep FAN_DEFAULT_PROFILE /etc/nvfancontrol.conf
   ```

Record both in a note (they go into every test report's metadata).

## Step 4 — One supervised manual stress (watch, don't automate yet)

Terminal A: `tegrastats --interval 1000`
Terminal B: `stress-ng --cpu 6 --timeout 60s`

Watch for one minute: temperatures climb smoothly, CPU frequencies stay
pinned, nothing dramatic. Ctrl-C terminal A when done. That's the whole
point — see the board behave with your own eyes before any script does.

## Step 5 — Re-run the checker → send back the two files

When it says **READY FOR M1**, send `bench_report.txt` and
`tegrastats_sample.txt` back. M1's measurement script gets written against
your board's exact telemetry format — no guessed parsing.

---
**M0 exit criteria:** checker green · power+fan mode recorded · one manual
stress observed · two report files delivered.
