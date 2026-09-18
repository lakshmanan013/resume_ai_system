"""
Auto Job Syncer Service for Resume AI.

Continuously and automatically synchronizes live job postings from the Adzuna Jobs API
into the database every 10 seconds. Ensures new openings are detected, enriched with
canonical skills via the NLP pipeline, and automatically saved into MySQL 'ai_resume'.
"""

import sys
import time
import signal
import logging
import threading
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import adzuna_client
import models
from config import Config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("AutoJobSyncer")

# Rotating tech search categories for comprehensive market coverage
DEFAULT_SYNC_QUERIES = [
    "python developer",
    "react developer",
    "data analyst",
    "full stack developer",
    "devops engineer",
    "machine learning engineer",
    "cloud engineer",
    "java developer",
    "frontend developer",
    "backend developer",
    "artificial intelligence",
    "cybersecurity engineer",
    "data engineer",
    "software engineer",
    "mobile app developer"
]


class AutoJobSyncer:
    """
    Background worker that runs every N seconds (default: 10s) to query Adzuna
    for the latest live job postings, enrich them, and automatically save them into MySQL.
    """

    def __init__(self, interval_seconds: int = 10, queries: Optional[List[str]] = None):
        self.interval_seconds = max(5, interval_seconds)
        self.queries = queries or DEFAULT_SYNC_QUERIES
        self._query_index = 0
        self._is_running = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Operational metrics
        self._last_sync_time: Optional[str] = None
        self._last_query: Optional[str] = None
        self._last_batch_new_count: int = 0
        self._last_batch_saved_count: int = 0
        self._total_synced_lifetime: int = 0
        self._total_new_jobs_lifetime: int = 0
        self._sync_ticks_completed: int = 0
        self._latest_synced_jobs: List[Dict[str, Any]] = []

    def start(self):
        """Starts the background daemon sync thread if not already active."""
        with self._lock:
            if self._is_running and self._thread and self._thread.is_alive():
                logger.info("AutoJobSyncer already running.")
                return

            self._is_running = True
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="AutoJobSyncerThread",
                daemon=True
            )
            self._thread.start()
            logger.info("AutoJobSyncer active! Syncing Adzuna live jobs every %ds into MySQL.", self.interval_seconds)

    def stop(self):
        """Signals the background sync thread to stop gracefully."""
        with self._lock:
            if not self._is_running:
                return
            logger.info("Stopping AutoJobSyncer...")
            self._is_running = False
            self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        logger.info("AutoJobSyncer stopped.")

    def sync_tick(self) -> Dict[str, Any]:
        """
        Executes a single live sync cycle:
        1. Selects the next rotating query.
        2. Queries Adzuna for the newest live jobs (sort_by='date').
        3. Enriches with canonical skills and saves to database.
        4. Updates status and newly discovered job records.
        """
        if not Config.is_adzuna_configured():
            logger.warning("Adzuna credentials not configured. Skipping auto-sync tick.")
            return {
                "success": False,
                "error": "Adzuna credentials not configured",
                "new_count": 0,
                "saved_count": 0,
                "synced": 0
            }

        # Pick query in round-robin sequence
        with self._lock:
            query = self.queries[self._query_index % len(self.queries)]
            self._query_index += 1
            self._last_query = query

        try:
            # Sync 10 newest jobs for this target role
            res = adzuna_client.sync_live_adzuna_batch(query=query, count=10)
            now_iso = datetime.now(timezone.utc).isoformat()

            # Handle transient upstream API errors (503, 502, 429, timeouts)
            if not res.get("success"):
                err_msg = res.get("error", "Upstream API temporarily unavailable")
                total_active = models.get_active_jobs_count()
                logger.warning(
                    "⚠️ [Tick #%d] Adzuna API notice for '%s' (%s). Auto-retrying next cycle in %ds | Active in DB: %d",
                    self._sync_ticks_completed + 1,
                    query,
                    err_msg,
                    self.interval_seconds,
                    total_active
                )
                with self._lock:
                    self._last_sync_time = now_iso
                    self._sync_ticks_completed += 1
                    self._last_batch_new_count = 0
                    self._last_batch_saved_count = 0
                return {
                    "success": False,
                    "query": query,
                    "error": err_msg,
                    "synced": 0,
                    "saved_count": 0,
                    "new_count": 0,
                    "total_active": total_active,
                    "timestamp": now_iso
                }

            synced_count = res.get("synced", 0)
            saved_jobs = res.get("saved_jobs", [])
            new_jobs = res.get("new_jobs", [])
            new_count = len(new_jobs)

            with self._lock:
                self._last_sync_time = now_iso
                self._last_batch_new_count = new_count
                self._last_batch_saved_count = len(saved_jobs)
                self._total_synced_lifetime += synced_count
                self._total_new_jobs_lifetime += new_count
                self._sync_ticks_completed += 1

                # Maintain rolling window of recently updated live jobs
                if saved_jobs:
                    self._latest_synced_jobs = (saved_jobs + self._latest_synced_jobs)[:30]
                elif res.get("synced", 0) > 0:
                    latest = models.get_latest_active_jobs(limit=15)
                    self._latest_synced_jobs = latest[:15]

            total_active = models.get_active_jobs_count()
            logger.info(
                "⚡ [Tick #%d] Query: '%s' | %d fetched | %d saved to MySQL (%d NEW) | Total Active in DB: %d",
                self._sync_ticks_completed,
                query,
                synced_count,
                len(saved_jobs),
                new_count,
                total_active
            )

            # Log individual newly added jobs
            for j in new_jobs:
                logger.info(
                    "   🔥 [NEW JOB SAVED] DB ID #%s: '%s' @ %s (%s) | Skills: %s",
                    j.get("id"),
                    j.get("title"),
                    j.get("company"),
                    j.get("location"),
                    j.get("required_skills")
                )

            return {
                "success": True,
                "query": query,
                "synced": synced_count,
                "saved_count": len(saved_jobs),
                "new_count": new_count,
                "total_active": total_active,
                "timestamp": now_iso,
                "saved_jobs": saved_jobs,
                "new_jobs": new_jobs
            }
        except Exception as e:
            total_active = models.get_active_jobs_count()
            logger.warning("⚠️ AutoJobSyncer cycle notice: %s (will auto-retry next tick)", e)
            return {
                "success": False,
                "error": str(e),
                "new_count": 0,
                "saved_count": 0,
                "synced": 0,
                "total_active": total_active
            }

    def _run_loop(self):
        """Worker loop executed by the background thread every 10 seconds."""
        logger.info("AutoJobSyncer background loop initialized (interval: %ds).", self.interval_seconds)
        # Perform initial sync tick immediately on startup
        self.sync_tick()

        while not self._stop_event.is_set():
            # Sleep in intervals of 10s (interruptible by stop_event)
            stopped = self._stop_event.wait(timeout=self.interval_seconds)
            if stopped:
                break
            self.sync_tick()

    def get_status(self) -> Dict[str, Any]:
        """Returns comprehensive operational metrics for monitoring."""
        with self._lock:
            total_active = models.get_active_jobs_count()
            return {
                "is_running": self._is_running and bool(self._thread and self._thread.is_alive()),
                "interval_seconds": self.interval_seconds,
                "last_sync_time": self._last_sync_time,
                "last_query": self._last_query,
                "new_jobs_last_tick": self._last_batch_new_count,
                "saved_jobs_last_tick": self._last_batch_saved_count,
                "total_new_jobs_synced": self._total_new_jobs_lifetime,
                "total_active_jobs": total_active,
                "sync_ticks_completed": self._sync_ticks_completed,
                "latest_jobs": self._latest_synced_jobs[:15]
            }


# Singleton service instance
syncer = AutoJobSyncer(interval_seconds=10)


def start_auto_syncer(interval_seconds: int = 10):
    """Starts the global auto-syncer service."""
    syncer.interval_seconds = max(5, interval_seconds)
    syncer.start()


def stop_auto_syncer():
    """Stops the global auto-syncer service."""
    syncer.stop()


def get_auto_syncer_status() -> Dict[str, Any]:
    """Fetches global auto-syncer metrics."""
    return syncer.get_status()


def trigger_manual_sync() -> Dict[str, Any]:
    """Manually triggers an immediate sync cycle."""
    return syncer.sync_tick()


if __name__ == "__main__":
    print("=" * 75)
    print("  RESUME AI — 10-SECOND ADZUNA LIVE AUTO-SYNC SERVICE")
    print("  Auto-Sync Interval: Every 10 Seconds | Database: MySQL 'ai_resume'")
    print("  Auto-Save: Live Jobs fetched from Adzuna are saved to DB immediately")
    print("=" * 75)

    # Clean shutdown on Ctrl+C
    def _sig_handler(sig, frame):
        print("\nStopping AutoJobSyncer cleanly...")
        syncer.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    print("\nStarting live sync worker... Press Ctrl+C to stop.\n")
    syncer.start()

    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        syncer.stop()
