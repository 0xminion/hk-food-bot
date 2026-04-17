#!/usr/bin/env python3
"""
Automated data refresh pipeline for HK Food Bot.

Runs the full data pipeline:
1. Scrape latest data from OpenRice
2. Merge with Google Maps data
3. Optionally restart the bot

Usage:
    python scripts/refresh_data.py                  # Full pipeline
    python scripts/refresh_data.py --merge-only     # Skip scraping, just merge
    python scripts/refresh_data.py --dry-run        # Show what would happen

Designed to run as a cron job: 0 3 * * 0 (Sunday 3am)
"""

import argparse
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("refresh")

BOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BOT_DIR / "data"
SCRIPTS_DIR = BOT_DIR / "scripts"
MERGED_CSV = DATA_DIR / "merged_places.csv"
OR_CSV = DATA_DIR / "openrice_places.csv"
STATUS_FILE = DATA_DIR / "batch_status.json"


def run_step(name: str, cmd: list[str], timeout: int = 600) -> bool:
    """Run a pipeline step and return success/failure."""
    log.info(f"▶ {name}")
    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(BOT_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.time() - start
        if result.returncode == 0:
            log.info(f"✓ {name} completed in {elapsed:.1f}s")
            if result.stdout.strip():
                for line in result.stdout.strip().split("\n")[-5:]:
                    log.info(f"  {line}")
            return True
        else:
            log.error(f"✗ {name} failed (exit {result.returncode})")
            if result.stderr.strip():
                for line in result.stderr.strip().split("\n")[-5:]:
                    log.error(f"  {line}")
            return False
    except subprocess.TimeoutExpired:
        log.error(f"✗ {name} timed out after {timeout}s")
        return False
    except Exception as e:
        log.error(f"✗ {name} error: {e}")
        return False


def update_status(success: bool, message: str):
    """Write status file for monitoring."""
    import json
    status = {
        "last_run": datetime.now(timezone.utc).isoformat(),
        "success": success,
        "message": message,
        "venues": 0,
    }
    if MERGED_CSV.exists():
        import csv
        with open(MERGED_CSV, encoding="utf-8") as f:
            status["venues"] = sum(1 for _ in csv.DictReader(f))
    STATUS_FILE.write_text(json.dumps(status, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Refresh HK Food Bot data")
    parser.add_argument("--merge-only", action="store_true", help="Skip scraping, just merge")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen")
    args = parser.parse_args()

    log.info("=" * 50)
    log.info("HK Food Bot — Data Refresh Pipeline")
    log.info("=" * 50)

    if args.dry_run:
        log.info("DRY RUN — no changes will be made")
        log.info(f"  Scraper: {SCRIPTS_DIR / 'openrice.py'} (if not --merge-only)")
        log.info(f"  Merger:  {SCRIPTS_DIR / 'merge_data.py'}")
        log.info(f"  Output:  {MERGED_CSV}")
        return

    steps_ok = True

    # Step 1: Scrape OpenRice (skip if --merge-only)
    if not args.merge_only:
        ok = run_step(
            "OpenRice scraper",
            [
                sys.executable, "-m", "scrapers.openrice",
                "--output", str(OR_CSV),
                "--max-pages", "200",
            ],
            timeout=900,
        )
        if not ok:
            log.warning("Scraper failed — continuing with existing data")

    # Step 2: Merge data
    ok = run_step(
        "Merge data",
        [sys.executable, str(SCRIPTS_DIR / "merge_data.py")],
        timeout=120,
    )
    if not ok:
        steps_ok = False
        log.error("Merge failed — data may be stale")

    # Step 3: Validate output
    if MERGED_CSV.exists():
        import csv
        with open(MERGED_CSV, encoding="utf-8") as f:
            count = sum(1 for _ in csv.DictReader(f))
        log.info(f"✓ Validation: {count} venues in merged CSV")
        if count < 1000:
            log.warning(f"⚠ Only {count} venues — expected 10000+")
    else:
        log.error("✗ Merged CSV not found after pipeline")
        steps_ok = False

    # Update status
    if steps_ok:
        update_status(True, "Pipeline completed successfully")
        log.info("✓ Data refresh complete")
    else:
        update_status(False, "Pipeline completed with errors")
        log.error("✗ Data refresh completed with errors")
        sys.exit(1)


if __name__ == "__main__":
    main()
