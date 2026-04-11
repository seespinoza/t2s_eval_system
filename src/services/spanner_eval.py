"""Read/write access to the eval Spanner database."""
import uuid
from datetime import datetime
from google.cloud.spanner_v1 import param_types, KeySet
from google.cloud.spanner_v1.data_types import JsonObject
from src.core.database import (
    get_eval_db, T_QUESTIONS, T_LEAKAGE_CHECKS,
    T_QUESTION_SETS, T_RUNS, T_RESULTS, T_REVIEW_ITEMS, T_RUN_METRICS,
)
from src.core.models import Question, LeakageCheck, QuestionSet, Run, Result, ReviewItem, RunMetrics

COMMIT_TS = "spanner.commit_timestamp()"


def _keyset(keys: list) -> KeySet:
    return KeySet(keys=[keys])


def _ts(val) -> str | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.isoformat()
    return str(val)


# ─── Questions ────────────────────────────────────────────────────────────────

def list_questions(
    status: str | None = None,
    table_name: str | None = None,
    task: str | None = None,
    tone: str | None = None,
    leakage_checked: bool | None = None,
    page: int = 1,
    page_size: int = 50,
) -> list[Question]:
    db = get_eval_db()
    conditions = ["status != 'deleted'"]
    params: dict = {}
    pt: dict = {}

    if status:
        conditions.append("status = @status")
        params["status"] = status
        pt["status"] = param_types.STRING
    if table_name:
        conditions.append("table_name = @table_name")
        params["table_name"] = table_name
        pt["table_name"] = param_types.STRING
    if task:
        conditions.append("task = @task")
        params["task"] = task
        pt["task"] = param_types.STRING
    if tone:
        conditions.append("tone = @tone")
        params["tone"] = tone
        pt["tone"] = param_types.STRING
    if leakage_checked is not None:
        conditions.append("leakage_checked = @leakage_checked")
        params["leakage_checked"] = leakage_checked
        pt["leakage_checked"] = param_types.BOOL

    where = " AND ".join(conditions)
    offset = (page - 1) * page_size
    sql = (
        f"SELECT {', '.join(Question.COLUMNS)} FROM {T_QUESTIONS} "
        f"WHERE {where} ORDER BY created_at DESC LIMIT {page_size} OFFSET {offset}"
    )
    results: list[Question] = []
    with db.snapshot() as snapshot:
        for row in snapshot.execute_sql(sql, params=params or None, param_types=pt or None):
            results.append(Question.from_row(row))
    return results


def get_question(question_id: str) -> Question | None:
    db = get_eval_db()
    with db.snapshot() as snapshot:
        for row in snapshot.read(T_QUESTIONS, columns=Question.COLUMNS, keyset=_keyset([question_id])):
            return Question.from_row(row)
    return None


def create_question(nlq: str, table_name: str, task: str, tone: str = "neutral",
                    status: str = "active", is_seeded: bool = False,
                    notes: str | None = None) -> Question:
    qid = str(uuid.uuid4())

    def _tx(transaction):
        transaction.insert(
            T_QUESTIONS,
            columns=["id", "nlq", "table_name", "task", "tone", "status", "is_seeded",
                     "leakage_checked", "notes", "created_at", "updated_at"],
            values=[[qid, nlq, table_name, task, tone, status, is_seeded,
                     False, notes, COMMIT_TS, COMMIT_TS]],
        )

    get_eval_db().run_in_transaction(_tx)
    return get_question(qid)


def update_question(question_id: str, **fields) -> Question | None:
    allowed = {"nlq", "table_name", "task", "tone", "status", "notes", "leakage_checked", "leakage_check_id"}
    update = {k: v for k, v in fields.items() if k in allowed}
    if not update:
        return get_question(question_id)
    update["updated_at"] = COMMIT_TS

    def _tx(transaction):
        cols = list(update.keys())
        transaction.update(T_QUESTIONS, columns=["id"] + cols,
                           values=[[question_id] + [update[c] for c in cols]])

    get_eval_db().run_in_transaction(_tx)
    return get_question(question_id)


def soft_delete_question(question_id: str) -> None:
    update_question(question_id, status="deleted")


def bulk_insert_questions(rows: list[dict]) -> int:
    def _tx(transaction):
        values = [
            [str(uuid.uuid4()), r["nlq"], r["table_name"], r["task"],
             r.get("tone", "neutral"), r.get("status", "active"), r.get("is_seeded", False),
             False, r.get("notes"), COMMIT_TS, COMMIT_TS]
            for r in rows
        ]
        transaction.insert(
            T_QUESTIONS,
            columns=["id", "nlq", "table_name", "task", "tone", "status", "is_seeded",
                     "leakage_checked", "notes", "created_at", "updated_at"],
            values=values,
        )

    get_eval_db().run_in_transaction(_tx)
    return len(rows)


def list_unchecked_questions() -> list[Question]:
    results: list[Question] = []
    with get_eval_db().snapshot() as snapshot:
        for row in snapshot.execute_sql(
            f"SELECT {', '.join(Question.COLUMNS)} FROM {T_QUESTIONS} "
            "WHERE leakage_checked = FALSE AND status != 'deleted' ORDER BY created_at"
        ):
            results.append(Question.from_row(row))
    return results


# ─── Leakage Checks ───────────────────────────────────────────────────────────

def insert_leakage_check(
    question_id: str, embedding_flagged: bool, embedding_max_sim: float | None,
    embedding_match_text: str | None, llm_flagged: bool, llm_reasoning: str | None,
    overall_passed: bool,
) -> LeakageCheck:
    check_id = str(uuid.uuid4())

    def _tx(transaction):
        transaction.insert(
            T_LEAKAGE_CHECKS,
            columns=["id", "question_id", "embedding_flagged", "embedding_max_sim",
                     "embedding_match_text", "llm_flagged", "llm_reasoning",
                     "overall_passed", "checked_at"],
            values=[[check_id, question_id, embedding_flagged, embedding_max_sim,
                     embedding_match_text, llm_flagged, llm_reasoning, overall_passed, COMMIT_TS]],
        )
        transaction.update(
            T_QUESTIONS,
            columns=["id", "leakage_checked", "leakage_check_id", "updated_at"],
            values=[[question_id, overall_passed, check_id, COMMIT_TS]],
        )

    get_eval_db().run_in_transaction(_tx)

    with get_eval_db().snapshot() as snapshot:
        for row in snapshot.read(
            T_LEAKAGE_CHECKS, columns=LeakageCheck.COLUMNS,
            keyset=_keyset([question_id, check_id])
        ):
            return LeakageCheck.from_row(row)


def get_leakage_check(question_id: str, check_id: str) -> LeakageCheck | None:
    with get_eval_db().snapshot() as snapshot:
        for row in snapshot.read(
            T_LEAKAGE_CHECKS, columns=LeakageCheck.COLUMNS,
            keyset=_keyset([question_id, check_id])
        ):
            return LeakageCheck.from_row(row)
    return None


# ─── Runs ─────────────────────────────────────────────────────────────────────

# ─── Question Sets ────────────────────────────────────────────────────────────

def create_question_set(
    name: str,
    question_ids: list[str],
    version: str | None = None,
    description: str | None = None,
) -> QuestionSet:
    qs_id = str(uuid.uuid4())

    def _tx(transaction):
        transaction.insert(
            T_QUESTION_SETS,
            columns=["id", "name", "version", "description",
                     "question_ids_json", "question_count", "created_at"],
            values=[[qs_id, name, version, description,
                     JsonObject(question_ids), len(question_ids), COMMIT_TS]],
        )

    get_eval_db().run_in_transaction(_tx)
    return get_question_set(qs_id)


def get_question_set(qs_id: str) -> QuestionSet | None:
    with get_eval_db().snapshot() as snapshot:
        for row in snapshot.read(
            T_QUESTION_SETS, columns=QuestionSet.COLUMNS, keyset=_keyset([qs_id])
        ):
            return QuestionSet.from_row(row)
    return None


def list_question_sets(limit: int = 50) -> list[QuestionSet]:
    results: list[QuestionSet] = []
    with get_eval_db().snapshot() as snapshot:
        for row in snapshot.execute_sql(
            f"SELECT {', '.join(QuestionSet.COLUMNS)} FROM {T_QUESTION_SETS} "
            f"ORDER BY created_at DESC LIMIT {limit}"
        ):
            results.append(QuestionSet.from_row(row))
    return results


def delete_question_set(qs_id: str) -> None:
    def _tx(transaction):
        transaction.delete(T_QUESTION_SETS, keyset=_keyset([qs_id]))
    get_eval_db().run_in_transaction(_tx)


# ─── Runs ─────────────────────────────────────────────────────────────────────

def create_run(
    name: str | None,
    config: dict,
    question_filter: dict,
    agent_version: str | None = None,
    description: str | None = None,
    question_set_id: str | None = None,
) -> Run:
    run_id = str(uuid.uuid4())

    def _tx(transaction):
        transaction.insert(
            T_RUNS,
            columns=["id", "name", "status", "agent_version", "description",
                     "question_set_id", "config_json",
                     "question_filter_json", "resume_count", "created_at"],
            values=[[run_id, name, "pending", agent_version, description,
                     question_set_id, JsonObject(config),
                     JsonObject(question_filter), 0, COMMIT_TS]],
        )

    get_eval_db().run_in_transaction(_tx)
    return get_run(run_id)


def get_run(run_id: str) -> Run | None:
    with get_eval_db().snapshot() as snapshot:
        for row in snapshot.read(T_RUNS, columns=Run.COLUMNS, keyset=_keyset([run_id])):
            return Run.from_row(row)
    return None


def list_runs(limit: int = 20) -> list[Run]:
    results: list[Run] = []
    with get_eval_db().snapshot() as snapshot:
        for row in snapshot.execute_sql(
            f"SELECT {', '.join(Run.COLUMNS)} FROM {T_RUNS} "
            f"ORDER BY created_at DESC LIMIT {limit}"
        ):
            results.append(Run.from_row(row))
    return results


def update_run(run_id: str, **fields) -> None:
    allowed = {"status", "started_at", "completed_at", "last_heartbeat",
               "question_ids_json", "total_questions", "resume_count"}
    update = {k: v for k, v in fields.items() if k in allowed}
    if not update:
        return

    def _tx(transaction):
        cols = list(update.keys())
        transaction.update(T_RUNS, columns=["id"] + cols,
                           values=[[run_id] + [update[c] for c in cols]])

    get_eval_db().run_in_transaction(_tx)


def find_stale_running_runs(stale_minutes: int) -> list[Run]:
    results: list[Run] = []
    with get_eval_db().snapshot() as snapshot:
        for row in snapshot.execute_sql(
            f"SELECT {', '.join(Run.COLUMNS)} FROM {T_RUNS} "
            "WHERE status = 'running' "
            f"AND last_heartbeat < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {stale_minutes} MINUTE) "
            "ORDER BY created_at"
        ):
            results.append(Run.from_row(row))
    return results


def find_pending_run() -> Run | None:
    with get_eval_db().snapshot() as snapshot:
        for row in snapshot.execute_sql(
            f"SELECT {', '.join(Run.COLUMNS)} FROM {T_RUNS} "
            "WHERE status = 'pending' ORDER BY created_at LIMIT 1"
        ):
            return Run.from_row(row)
    return None


def delete_run(run_id: str) -> None:
    def _tx(transaction):
        transaction.delete(T_RUNS, keyset=_keyset([run_id]))
    get_eval_db().run_in_transaction(_tx)


def get_run_progress(run_id: str) -> dict:
    with get_eval_db().snapshot() as snapshot:
        for row in snapshot.execute_sql(
            f"SELECT COUNT(*) FROM {T_RESULTS} WHERE run_id = @run_id",
            params={"run_id": run_id}, param_types={"run_id": param_types.STRING},
        ):
            completed = row[0]
    run = get_run(run_id)
    return {"completed": completed, "total": run.total_questions if run else 0}


# ─── Results ──────────────────────────────────────────────────────────────────

def insert_result(result: Result) -> None:
    def _tx(transaction):
        transaction.insert(
            T_RESULTS, columns=Result.COLUMNS,
            values=[[
                result.run_id, result.id, result.question_id, result.nlq_snapshot,
                result.tone_snapshot, result.outcome, result.sql_generated,
                result.agent_response, result.judge_verdict, result.judge_confidence,
                result.judge_reasoning, result.runtime_ms, result.route, result.join_count,
                result.error_message, result.started_at, result.completed_at,
            ]],
        )
    get_eval_db().run_in_transaction(_tx)


def list_results(
    run_id: str, outcome: str | None = None,
    table_name: str | None = None, task: str | None = None,
    page: int = 1, page_size: int = 50,
) -> list[Result]:
    db = get_eval_db()
    conditions = ["r.run_id = @run_id"]
    params: dict = {"run_id": run_id}
    pt: dict = {"run_id": param_types.STRING}

    if outcome:
        conditions.append("r.outcome = @outcome")
        params["outcome"] = outcome
        pt["outcome"] = param_types.STRING

    join_clause = ""
    if table_name or task:
        join_clause = f"JOIN {T_QUESTIONS} q ON r.question_id = q.id"
        if table_name:
            conditions.append("q.table_name = @table_name")
            params["table_name"] = table_name
            pt["table_name"] = param_types.STRING
        if task:
            conditions.append("q.task = @task")
            params["task"] = task
            pt["task"] = param_types.STRING

    cols = ", ".join(f"r.{c}" for c in Result.COLUMNS)
    offset = (page - 1) * page_size
    sql = (
        f"SELECT {cols} FROM {T_RESULTS} r {join_clause} "
        f"WHERE {' AND '.join(conditions)} ORDER BY r.completed_at DESC "
        f"LIMIT {page_size} OFFSET {offset}"
    )
    results: list[Result] = []
    with db.snapshot() as snapshot:
        for row in snapshot.execute_sql(sql, params=params, param_types=pt):
            results.append(Result.from_row(row))
    return results


def get_completed_question_ids(run_id: str) -> set[str]:
    ids: set[str] = set()
    with get_eval_db().snapshot() as snapshot:
        for row in snapshot.execute_sql(
            f"SELECT question_id FROM {T_RESULTS} WHERE run_id = @run_id",
            params={"run_id": run_id}, param_types={"run_id": param_types.STRING},
        ):
            ids.add(row[0])
    return ids


# ─── Review Items ─────────────────────────────────────────────────────────────

def insert_review_item(
    result_id: str, run_id: str, question_id: str,
    nlq_snapshot: str, judge_confidence: float, judge_reasoning: str | None,
) -> ReviewItem:
    item_id = str(uuid.uuid4())

    def _tx(transaction):
        transaction.insert(
            T_REVIEW_ITEMS,
            columns=["id", "result_id", "run_id", "question_id", "nlq_snapshot",
                     "judge_confidence", "judge_reasoning", "created_at"],
            values=[[item_id, result_id, run_id, question_id, nlq_snapshot,
                     judge_confidence, judge_reasoning, COMMIT_TS]],
        )

    get_eval_db().run_in_transaction(_tx)
    with get_eval_db().snapshot() as snapshot:
        for row in snapshot.read(T_REVIEW_ITEMS, columns=ReviewItem.COLUMNS, keyset=_keyset([item_id])):
            return ReviewItem.from_row(row)


def get_review_item(item_id: str) -> ReviewItem | None:
    with get_eval_db().snapshot() as snapshot:
        for row in snapshot.read(T_REVIEW_ITEMS, columns=ReviewItem.COLUMNS, keyset=_keyset([item_id])):
            return ReviewItem.from_row(row)
    return None


def list_review_items(
    run_id: str | None = None, pending_only: bool = True,
    page: int = 1, page_size: int = 50,
) -> list[ReviewItem]:
    conditions: list[str] = []
    params: dict = {}
    pt: dict = {}

    if pending_only:
        conditions.append("review_decision IS NULL")
    if run_id:
        conditions.append("run_id = @run_id")
        params["run_id"] = run_id
        pt["run_id"] = param_types.STRING

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    offset = (page - 1) * page_size
    sql = (
        f"SELECT {', '.join(ReviewItem.COLUMNS)} FROM {T_REVIEW_ITEMS} "
        f"{where} ORDER BY created_at DESC LIMIT {page_size} OFFSET {offset}"
    )
    results: list[ReviewItem] = []
    with get_eval_db().snapshot() as snapshot:
        for row in snapshot.execute_sql(sql, params=params or None, param_types=pt or None):
            results.append(ReviewItem.from_row(row))
    return results


def submit_review(item_id: str, decision: str, reviewer: str | None, notes: str | None) -> ReviewItem | None:
    def _tx(transaction):
        transaction.update(
            T_REVIEW_ITEMS,
            columns=["id", "review_decision", "reviewer", "review_notes", "reviewed_at"],
            values=[[item_id, decision, reviewer, notes, COMMIT_TS]],
        )
    get_eval_db().run_in_transaction(_tx)
    return get_review_item(item_id)


def get_review_stats() -> dict:
    stats = {"pending": 0, "confirmed_pass": 0, "override_fail": 0}
    with get_eval_db().snapshot() as snapshot:
        for row in snapshot.execute_sql(
            f"SELECT review_decision, COUNT(*) FROM {T_REVIEW_ITEMS} GROUP BY review_decision"
        ):
            key = row[0] if row[0] else "pending"
            stats[key] = row[1]
    return stats


# ─── Run Metrics ──────────────────────────────────────────────────────────────

def upsert_run_metrics(metrics: RunMetrics) -> None:
    def _tx(transaction):
        transaction.insert_or_update(
            T_RUN_METRICS,
            columns=["run_id", "total", "count_passed", "count_failed",
                     "count_rule_violation", "count_low_conf_pass",
                     "pct_passed", "pct_failed", "pct_rule_violation",
                     "avg_runtime_ms", "metrics_json", "computed_at"],
            values=[[
                metrics.run_id, metrics.total, metrics.count_passed,
                metrics.count_failed, metrics.count_rule_violation,
                metrics.count_low_conf_pass, metrics.pct_passed,
                metrics.pct_failed, metrics.pct_rule_violation,
                metrics.avg_runtime_ms,
                JsonObject(metrics.metrics_json) if metrics.metrics_json else None,
                COMMIT_TS,
            ]],
        )
    get_eval_db().run_in_transaction(_tx)


def get_run_metrics(run_id: str) -> RunMetrics | None:
    with get_eval_db().snapshot() as snapshot:
        for row in snapshot.read(T_RUN_METRICS, columns=RunMetrics.COLUMNS, keyset=_keyset([run_id])):
            return RunMetrics.from_row(row)
    return None


def get_metrics_for_runs(run_ids: list[str]) -> list[RunMetrics]:
    if not run_ids:
        return []
    placeholders = ", ".join(f"@id{i}" for i in range(len(run_ids)))
    params = {f"id{i}": v for i, v in enumerate(run_ids)}
    pt = {f"id{i}": param_types.STRING for i in range(len(run_ids))}
    results: list[RunMetrics] = []
    with get_eval_db().snapshot() as snapshot:
        for row in snapshot.execute_sql(
            f"SELECT {', '.join(RunMetrics.COLUMNS)} FROM {T_RUN_METRICS} "
            f"WHERE run_id IN ({placeholders})",
            params=params, param_types=pt,
        ):
            results.append(RunMetrics.from_row(row))
    return results


def get_timeseries_metrics(limit: int = 50) -> list[dict]:
    results: list[dict] = []
    with get_eval_db().snapshot() as snapshot:
        for row in snapshot.execute_sql(
            f"SELECT rm.run_id, r.name, r.completed_at, rm.pct_passed, rm.total "
            f"FROM {T_RUN_METRICS} rm JOIN {T_RUNS} r ON rm.run_id = r.id "
            f"WHERE r.status = 'completed' ORDER BY r.completed_at DESC LIMIT {limit}"
        ):
            results.append({
                "run_id": row[0], "name": row[1],
                "completed_at": _ts(row[2]),
                "pct_passed": row[3], "total": row[4],
            })
    return list(reversed(results))


def compute_and_store_metrics(run_id: str) -> RunMetrics:
    outcome_counts: dict[str, int] = {}
    runtimes: list[int] = []
    by_route: dict = {}
    by_table: dict = {}
    by_task: dict = {}
    by_joins: dict = {}
    by_tone: dict = {}

    with get_eval_db().snapshot() as snapshot:
        for row in snapshot.execute_sql(
            f"SELECT r.outcome, r.runtime_ms, r.route, r.join_count, "
            f"q.table_name, q.task, r.tone_snapshot "
            f"FROM {T_RESULTS} r JOIN {T_QUESTIONS} q ON r.question_id = q.id "
            "WHERE r.run_id = @run_id",
            params={"run_id": run_id}, param_types={"run_id": param_types.STRING},
        ):
            outcome, runtime_ms, route, join_count, table_name, task, tone_snapshot = row
            outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
            if runtime_ms:
                runtimes.append(runtime_ms)
            for gd, key in [
                (by_route, route or "unknown"),
                (by_table, table_name or "unknown"),
                (by_task, task or "unknown"),
                (by_joins, str(join_count) if join_count is not None else "unknown"),
                (by_tone, tone_snapshot or "unknown"),
            ]:
                if key not in gd:
                    gd[key] = {"total": 0, "passed": 0, "failed": 0,
                               "rule_violation": 0, "low_confidence_pass": 0, "runtimes": []}
                gd[key]["total"] += 1
                gd[key][outcome] = gd[key].get(outcome, 0) + 1
                if runtime_ms:
                    gd[key]["runtimes"].append(runtime_ms)

    total = sum(outcome_counts.values())

    def _summarize(gd: dict) -> dict:
        out = {}
        for k, v in gd.items():
            rt = v.pop("runtimes", [])
            v["avg_runtime_ms"] = round(sum(rt) / len(rt), 2) if rt else None
            out[k] = v
        return out

    metrics = RunMetrics(
        run_id=run_id, total=total,
        count_passed=outcome_counts.get("passed", 0),
        count_failed=outcome_counts.get("failed", 0),
        count_rule_violation=outcome_counts.get("rule_violation", 0),
        count_low_conf_pass=outcome_counts.get("low_confidence_pass", 0),
        pct_passed=round(outcome_counts.get("passed", 0) / total * 100, 2) if total else 0,
        pct_failed=round(outcome_counts.get("failed", 0) / total * 100, 2) if total else 0,
        pct_rule_violation=round(outcome_counts.get("rule_violation", 0) / total * 100, 2) if total else 0,
        avg_runtime_ms=round(sum(runtimes) / len(runtimes), 2) if runtimes else None,
        metrics_json={
            "by_route": _summarize(by_route), "by_table": _summarize(by_table),
            "by_task": _summarize(by_task), "by_joins": _summarize(by_joins),
            "by_tone": _summarize(by_tone),
        },
        computed_at=None,
    )
    upsert_run_metrics(metrics)
    return metrics
