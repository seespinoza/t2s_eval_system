"""Cloud Run Job entrypoint.

Default behavior (no flags):
  1. Check for stale 'running' runs (heartbeat older than HEARTBEAT_STALE_MINUTES) → resume
  2. Otherwise, find the oldest 'pending' run → start it
  3. Exit 0 if nothing to do.

Start a specific existing run by ID:

  python runner/main.py --run-id <uuid>

Create a new run immediately and execute it:

  python runner/main.py --name "nightly-2024-01-15"
  python runner/main.py --name "active-orders" --status active --table orders
  python runner/main.py --name "formal-only" --tone formal

Filter flags (--status, --table, --task, --tone) are stored in the run record and
applied when selecting which questions to evaluate.
"""
import argparse
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="T2S eval runner — executes one evaluation run and exits.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--run-id", dest="run_id",
                   help="Start (or resume) a specific existing run by ID.")
    p.add_argument("--name", help="Name for the new run (triggers run creation).")
    p.add_argument(
        "--status",
        default="active",
        help="Question status to include (default: active). Use 'all' to skip status filter.",
    )
    p.add_argument("--table", help="Restrict to questions for this table name.")
    p.add_argument("--task", help="Restrict to questions with this task label.")
    p.add_argument("--tone", choices=["casual", "neutral", "formal"],
                   help="Restrict to questions with this tone.")
    p.add_argument("--agent-version", dest="agent_version",
                   help="Agent version label stored with the run (e.g. 'v1.2.3', git SHA).")
    p.add_argument("--description",
                   help="Free-text notes about this run, stored for later reference.")
    p.add_argument("--question-set-id", dest="question_set_id",
                   help="ID of a QuestionSet to evaluate against instead of a live filter.")
    p.add_argument(
        "--force-create",
        action="store_true",
        help="Create and run a new run even if a pending run already exists. "
             "Ignored when --name or any filter flag is set (those always create).",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    # Import after arg parsing so dotenv loads first via settings.py
    from src.config.settings import get_config
    from src.services import spanner_eval, orchestrator

    cfg = get_config()

    # --run-id: start or resume a specific run by ID
    if args.run_id:
        run = spanner_eval.get_run(args.run_id)
        if run is None:
            log.error("Run %s not found.", args.run_id)
            sys.exit(1)
        if run.status not in ("pending", "running"):
            log.error(
                "Run %s has status '%s'. Only 'pending' or 'running' runs can be started.",
                args.run_id, run.status,
            )
            sys.exit(1)
        log.info("Starting run %s (%s)", run.id, run.name or "unnamed")
        orchestrator.start_run(run.id)
        return

    wants_new_run = bool(
        args.name
        or args.table
        or args.task
        or args.tone
        or (args.status and args.status != "active")
        or args.force_create
    )

    if wants_new_run:
        question_filter: dict = {}
        if args.status and args.status != "all":
            question_filter["status"] = args.status
        if args.table:
            question_filter["table_name"] = args.table
        if args.task:
            question_filter["task"] = args.task
        if args.tone:
            question_filter["tone"] = args.tone

        run = spanner_eval.create_run(
            name=args.name,
            config={},
            question_filter=question_filter,
            agent_version=args.agent_version,
            description=args.description,
            question_set_id=args.question_set_id,
        )
        log.info("Created run %s (%s) with filter %s", run.id, run.name or "unnamed", question_filter)
        orchestrator.start_run(run.id)
        return

    # Default: resume stale run or pick up oldest pending run
    stale_runs = spanner_eval.find_stale_running_runs(cfg.heartbeat_stale_minutes)
    if stale_runs:
        run = stale_runs[0]
        log.info(
            "Found interrupted run %s (status=%s, resume_count=%d). Resuming.",
            run.id, run.status, run.resume_count,
        )
        orchestrator.start_run(run.id)
        return

    pending = spanner_eval.find_pending_run()
    if pending:
        log.info("Starting pending run %s (%s)", pending.id, pending.name or "unnamed")
        orchestrator.start_run(pending.id)
        return

    log.info("No pending or interrupted runs found. Exiting.")
    sys.exit(0)


if __name__ == "__main__":
    main()
