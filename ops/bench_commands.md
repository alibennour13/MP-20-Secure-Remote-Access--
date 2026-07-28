# Bench Command Card — M0 + M1 over WiFi from WSL2

Replace the address once, everything else copy-pastes:

```bash
export J=jetsonuser@192.168.1.42     # your Jetson user@IP — set in every new WSL window
```

## A) One-time, physically at the Jetson

```bash
hostname -I                    # note the IP for $J
sudo systemctl status ssh      # should be active (JetPack default)
```

## B) Connect from WSL2

```bash
ssh $J                         # accept fingerprint on first connect
```

## C) Transfer the scripts (from WSL, not inside ssh)

```bash
ssh $J "mkdir -p ~/stress"
scp /mnt/c/Users/pc/Desktop/m0_bench_check.py \
    /mnt/c/Users/pc/Desktop/m1_stress_test_jetson.py  $J:~/stress/
```

## D) Install dependencies (inside ssh, once)

```bash
sudo apt update && sudo apt install -y stress-ng python3-matplotlib tmux
```

## E) M0 — bench checker (inside ssh)

```bash
cd ~/stress && python3 m0_bench_check.py     # fix flags until READY FOR M1
```

## F) Run the test — ALWAYS inside tmux (inside ssh)

```bash
tmux new -s stress                                    # persistent session
cd ~/stress
python3 m1_stress_test_jetson.py --ambient-c 24.5 --levels 10 --trials 1   # 1) shakedown
python3 m1_stress_test_jetson.py --ambient-c 24.5 --humidity 60            # 2) full fast (~10-12 min)
python3 m1_stress_test_jetson.py --ambient-c 24.5 --profile deep           # 3) later: calibration (~2 h)
```

Detach and leave it running: `Ctrl-B` then `D`. Reattach anytime:

```bash
ssh $J -t "tmux attach -t stress"
```

## G) Monitor from a second WSL window (without touching the test)

```bash
ssh $J "tegrastats --interval 2000"                       # live temps/clocks (Ctrl-C exits view only)
ssh $J 'cat /sys/class/thermal/thermal_zone*/temp'        # instant temps (millidegrees: 51500 = 51.5 °C)
ssh $J "pgrep -a stress-ng"                               # is a load running?
ssh $J "ls ~/stress/runs"                                 # runs produced so far
```

## H) STOPPING the test — four levels, in order of preference

**1. Attached (cleanest):** press `Ctrl-C` inside the tmux session.
→ script aborts safely, kills the load, writes a FAIL(operator) report.

**2. Remote graceful stop (one-liner from WSL — TEST THIS ONE during the shakedown):**

```bash
ssh $J 'pkill -INT -f m1_stress_test_jetson.py'
```

→ same clean abort as Ctrl-C, no need to attach.

**3. Kill the tmux session (also graceful — the script handles SIGHUP):**

```bash
ssh $J 'tmux kill-session -t stress'
```

**4. EMERGENCY — script hung, nothing responds (bypasses all cleanup, so the
load must be killed manually too — always both commands together):**

```bash
ssh $J 'pkill -9 -f m1_stress_test_jetson.py; pkill -9 stress-ng'
```

## I) Verify everything is stopped (after ANY stop, especially method 4)

```bash
ssh $J 'pgrep -a stress-ng || echo "CLEAN — no load running"'
ssh $J 'cat /sys/class/thermal/thermal_zone*/temp'    # run twice, 30 s apart: numbers must be FALLING
```

## J) Retrieve results back to Windows (from WSL)

```bash
scp -r $J:~/stress/runs           /mnt/c/Users/pc/Desktop/
scp $J:~/stress/bench_report.txt  $J:~/stress/tegrastats_sample.txt  /mnt/c/Users/pc/Desktop/
```

## Exit codes (for scripts later)
`0` = PASS · `2` = FAIL (cause in report.txt, first line)

## The drill (do this once, during the shakedown)
Start the shakedown in tmux → from a second WSL window run stop method 2 →
confirm the report says FAIL / cause: operator → run the two verify commands.
Now the stop procedure is rehearsed, not just written down.
