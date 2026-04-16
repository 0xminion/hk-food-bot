#!/usr/bin/env python3
"""
Parallel batch supervisor — runs 2 workers with isolated caches, merges on completion.
Auto-restarts on crash/hang. Monitors via log + status file.
"""
import csv, json, subprocess, sys, time, os, signal
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent.parent
SCRIPT = BASE / "scripts" / "batch_cache_area.py"
MAIN_CACHE = BASE / "data" / "google_ratings_cache.json"
LOG = BASE / "data" / "batch_supervisor_v2.log"
STATUS_FILE = BASE / "data" / "batch_status.json"

# Worker groups with isolated cache files
WORKERS = [
    {
        "name": "group_a_kowloon",
        "csv": str(BASE / "data" / "_uncached_group_a_kowloon.csv"),
        "cache": str(BASE / "data" / "_cache_group_a.json"),
    },
    {
        "name": "group_b_nt_hki",
        "csv": str(BASE / "data" / "_uncached_group_b_nt_hki.csv"),
        "cache": str(BASE / "data" / "_cache_group_b.json"),
    },
]

MAX_RETRIES = 5
STALL_TIMEOUT = 300  # 5 min with no output = hung
RESTART_DELAY = 10


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def save_status(workers_status: dict):
    with open(STATUS_FILE, "w") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "workers": workers_status,
            "main_cache_size": count_cache(MAIN_CACHE),
        }, f, indent=2)


def count_cache(path) -> int:
    try:
        with open(path) as f:
            return len(json.load(f))
    except:
        return 0


def count_remaining(csv_path: str, cache_path: str) -> int:
    cache = {}
    if Path(cache_path).exists():
        with open(cache_path) as f:
            cache = json.load(f)
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return sum(1 for r in rows if f"{r['name'].strip()}|{r['address'].strip()}" not in cache)


def run_worker(worker: dict) -> bool:
    """Run one worker with isolated cache. Returns True if completed."""
    name = worker["name"]
    csv_path = worker["csv"]
    cache_path = worker["cache"]

    remaining = count_remaining(csv_path, cache_path)
    log(f"[{name}] Starting: {remaining} venues (cache={count_cache(cache_path)})")

    if remaining == 0:
        log(f"[{name}] Already done, skipping")
        return True

    for attempt in range(1, MAX_RETRIES + 1):
        cache_before = count_cache(cache_path)
        log(f"[{name}] Attempt {attempt}/{MAX_RETRIES}")

        try:
            env = os.environ.copy()
            env["CACHE_FILE_OVERRIDE"] = cache_path

            proc = subprocess.Popen(
                [sys.executable, str(SCRIPT), csv_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=str(BASE),
                env=env,
            )

            last_output_time = time.time()
            stall_count = 0

            for line in proc.stdout:
                last_output_time = time.time()
                line = line.rstrip()
                if line:
                    print(f"  [{name}] {line}", flush=True)

                # Check for stall
                if time.time() - last_output_time > STALL_TIMEOUT:
                    log(f"[{name}] STALL detected ({STALL_TIMEOUT}s no output), killing")
                    proc.kill()
                    break

            proc.wait(timeout=30)
            cache_after = count_cache(cache_path)
            added = cache_after - cache_before

            if proc.returncode == 0:
                log(f"[{name}] Completed: +{added} cached, cache={cache_after}")
                return True
            else:
                log(f"[{name}] Exit code {proc.returncode}, +{added} before crash")

        except subprocess.TimeoutExpired:
            proc.kill()
            log(f"[{name}] Timed out, killed")
        except Exception as e:
            log(f"[{name}] Error: {type(e).__name__}: {e}")

        if attempt < MAX_RETRIES:
            log(f"[{name}] Restarting in {RESTART_DELAY}s...")
            time.sleep(RESTART_DELAY)

    log(f"[{name}] FAILED after {MAX_RETRIES} retries")
    return False


def merge_caches():
    """Merge all worker caches into main cache."""
    main = {}
    if MAIN_CACHE.exists():
        with open(MAIN_CACHE) as f:
            main = json.load(f)

    total_added = 0
    for worker in WORKERS:
        cache_path = worker["cache"]
        if not Path(cache_path).exists():
            continue
        with open(cache_path) as f:
            worker_cache = json.load(f)
        for key, val in worker_cache.items():
            if key not in main:
                main[key] = val
                total_added += 1

    with open(MAIN_CACHE, "w") as f:
        json.dump(main, f, ensure_ascii=False)

    log(f"Merged: +{total_added} new entries, main cache now {len(main)}")
    return len(main)


def main():
    log("=" * 60)
    log("Parallel batch supervisor v2 started")
    log(f"Workers: {[w['name'] for w in WORKERS]}")

    results = {}
    processes = {}

    # Spawn both workers in parallel
    for worker in WORKERS:
        name = worker["name"]
        csv_path = worker["csv"]
        cache_path = worker["cache"]

        remaining = count_remaining(csv_path, cache_path)
        if remaining == 0:
            log(f"[{name}] Already done, skipping")
            results[name] = True
            continue

        log(f"[{name}] Spawning: {remaining} venues")
        env = os.environ.copy()
        env["CACHE_FILE_OVERRIDE"] = cache_path

        proc = subprocess.Popen(
            [sys.executable, str(SCRIPT), csv_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(BASE),
            env=env,
        )
        processes[name] = {
            "proc": proc,
            "worker": worker,
            "last_output": time.time(),
            "attempt": 1,
            "cache_before": count_cache(cache_path),
        }

    # Monitor both processes
    while processes:
        for name, info in list(processes.items()):
            proc = info["proc"]

            # Read available output (non-blocking)
            import select
            if select.select([proc.stdout], [], [], 0)[0]:
                line = proc.stdout.readline()
                if line:
                    info["last_output"] = time.time()
                    print(f"  [{name}] {line.rstrip()}", flush=True)

            # Check if process exited
            if proc.poll() is not None:
                cache_after = count_cache(info["worker"]["cache"])
                added = cache_after - info["cache_before"]

                if proc.returncode == 0:
                    log(f"[{name}] Completed: +{added}")
                    results[name] = True
                    del processes[name]
                else:
                    log(f"[{name}] Crashed (code {proc.returncode}), +{added}")
                    if info["attempt"] < MAX_RETRIES:
                        info["attempt"] += 1
                        log(f"[{name}] Restarting (attempt {info['attempt']}/{MAX_RETRIES})")
                        time.sleep(RESTART_DELAY)
                        env = os.environ.copy()
                        env["CACHE_FILE_OVERRIDE"] = info["worker"]["cache"]
                        new_proc = subprocess.Popen(
                            [sys.executable, str(SCRIPT), info["worker"]["csv"]],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True,
                            bufsize=1,
                            cwd=str(BASE),
                            env=env,
                        )
                        info["proc"] = new_proc
                        info["last_output"] = time.time()
                        info["cache_before"] = count_cache(info["worker"]["cache"])
                    else:
                        log(f"[{name}] FAILED after {MAX_RETRIES} attempts")
                        results[name] = False
                        del processes[name]
                continue

            # Check for stall
            if time.time() - info["last_output"] > STALL_TIMEOUT:
                log(f"[{name}] STALL ({STALL_TIMEOUT}s), killing")
                proc.kill()
                if info["attempt"] < MAX_RETRIES:
                    info["attempt"] += 1
                    log(f"[{name}] Restarting after stall (attempt {info['attempt']}/{MAX_RETRIES})")
                    time.sleep(RESTART_DELAY)
                    env = os.environ.copy()
                    env["CACHE_FILE_OVERRIDE"] = info["worker"]["cache"]
                    new_proc = subprocess.Popen(
                        [sys.executable, str(SCRIPT), info["worker"]["csv"]],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                        cwd=str(BASE),
                        env=env,
                    )
                    info["proc"] = new_proc
                    info["last_output"] = time.time()
                    info["cache_before"] = count_cache(info["worker"]["cache"])
                else:
                    log(f"[{name}] FAILED (stalled)")
                    results[name] = False
                    del processes[name]

            # Save periodic status
            save_status({n: {
                "running": True,
                "attempt": info["attempt"],
                "cache_size": count_cache(info["worker"]["cache"]),
            } for n, info in processes.items()})

        time.sleep(2)  # Poll interval

    # Merge all caches
    log("All workers done. Merging caches...")
    final_count = merge_caches()

    # Clean up worker cache files
    for worker in WORKERS:
        p = Path(worker["cache"])
        if p.exists():
            p.unlink()
            log(f"Cleaned up {p.name}")

    all_ok = all(results.values())
    log(f"Final: {final_count} cache entries. Success: {all_ok}")

    save_status({"completed": results, "final_cache_size": final_count})


if __name__ == "__main__":
    main()
