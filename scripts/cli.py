#!/usr/bin/env python
"""
T2S Eval — administrative CLI.

Subcommands:

  runs list                         List all runs with status and question count
  runs list --status pending        Filter by status
  runs create --name NAME [filters] Create a pending run (does not execute it)
  runs start <run_id>               Execute an existing pending (or interrupted) run
  runs status <run_id>              Print current status and progress of a run

  seed [--dry-run]                  Generate questions for all under-filled strata
  leakage-check                     Run leakage checks on all unchecked questions

Examples:

  # See what runs are pending
  python scripts/cli.py runs list --status pending

  # Create a run filtered to a single table, then start it
  python scripts/cli.py runs create --name "orders-batch" --table orders
  python scripts/cli.py runs start <run_id printed above>

  # Or use runner/main.py to create + execute in one shot
  python runner/main.py --name "orders-batch" --table orders

  # Seed questions before a run
  python scripts/cli.py seed --dry-run   # preview
  python scripts/cli.py seed             # write to Spanner

  # Run leakage checks on newly seeded questions
  python scripts/cli.py leakage-check
"""
import argparse
import json
import sys


# ─── runs list ────────────────────────────────────────────────────────────────

def cmd_runs_list(args) -> None:
    from src.services.spanner_eval import list_runs
    runs = list_runs(limit=args.limit)
    if args.status:
        runs = [r for r in runs if r.status == args.status]
    if not runs:
        print("No runs found.")
        return
    print(f"{'ID':<38} {'NAME':<30} {'STATUS':<12} {'QUESTIONS':<10} CREATED")
    print("-" * 110)
    for r in runs:
        name = (r.name or "")[:29]
        qs = str(r.total_questions) if r.total_questions is not None else "—"
        created = r.created_at.isoformat() if hasattr(r.created_at, "isoformat") else str(r.created_at)
        print(f"{r.id:<38} {name:<30} {r.status:<12} {qs:<10} {created}")


# ─── runs create ──────────────────────────────────────────────────────────────

def cmd_runs_create(args) -> None:
    from src.services.spanner_eval import create_run
    question_filter: dict = {}
    if args.status_filter and args.status_filter != "all":
        question_filter["status"] = args.status_filter
    if args.table:
        question_filter["table_name"] = args.table
    if args.task:
        question_filter["task"] = args.task
    if args.tone:
        question_filter["tone"] = args.tone

    run = create_run(
        name=args.name,
        config={},
        question_filter=question_filter,
        agent_version=args.agent_version,
        description=args.description,
        question_set_id=args.question_set_id,
    )
    print(f"Created run: {run.id}")
    print(f"  Name:          {run.name or '(unnamed)'}")
    if run.agent_version:
        print(f"  Agent version: {run.agent_version}")
    if run.description:
        print(f"  Description:   {run.description}")
    if run.question_set_id:
        print(f"  Question set:  {run.question_set_id}")
    else:
        print(f"  Filter:        {json.dumps(question_filter) if question_filter else '(none)'}")
    print()
    print(f"To execute this run:")
    print(f"  python runner/main.py --run-id {run.id}")
    print(f"  python scripts/cli.py runs start {run.id}")


# ─── runs start ───────────────────────────────────────────────────────────────

def cmd_runs_start(args) -> None:
    from src.services import spanner_eval, orchestrator
    run = spanner_eval.get_run(args.run_id)
    if run is None:
        print(f"Error: run {args.run_id!r} not found.", file=sys.stderr)
        sys.exit(1)
    if run.status not in ("pending", "running"):
        print(
            f"Error: run {args.run_id!r} has status '{run.status}'. "
            "Only 'pending' or 'running' (interrupted) runs can be started.",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"Starting run {run.id} ({run.name or 'unnamed'}) ...")
    orchestrator.start_run(run.id)
    # start_run blocks until complete
    final = spanner_eval.get_run(run.id)
    if final:
        print(f"Run finished with status: {final.status}")


# ─── runs status ──────────────────────────────────────────────────────────────

def cmd_runs_status(args) -> None:
    from src.services.spanner_eval import get_run, get_run_progress, get_run_metrics
    run = get_run(args.run_id)
    if run is None:
        print(f"Error: run {args.run_id!r} not found.", file=sys.stderr)
        sys.exit(1)
    print(f"Run:     {run.id}")
    print(f"Name:    {run.name or '(unnamed)'}")
    print(f"Status:  {run.status}")
    if run.resume_count:
        print(f"Resumed: {run.resume_count}×")
    if run.total_questions is not None:
        print(f"Total questions: {run.total_questions}")
    if run.status == "running":
        progress = get_run_progress(run.id)
        completed = progress.get("completed", 0)
        total = progress.get("total", run.total_questions or 0)
        pct = (completed / total * 100) if total else 0
        print(f"Progress: {completed}/{total} ({pct:.1f}%)")
    if run.started_at:
        print(f"Started:   {run.started_at}")
    if run.completed_at:
        print(f"Completed: {run.completed_at}")
    if run.status == "completed":
        metrics = get_run_metrics(run.id)
        if metrics:
            print()
            print(f"Results:")
            print(f"  Passed:          {metrics.count_passed}/{metrics.total} ({metrics.pct_passed:.1f}%)")
            print(f"  Failed:          {metrics.count_failed}")
            print(f"  Rule violations: {metrics.count_rule_violation}")
            print(f"  Low-conf passes: {metrics.count_low_conf_pass}")
            if metrics.avg_runtime_ms:
                print(f"  Avg runtime:     {metrics.avg_runtime_ms / 1000:.1f}s per question")


# ─── question-sets ────────────────────────────────────────────────────────────

def cmd_qsets_list(args) -> None:
    from src.services.spanner_eval import list_question_sets
    sets = list_question_sets(limit=args.limit)
    if not sets:
        print("No question sets found.")
        return
    print(f"{'ID':<38} {'NAME':<30} {'VERSION':<16} {'COUNT':>6} CREATED")
    print("-" * 105)
    for qs in sets:
        version = qs.version or "—"
        created = qs.created_at.isoformat() if hasattr(qs.created_at, "isoformat") else str(qs.created_at)
        print(f"{qs.id:<38} {qs.name[:29]:<30} {version:<16} {qs.question_count:>6} {created}")
        if qs.description:
            print(f"{'':38} {qs.description[:80]}")


def cmd_qsets_create(args) -> None:
    from src.services.spanner_eval import create_question_set, list_questions

    question_filter: dict = {}
    if args.status_filter and args.status_filter != "all":
        question_filter["status"] = args.status_filter
    if args.table:
        question_filter["table_name"] = args.table
    if args.task:
        question_filter["task"] = args.task
    if args.tone:
        question_filter["tone"] = args.tone

    statuses = [question_filter["status"]] if "status" in question_filter else ["active", "monitoring"]
    questions = []
    for status in statuses:
        questions.extend(list_questions(
            status=status, leakage_checked=True,
            table_name=question_filter.get("table_name"),
            task=question_filter.get("task"),
            tone=question_filter.get("tone"),
            page=1, page_size=10000,
        ))

    if not questions:
        print("Error: no eligible questions match the given filter.", file=sys.stderr)
        sys.exit(1)

    print(f"Snapshotting {len(questions)} questions into question set '{args.name}' ...")
    qs = create_question_set(
        name=args.name,
        question_ids=[q.id for q in questions],
        version=args.version,
        description=args.description,
    )
    print(f"Created question set: {qs.id}")
    print(f"  Name:        {qs.name}")
    if qs.version:
        print(f"  Version:     {qs.version}")
    if qs.description:
        print(f"  Description: {qs.description}")
    print(f"  Questions:   {qs.question_count}")
    print()
    print("To run against this question set:")
    print(f"  python scripts/cli.py runs create --name \"my-run\" --question-set-id {qs.id}")
    print(f"  python runner/main.py --name \"my-run\" --question-set-id {qs.id}")


def cmd_qsets_show(args) -> None:
    from src.services.spanner_eval import get_question_set
    qs = get_question_set(args.qs_id)
    if qs is None:
        print(f"Error: question set {args.qs_id!r} not found.", file=sys.stderr)
        sys.exit(1)
    print(f"ID:          {qs.id}")
    print(f"Name:        {qs.name}")
    print(f"Version:     {qs.version or '—'}")
    print(f"Questions:   {qs.question_count}")
    created = qs.created_at.isoformat() if hasattr(qs.created_at, "isoformat") else str(qs.created_at)
    print(f"Created:     {created}")
    if qs.description:
        print(f"Description: {qs.description}")


# ─── seed ─────────────────────────────────────────────────────────────────────

def cmd_seed(args) -> None:
    from src.services.seeder import seed_all
    dry = args.dry_run
    action = "Dry-run seeding" if dry else "Seeding"
    print(f"{action} question bank ...")
    report = seed_all(dry_run=dry)
    print()
    print(f"Strata processed:    {report.strata_processed}")
    print(f"Questions generated: {report.questions_generated}")
    if dry:
        print(f"Would write:         {report.questions_generated - report.skipped_duplicate}")
    else:
        print(f"Questions written:   {report.questions_written}")
    print(f"Duplicates skipped:  {report.skipped_duplicate}")
    if report.strata_detail:
        print()
        print(f"{'TABLE':<20} {'TASK':<25} {'TONE':<10} {'NEEDED':>6} {'WRITTEN':>7}")
        print("-" * 75)
        for d in report.strata_detail:
            written = d["generated"] - d["skipped_duplicate"] if dry else d["written"]
            print(f"{d['table_name']:<20} {d['task']:<25} {d['tone']:<10} {d['needed']:>6} {written:>7}")
    if dry:
        print()
        print("(Dry run — no changes written. Re-run without --dry-run to apply.)")


# ─── leakage-check ────────────────────────────────────────────────────────────

def cmd_leakage_check(_args) -> None:
    from src.services import spanner_eval
    from src.services.leakage import run_leakage_check

    questions = spanner_eval.list_unchecked_questions()
    if not questions:
        print("No unchecked questions found.")
        return

    print(f"Running leakage checks on {len(questions)} question(s) ...")
    passed = failed = errors = 0
    for q in questions:
        try:
            result = run_leakage_check(q)
            if result.overall_passed:
                passed += 1
            else:
                failed += 1
                print(f"  FLAGGED  {q.id[:8]} — {q.nlq[:60]}")
                if result.embedding_flagged:
                    print(f"           Embedding similarity {result.embedding_max_sim:.3f} > threshold")
                if result.llm_flagged:
                    print(f"           LLM: {(result.llm_reasoning or '')[:80]}")
        except Exception as e:
            errors += 1
            print(f"  ERROR    {q.id[:8]} — {e}", file=sys.stderr)

    print()
    print(f"Passed:  {passed}")
    print(f"Flagged: {failed}")
    if errors:
        print(f"Errors:  {errors}")


# ─── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="T2S Eval admin CLI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    # ── runs ──────────────────────────────────────────────────────────────────
    runs_p = sub.add_parser("runs", help="Manage evaluation runs.")
    runs_sub = runs_p.add_subparsers(dest="runs_command", metavar="ACTION")
    runs_sub.required = True

    # runs list
    list_p = runs_sub.add_parser("list", help="List runs.")
    list_p.add_argument("--status", help="Filter by status (pending, running, completed, failed, cancelled).")
    list_p.add_argument("--limit", type=int, default=50, help="Max rows to return (default: 50).")
    list_p.set_defaults(func=cmd_runs_list)

    # runs create
    create_p = runs_sub.add_parser("create", help="Create a pending run without executing it.")
    create_p.add_argument("--name", required=True, help="Run name.")
    create_p.add_argument("--agent-version", dest="agent_version",
                          help="Agent version label (e.g. 'v1.2.3', git SHA, image tag).")
    create_p.add_argument("--description", help="Free-text notes about this run.")
    create_p.add_argument("--question-set-id", dest="question_set_id",
                          help="ID of a QuestionSet to use instead of a filter.")
    create_p.add_argument("--status-filter", dest="status_filter", default="active",
                          help="Question status to include (default: active). Use 'all' to skip.")
    create_p.add_argument("--table", help="Restrict to a specific table name.")
    create_p.add_argument("--task", help="Restrict to a specific task label.")
    create_p.add_argument("--tone", choices=["casual", "neutral", "formal"],
                          help="Restrict to a specific tone.")
    create_p.set_defaults(func=cmd_runs_create)

    # runs start
    start_p = runs_sub.add_parser("start", help="Execute an existing pending run (blocks until complete).")
    start_p.add_argument("run_id", help="Run ID to start.")
    start_p.set_defaults(func=cmd_runs_start)

    # runs status
    status_p = runs_sub.add_parser("status", help="Print the status and metrics of a run.")
    status_p.add_argument("run_id", help="Run ID to inspect.")
    status_p.set_defaults(func=cmd_runs_status)

    # ── question-sets ─────────────────────────────────────────────────────────
    qs_p = sub.add_parser("question-sets", help="Manage named question set snapshots.")
    qs_sub = qs_p.add_subparsers(dest="qs_command", metavar="ACTION")
    qs_sub.required = True

    qs_list_p = qs_sub.add_parser("list", help="List all question sets.")
    qs_list_p.add_argument("--limit", type=int, default=50)
    qs_list_p.set_defaults(func=cmd_qsets_list)

    qs_create_p = qs_sub.add_parser("create", help="Snapshot current questions into a named set.")
    qs_create_p.add_argument("--name", required=True, help="Question set name.")
    qs_create_p.add_argument("--version", help="Version label (e.g. 'v1', '2024-01-15').")
    qs_create_p.add_argument("--description", help="Free-text notes about this question set.")
    qs_create_p.add_argument("--status-filter", dest="status_filter", default="active",
                             help="Question status to include (default: active). Use 'all' to skip.")
    qs_create_p.add_argument("--table", help="Restrict to a specific table name.")
    qs_create_p.add_argument("--task", help="Restrict to a specific task label.")
    qs_create_p.add_argument("--tone", choices=["casual", "neutral", "formal"])
    qs_create_p.set_defaults(func=cmd_qsets_create)

    qs_show_p = qs_sub.add_parser("show", help="Show details of a question set.")
    qs_show_p.add_argument("qs_id", help="Question set ID.")
    qs_show_p.set_defaults(func=cmd_qsets_show)

    # ── seed ──────────────────────────────────────────────────────────────────
    seed_p = sub.add_parser("seed", help="Generate questions for under-filled strata.")
    seed_p.add_argument("--dry-run", action="store_true",
                        help="Preview without writing to Spanner.")
    seed_p.set_defaults(func=cmd_seed)

    # ── leakage-check ─────────────────────────────────────────────────────────
    lc_p = sub.add_parser("leakage-check", help="Run leakage checks on all unchecked questions.")
    lc_p.set_defaults(func=cmd_leakage_check)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
