#!/usr/bin/env python3
"""Supervisor for batch Google rating caching — runs HK Island then TST, auto-restarts on crash."""
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent.parent
SCRIPT = BASE / "scripts" / "batch_cache_area.py"
CACHE_FILE = BASE / "data" / "google_ratings_cache.json"

AREAS = [
    str(BASE / "data" / "_uncached_hk_island.csv"),
    str(BASE / "data" / "_uncached_tst.csv"),
]

MAX_RETRIES = 5
TIMEOUT_SECONDS = 600  # kill if no output for 10 min
RESTART_DELAY = 5


def count_remaining(area_csv: str, cache: dict) -> int:
    """Count venues in area CSV not yet in cache."""
    import csv
    with open(area_csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    count = 0
    for row in rows:
        key = f"{row['name'].strip()}|{row['address'].strip()}"
        if key not in cache:
            count += 1
    return count


def load_cache() -> dict:
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(BASE / "data" / "batch_supervisor.log", "a") as f:
        f.write(line + "\n")


def run_batch(area_csv: str) -> bool:
    """Run batch_cache_area.py for one area. Returns True if completed, False if crashed."""
    area_name = Path(area_csv).stem.replace("_uncached_", "")
    cache = load_cache()
    remaining = count_remaining(area_csv, cache)
    log(f"Starting {area_name}: {remaining} venues remaining (cache={len(cache)})")

    if remaining == 0:
        log(f"{area_name}: already done, skipping")
        return True

    for attempt in range(1, MAX_RETRIES + 1):
        cache_before = len(load_cache())
        log(f"  Attempt {attempt}/{MAX_RETRIES}")

        try:
            proc = subprocess.Popen(
                [sys.executable, str(SCRIPT), area_csv],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=str(BASE),
            )

            last_output_time = time.time()
            for line in proc.stdout:
                last_output_time = time.time()
                print(f"  {line.rstrip()}", flush=True)

            proc.wait(timeout=30)
            cache_after = len(load_cache())
            added = cache_after - cache_before

            if proc.returncode == 0:
                log(f"  {area_name} completed: +{added} cached, total={cache_after}")
                return True
            else:
                log(f"  {area_name} exited code {proc.returncode}, +{added} cached before crash")

        except subprocess.TimeoutExpired:
            proc.kill()
            log(f"  {area_name} timed out, killed")
        except Exception as e:
            log(f"  {area_name} error: {type(e).__name__}: {e}")

        if attempt < MAX_RETRIES:
            log(f"  Restarting in {RESTART_DELAY}s...")
            time.sleep(RESTART_DELAY)

    log(f"  {area_name} FAILED after {MAX_RETRIES} retries")
    return False


def main():
    log("=" * 60)
    log("Batch supervisor started")
    log(f"Areas: {[Path(a).stem for a in AREAS]}")

    all_ok = True
    for area_csv in AREAS:
        ok = run_batch(area_csv)
        if not ok:
            all_ok = False

    cache = load_cache()
    log(f"All done. Cache: {len(cache)} entries. Success: {all_ok}")


if __name__ == "__main__":
    main()
