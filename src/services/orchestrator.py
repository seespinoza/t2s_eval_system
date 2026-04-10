"""Run lifecycle: startup/resume detection, parallel eval, metrics, teardown."""
import threading
import uuid
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from google.cloud import spanner as _spanner
from google.cloud.spanner_v1.data_types import JsonObject

COMMIT_TIMESTAMP = _spanner.COMMIT_TIMESTAMP

from src.config.settings import get_config
from src.core.models import Question, Result
from src.services import adk_client, judge, spanner_eval
from src.services.spanner_source import get_all_table_schemas
from src.utils.sql_parser import count_joins, extract_table_names

log = logging.getLogger(__name__)

_cancel_events: dict[str, threading.Event] = {}


# ─── Business rules summary (cached per process) ─────────────────────────────

_business_rules_cache: str | None = None


def _get_business_rules_summary() -> str:
    global _business_rules_cache
    if _business_rules_cache is None:
        schemas = get_all_table_schemas()
        lines: list[str] = []
        for s in schemas:
            lines.append(f"Table: {s.table_name} — {s.description}")
            for col in s.columns[:10]:  # cap to avoid context overflow
                lines.append(f"  {col.get('name', '')}: {col.get('description', '')}")
        _business_rules_cache = "\n".join(lines)[:8000]  # hard cap
    return _business_rules_cache


# ─── Heartbeat ────────────────────────────────────────────────────────────────

def _heartbeat_loop(run_id: str, interval: int, stop_event: threading.Event) -> None:
    while not stop_event.wait(interval):
        try:
            spanner_eval.update_run(run_id, last_heartbeat=COMMIT_TIMESTAMP)
        except Exception as e:
            log.warning("Heartbeat failed for run %s: %s", run_id, e)


# ─── Per-question evaluation ─────────────────────────────────────────────────

def _evaluate_question(
    run_id: str,
    question: Question,
    cfg,
    business_rules: str,
    cancel_event: threading.Event,
) -> Result | None:
    if cancel_event.is_set():
        return None

    result_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)

    adk_resp = adk_client.send_nlq(question.nlq)
    completed_at = datetime.now(timezone.utc)

    if adk_resp.error or not adk_resp.sql_generated:
        return Result(
            run_id=run_id, id=result_id, question_id=question.id,
            nlq_snapshot=question.nlq, outcome="failed",
            sql_generated=None, agent_response=adk_resp.agent_response,
            judge_verdict=None, judge_confidence=None, judge_reasoning=None,
            runtime_ms=adk_resp.runtime_ms, route=adk_resp.route,
            join_count=0, error_message=adk_resp.error,
            started_at=started_at, completed_at=completed_at,
        )

    join_count = count_joins(adk_resp.sql_generated)

    try:
        judge_result = judge.judge_result(
            nlq=question.nlq,
            sql=adk_resp.sql_generated,
            agent_response=adk_resp.agent_response or "",
            business_rules_summary=business_rules,
        )
    except Exception as e:
        log.error("Judge failed for question %s: %s", question.id, e)
        judge_result = judge.JudgeResult(verdict="fail", confidence=0.0, reasoning=str(e))

    threshold = cfg.judge_confidence_threshold
    if judge_result.verdict == "fail":
        outcome = "rule_violation"
    elif judge_result.confidence >= threshold:
        outcome = "passed"
    else:
        outcome = "low_confidence_pass"

    return Result(
        run_id=run_id, id=result_id, question_id=question.id,
        nlq_snapshot=question.nlq, outcome=outcome,
        sql_generated=adk_resp.sql_generated,
        agent_response=adk_resp.agent_response,
        judge_verdict=judge_result.verdict,
        judge_confidence=judge_result.confidence,
        judge_reasoning=judge_result.reasoning,
        runtime_ms=adk_resp.runtime_ms,
        route=adk_resp.route,
        join_count=join_count,
        error_message=None,
        started_at=started_at,
        completed_at=completed_at,
    )


def _write_result(result: Result) -> None:
    spanner_eval.insert_result(result)
    if result.outcome == "low_confidence_pass":
        spanner_eval.insert_review_item(
            result_id=result.id,
            run_id=result.run_id,
            question_id=result.question_id,
            nlq_snapshot=result.nlq_snapshot,
            judge_confidence=result.judge_confidence,
            judge_reasoning=result.judge_reasoning,
        )


# ─── Main orchestration ───────────────────────────────────────────────────────

def start_run(run_id: str) -> None:
    """Full run lifecycle. Called in a background thread by the Flask API,
    or directly by the Cloud Run Job runner/main.py."""
    cfg = get_config()
    cancel_event = threading.Event()
    _cancel_events[run_id] = cancel_event

    run = spanner_eval.get_run(run_id)
    if run is None:
        log.error("Run %s not found", run_id)
        return

    # Determine if this is a resume
    is_resume = run.question_ids_json is not None
    stop_heartbeat = threading.Event()  # initialized here so finally block can always reference it

    try:
        if is_resume:
            all_ids: list[str] = run.question_ids_json
            completed_ids = spanner_eval.get_completed_question_ids(run_id)
            remaining_ids = [qid for qid in all_ids if qid not in completed_ids]
            log.info("Resuming run %s — %d/%d questions remaining",
                     run_id, len(remaining_ids), len(all_ids))

            # Fetch question objects for remaining IDs
            questions: list[Question] = []
            for qid in remaining_ids:
                q = spanner_eval.get_question(qid)
                if q:
                    questions.append(q)

            new_resume_count = (run.resume_count or 0) + 1
            spanner_eval.update_run(run_id, status="running", resume_count=new_resume_count)

        else:
            # Fresh start: load eligible questions
            filter_cfg = run.question_filter_json or {}
            statuses = filter_cfg.get("statuses", ["active", "monitoring"])

            all_questions: list[Question] = []
            for status in statuses:
                all_questions.extend(spanner_eval.list_questions(
                    status=status, leakage_checked=True,
                    page=1, page_size=10000,
                ))

            if not all_questions:
                spanner_eval.update_run(run_id, status="failed")
                log.error("Run %s has no eligible questions", run_id)
                return

            question_ids = [q.id for q in all_questions]
            spanner_eval.update_run(
                run_id,
                status="running",
                started_at=datetime.now(timezone.utc),
                total_questions=len(all_questions),
                question_ids_json=JsonObject(question_ids),
            )
            questions = all_questions
            log.info("Starting run %s with %d questions", run_id, len(questions))

        # Start heartbeat
        hb_thread = threading.Thread(
            target=_heartbeat_loop,
            args=(run_id, cfg.heartbeat_interval_seconds, stop_heartbeat),
            daemon=True,
        )
        hb_thread.start()

        # Start ADK server
        adk_client.start_server()
        business_rules = _get_business_rules_summary()

        # Parallel execution
        with ThreadPoolExecutor(max_workers=cfg.run_concurrency) as executor:
            futures = {
                executor.submit(
                    _evaluate_question, run_id, q, cfg, business_rules, cancel_event
                ): q
                for q in questions
            }
            for future in as_completed(futures):
                if cancel_event.is_set():
                    break
                result = future.result()
                if result is not None:
                    try:
                        _write_result(result)
                    except Exception as e:
                        log.error("Failed to write result for question %s: %s",
                                  futures[future].id, e)

        # Compute and store metrics
        spanner_eval.compute_and_store_metrics(run_id)
        spanner_eval.update_run(run_id, status="completed",
                                completed_at=datetime.now(timezone.utc))
        log.info("Run %s completed", run_id)

    except Exception as e:
        log.exception("Run %s failed: %s", run_id, e)
        spanner_eval.update_run(run_id, status="failed")
    finally:
        stop_heartbeat.set()
        adk_client.stop_server()
        _cancel_events.pop(run_id, None)


def cancel_run(run_id: str) -> bool:
    event = _cancel_events.get(run_id)
    if event:
        event.set()
        spanner_eval.update_run(run_id, status="cancelled")
        return True
    return False
