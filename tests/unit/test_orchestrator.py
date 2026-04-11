"""Unit tests for the run orchestrator.

Mocks: ADK client, Spanner eval, judge, and spanner_source.
Tests cover all outcome branches, ReviewItem creation, and resume logic.
"""
import threading
import uuid
import pytest
from unittest.mock import patch, MagicMock, call
from datetime import datetime, timezone

from src.core.models import Question, Result, Run
from src.services import orchestrator
from src.services.judge import JudgeResult


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_question(id=None, nlq="How many orders?", tone="neutral") -> Question:
    return Question(
        id=id or str(uuid.uuid4()),
        nlq=nlq,
        table_name="orders",
        task="aggregation",
        tone=tone,
        status="active",
        is_seeded=False,
        leakage_checked=True,
        leakage_check_id=None,
        notes=None,
        created_at=None,
        updated_at=None,
    )


def _make_run(id=None, status="pending", question_ids_json=None, resume_count=0) -> Run:
    return Run(
        id=id or str(uuid.uuid4()),
        name="test-run",
        status=status,
        started_at=None,
        completed_at=None,
        last_heartbeat=None,
        question_ids_json=question_ids_json,
        config_json=None,
        question_filter_json=None,
        total_questions=None,
        resume_count=resume_count,
        created_at=None,
    )


def _make_adk_response(sql="SELECT COUNT(*) FROM orders", error=None, route="sql_agent"):
    resp = MagicMock()
    resp.sql_generated = sql
    resp.agent_response = "Here is your result."
    resp.error = error
    resp.route = route
    resp.runtime_ms = 250
    return resp


# ─── _evaluate_question outcome mapping ──────────────────────────────────────

class TestEvaluateQuestion:
    def _setup(self, monkeypatch, adk_resp=None, judge_resp=None, threshold=0.75):
        cfg = MagicMock()
        cfg.judge_confidence_threshold = threshold

        if adk_resp is None:
            adk_resp = _make_adk_response()
        monkeypatch.setattr("src.services.orchestrator.adk_client.send_nlq", lambda nlq: adk_resp)

        if judge_resp:
            monkeypatch.setattr(
                "src.services.orchestrator.judge.judge_result",
                lambda **kwargs: judge_resp,
            )

        return cfg

    def test_adk_error_yields_failed(self, monkeypatch):
        adk_resp = _make_adk_response(sql=None, error="Connection refused")
        cfg = self._setup(monkeypatch, adk_resp=adk_resp)

        q = _make_question()
        result = orchestrator._evaluate_question("run-1", q, cfg, "", threading.Event())
        assert result.outcome == "failed"
        assert result.error_message == "Connection refused"
        assert result.sql_generated is None

    def test_no_sql_generated_yields_failed(self, monkeypatch):
        adk_resp = _make_adk_response(sql=None, error=None)
        cfg = self._setup(monkeypatch, adk_resp=adk_resp)

        q = _make_question()
        result = orchestrator._evaluate_question("run-1", q, cfg, "", threading.Event())
        assert result.outcome == "failed"

    def test_judge_fail_yields_rule_violation(self, monkeypatch):
        judge_resp = JudgeResult(verdict="fail", confidence=0.1, reasoning="Rule broken.")
        cfg = self._setup(monkeypatch, judge_resp=judge_resp)

        q = _make_question()
        result = orchestrator._evaluate_question("run-1", q, cfg, "", threading.Event())
        assert result.outcome == "rule_violation"
        assert result.judge_verdict == "fail"

    def test_judge_pass_high_confidence_yields_passed(self, monkeypatch):
        judge_resp = JudgeResult(verdict="pass", confidence=0.9, reasoning="Correct.")
        cfg = self._setup(monkeypatch, judge_resp=judge_resp, threshold=0.75)

        q = _make_question()
        result = orchestrator._evaluate_question("run-1", q, cfg, "", threading.Event())
        assert result.outcome == "passed"

    def test_judge_pass_at_threshold_yields_passed(self, monkeypatch):
        judge_resp = JudgeResult(verdict="pass", confidence=0.75, reasoning="Borderline.")
        cfg = self._setup(monkeypatch, judge_resp=judge_resp, threshold=0.75)

        q = _make_question()
        result = orchestrator._evaluate_question("run-1", q, cfg, "", threading.Event())
        assert result.outcome == "passed"

    def test_judge_pass_below_threshold_yields_low_confidence_pass(self, monkeypatch):
        judge_resp = JudgeResult(verdict="pass", confidence=0.6, reasoning="Uncertain.")
        cfg = self._setup(monkeypatch, judge_resp=judge_resp, threshold=0.75)

        q = _make_question()
        result = orchestrator._evaluate_question("run-1", q, cfg, "", threading.Event())
        assert result.outcome == "low_confidence_pass"
        assert result.judge_confidence == 0.6

    def test_cancel_event_returns_none(self, monkeypatch):
        cfg = self._setup(monkeypatch)

        cancel = threading.Event()
        cancel.set()
        q = _make_question()
        result = orchestrator._evaluate_question("run-1", q, cfg, "", cancel)
        assert result is None

    def test_judge_exception_yields_rule_violation(self, monkeypatch):
        adk_resp = _make_adk_response(sql="SELECT 1")
        cfg = self._setup(monkeypatch, adk_resp=adk_resp, threshold=0.75)
        monkeypatch.setattr(
            "src.services.orchestrator.judge.judge_result",
            lambda **kwargs: (_ for _ in ()).throw(Exception("Judge API down")),
        )

        q = _make_question()
        result = orchestrator._evaluate_question("run-1", q, cfg, "", threading.Event())
        assert result.outcome == "rule_violation"

    def test_result_has_correct_metadata(self, monkeypatch):
        sql = "SELECT COUNT(*) FROM orders WHERE status = 'shipped'"
        adk_resp = _make_adk_response(sql=sql, route="aggregation_agent")
        judge_resp = JudgeResult(verdict="pass", confidence=0.88, reasoning="Good.")
        cfg = self._setup(monkeypatch, adk_resp=adk_resp, judge_resp=judge_resp)

        q = _make_question(id="q-abc", nlq="How many shipped orders?")
        result = orchestrator._evaluate_question("run-99", q, cfg, "", threading.Event())

        assert result.run_id == "run-99"
        assert result.question_id == "q-abc"
        assert result.nlq_snapshot == "How many shipped orders?"
        assert result.sql_generated == sql
        assert result.route == "aggregation_agent"
        assert result.join_count == 0


# ─── _write_result: ReviewItem creation ──────────────────────────────────────

class TestWriteResult:
    def _make_result(self, outcome, confidence=0.9) -> Result:
        return Result(
            run_id="run-1", id="res-1", question_id="q-1",
            nlq_snapshot="Test?", tone_snapshot="neutral", outcome=outcome,
            sql_generated="SELECT 1", agent_response="ok",
            judge_verdict="pass", judge_confidence=confidence,
            judge_reasoning="reason", runtime_ms=100, route="r",
            join_count=0, error_message=None,
            started_at=None, completed_at=None,
        )

    def test_passed_result_no_review_item(self, monkeypatch):
        insert_result = MagicMock()
        insert_review = MagicMock()
        monkeypatch.setattr("src.services.orchestrator.spanner_eval.insert_result", insert_result)
        monkeypatch.setattr("src.services.orchestrator.spanner_eval.insert_review_item", insert_review)

        orchestrator._write_result(self._make_result("passed"))
        insert_result.assert_called_once()
        insert_review.assert_not_called()

    def test_rule_violation_no_review_item(self, monkeypatch):
        insert_result = MagicMock()
        insert_review = MagicMock()
        monkeypatch.setattr("src.services.orchestrator.spanner_eval.insert_result", insert_result)
        monkeypatch.setattr("src.services.orchestrator.spanner_eval.insert_review_item", insert_review)

        orchestrator._write_result(self._make_result("rule_violation"))
        insert_review.assert_not_called()

    def test_failed_no_review_item(self, monkeypatch):
        insert_result = MagicMock()
        insert_review = MagicMock()
        monkeypatch.setattr("src.services.orchestrator.spanner_eval.insert_result", insert_result)
        monkeypatch.setattr("src.services.orchestrator.spanner_eval.insert_review_item", insert_review)

        orchestrator._write_result(self._make_result("failed"))
        insert_review.assert_not_called()

    def test_low_confidence_pass_creates_review_item(self, monkeypatch):
        insert_result = MagicMock()
        insert_review = MagicMock()
        monkeypatch.setattr("src.services.orchestrator.spanner_eval.insert_result", insert_result)
        monkeypatch.setattr("src.services.orchestrator.spanner_eval.insert_review_item", insert_review)

        result = self._make_result("low_confidence_pass", confidence=0.62)
        orchestrator._write_result(result)

        insert_result.assert_called_once()
        insert_review.assert_called_once()
        kwargs = insert_review.call_args.kwargs
        assert kwargs["result_id"] == "res-1"
        assert kwargs["run_id"] == "run-1"
        assert kwargs["question_id"] == "q-1"
        assert kwargs["judge_confidence"] == 0.62


# ─── start_run: fresh start vs resume ────────────────────────────────────────

class TestStartRun:
    def _patch_orchestrator(self, monkeypatch, run, questions,
                             completed_ids=None, judge_resp=None):
        cfg = MagicMock()
        cfg.judge_confidence_threshold = 0.75
        cfg.run_concurrency = 1
        cfg.heartbeat_interval_seconds = 9999  # prevent actual heartbeat firing
        monkeypatch.setattr("src.services.orchestrator.get_config", lambda: cfg)

        monkeypatch.setattr("src.services.orchestrator.spanner_eval.get_run", lambda id: run)
        monkeypatch.setattr(
            "src.services.orchestrator.spanner_eval.list_questions",
            lambda **kwargs: questions,
        )
        monkeypatch.setattr(
            "src.services.orchestrator.spanner_eval.get_question",
            lambda id: next((q for q in questions if q.id == id), None),
        )
        monkeypatch.setattr(
            "src.services.orchestrator.spanner_eval.get_completed_question_ids",
            lambda run_id: set(completed_ids or []),
        )

        update_calls = []
        monkeypatch.setattr(
            "src.services.orchestrator.spanner_eval.update_run",
            lambda run_id, **kwargs: update_calls.append(kwargs),
        )
        monkeypatch.setattr("src.services.orchestrator.spanner_eval.insert_result", MagicMock())
        monkeypatch.setattr("src.services.orchestrator.spanner_eval.insert_review_item", MagicMock())
        monkeypatch.setattr("src.services.orchestrator.spanner_eval.compute_and_store_metrics", MagicMock())

        adk_resp = _make_adk_response()
        monkeypatch.setattr("src.services.orchestrator.adk_client.send_nlq", lambda nlq: adk_resp)
        monkeypatch.setattr("src.services.orchestrator.adk_client.start_server", MagicMock())
        monkeypatch.setattr("src.services.orchestrator.adk_client.stop_server", MagicMock())

        if judge_resp is None:
            judge_resp = JudgeResult(verdict="pass", confidence=0.9, reasoning="ok")
        monkeypatch.setattr(
            "src.services.orchestrator.judge.judge_result",
            lambda **kwargs: judge_resp,
        )
        monkeypatch.setattr(
            "src.services.orchestrator.get_all_table_schemas",
            lambda: [],
        )

        return update_calls

    def test_run_not_found_returns_early(self, monkeypatch):
        cfg = MagicMock()
        monkeypatch.setattr("src.services.orchestrator.get_config", lambda: cfg)
        monkeypatch.setattr("src.services.orchestrator.spanner_eval.get_run", lambda id: None)
        # Should not raise
        orchestrator.start_run("nonexistent-run")

    def test_no_eligible_questions_marks_failed(self, monkeypatch):
        run = _make_run(id="r-1")
        update_calls = self._patch_orchestrator(monkeypatch, run, questions=[])
        monkeypatch.setattr(
            "src.services.orchestrator.spanner_eval.list_questions",
            lambda **kwargs: [],
        )

        orchestrator.start_run("r-1")
        statuses = [c.get("status") for c in update_calls]
        assert "failed" in statuses

    def test_fresh_run_snapshots_question_ids(self, monkeypatch):
        q = _make_question(id="q-fresh")
        run = _make_run(id="r-fresh", question_ids_json=None)
        update_calls = self._patch_orchestrator(monkeypatch, run, questions=[q])

        orchestrator.start_run("r-fresh")
        # One of the update_calls should include question_ids_json
        snapshot_calls = [c for c in update_calls if "question_ids_json" in c]
        assert len(snapshot_calls) == 1

    def test_fresh_run_completes_successfully(self, monkeypatch):
        q = _make_question(id="q-1")
        run = _make_run(id="r-1", question_ids_json=None)
        update_calls = self._patch_orchestrator(monkeypatch, run, questions=[q])

        orchestrator.start_run("r-1")
        statuses = [c.get("status") for c in update_calls if "status" in c]
        assert "completed" in statuses

    def test_resume_skips_completed_questions(self, monkeypatch):
        q1 = _make_question(id="q-1")
        q2 = _make_question(id="q-2")
        run = _make_run(id="r-resume", question_ids_json=["q-1", "q-2"], resume_count=0)
        # q-1 already completed
        update_calls = self._patch_orchestrator(
            monkeypatch, run, questions=[q1, q2], completed_ids=["q-1"]
        )

        send_calls = []
        monkeypatch.setattr(
            "src.services.orchestrator.adk_client.send_nlq",
            lambda nlq: send_calls.append(nlq) or _make_adk_response(),
        )

        orchestrator.start_run("r-resume")

        # Only q-2 should have been evaluated
        assert len(send_calls) == 1
        assert q2.nlq in send_calls

    def test_resume_increments_resume_count(self, monkeypatch):
        q = _make_question(id="q-r")
        run = _make_run(id="r-rc", question_ids_json=["q-r"], resume_count=2)
        update_calls = self._patch_orchestrator(monkeypatch, run, questions=[q])

        orchestrator.start_run("r-rc")
        resume_updates = [c for c in update_calls if "resume_count" in c]
        assert len(resume_updates) == 1
        assert resume_updates[0]["resume_count"] == 3
