"""Cloud Run Job entrypoint.

On startup:
1. Check for stale 'running' runs (heartbeat older than HEARTBEAT_STALE_MINUTES) → resume
2. Otherwise, find the oldest 'pending' run → start fresh
3. Never resume cancelled runs.
"""
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> None:
    # Import here so dotenv is loaded first via settings.py
    from src.config.settings import get_config
    from src.services import spanner_eval, orchestrator

    cfg = get_config()

    # 1. Look for interrupted runs
    stale_runs = spanner_eval.find_stale_running_runs(cfg.heartbeat_stale_minutes)
    if stale_runs:
        run = stale_runs[0]
        log.info("Found interrupted run %s (status=%s, resume_count=%d). Resuming.",
                 run.id, run.status, run.resume_count)
        orchestrator.start_run(run.id)
        return

    # 2. Look for a pending run
    pending = spanner_eval.find_pending_run()
    if pending:
        log.info("Starting pending run %s (%s)", pending.id, pending.name or "unnamed")
        orchestrator.start_run(pending.id)
        return

    log.info("No pending or interrupted runs found. Exiting.")
    sys.exit(0)


if __name__ == "__main__":
    main()
