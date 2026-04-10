from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any


def _ts(val) -> str | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.isoformat()
    return str(val)


@dataclass
class Question:
    id: str
    nlq: str
    table_name: str
    task: str
    status: str
    is_seeded: bool
    leakage_checked: bool
    leakage_check_id: str | None
    notes: str | None
    created_at: Any
    updated_at: Any

    COLUMNS = ["id", "nlq", "table_name", "task", "status", "is_seeded",
               "leakage_checked", "leakage_check_id", "notes", "created_at", "updated_at"]

    @classmethod
    def from_row(cls, row) -> Question:
        return cls(
            id=row[0], nlq=row[1], table_name=row[2], task=row[3],
            status=row[4], is_seeded=bool(row[5]), leakage_checked=bool(row[6]),
            leakage_check_id=row[7], notes=row[8], created_at=row[9], updated_at=row[10],
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["created_at"] = _ts(self.created_at)
        d["updated_at"] = _ts(self.updated_at)
        return d


@dataclass
class LeakageCheck:
    id: str
    question_id: str
    embedding_flagged: bool
    embedding_max_sim: float | None
    embedding_match_text: str | None
    llm_flagged: bool
    llm_reasoning: str | None
    overall_passed: bool
    checked_at: Any

    COLUMNS = ["id", "question_id", "embedding_flagged", "embedding_max_sim",
               "embedding_match_text", "llm_flagged", "llm_reasoning",
               "overall_passed", "checked_at"]

    @classmethod
    def from_row(cls, row) -> LeakageCheck:
        return cls(
            id=row[0], question_id=row[1], embedding_flagged=bool(row[2]),
            embedding_max_sim=row[3], embedding_match_text=row[4],
            llm_flagged=bool(row[5]), llm_reasoning=row[6],
            overall_passed=bool(row[7]), checked_at=row[8],
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["checked_at"] = _ts(self.checked_at)
        return d


@dataclass
class Run:
    id: str
    name: str | None
    status: str
    started_at: Any
    completed_at: Any
    last_heartbeat: Any
    question_ids_json: list | None
    config_json: dict | None
    question_filter_json: dict | None
    total_questions: int | None
    resume_count: int
    created_at: Any

    COLUMNS = ["id", "name", "status", "started_at", "completed_at",
               "last_heartbeat", "question_ids_json", "config_json",
               "question_filter_json", "total_questions", "resume_count", "created_at"]

    @classmethod
    def from_row(cls, row) -> Run:
        return cls(
            id=row[0], name=row[1], status=row[2], started_at=row[3],
            completed_at=row[4], last_heartbeat=row[5], question_ids_json=row[6],
            config_json=row[7], question_filter_json=row[8], total_questions=row[9],
            resume_count=row[10] or 0, created_at=row[11],
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "status": self.status,
            "started_at": _ts(self.started_at), "completed_at": _ts(self.completed_at),
            "last_heartbeat": _ts(self.last_heartbeat),
            "question_ids_json": self.question_ids_json,
            "config_json": self.config_json,
            "question_filter_json": self.question_filter_json,
            "total_questions": self.total_questions,
            "resume_count": self.resume_count,
            "created_at": _ts(self.created_at),
        }


@dataclass
class Result:
    run_id: str
    id: str
    question_id: str
    nlq_snapshot: str
    outcome: str
    sql_generated: str | None
    agent_response: str | None
    judge_verdict: str | None
    judge_confidence: float | None
    judge_reasoning: str | None
    runtime_ms: int | None
    route: str | None
    join_count: int | None
    error_message: str | None
    started_at: Any
    completed_at: Any

    COLUMNS = ["run_id", "id", "question_id", "nlq_snapshot", "outcome",
               "sql_generated", "agent_response", "judge_verdict",
               "judge_confidence", "judge_reasoning", "runtime_ms", "route",
               "join_count", "error_message", "started_at", "completed_at"]

    @classmethod
    def from_row(cls, row) -> Result:
        return cls(
            run_id=row[0], id=row[1], question_id=row[2], nlq_snapshot=row[3],
            outcome=row[4], sql_generated=row[5], agent_response=row[6],
            judge_verdict=row[7], judge_confidence=row[8], judge_reasoning=row[9],
            runtime_ms=row[10], route=row[11], join_count=row[12],
            error_message=row[13], started_at=row[14], completed_at=row[15],
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["started_at"] = _ts(self.started_at)
        d["completed_at"] = _ts(self.completed_at)
        return d


@dataclass
class ReviewItem:
    id: str
    result_id: str
    run_id: str
    question_id: str
    nlq_snapshot: str
    judge_confidence: float
    judge_reasoning: str | None
    reviewer: str | None
    review_decision: str | None
    review_notes: str | None
    created_at: Any
    reviewed_at: Any

    COLUMNS = ["id", "result_id", "run_id", "question_id", "nlq_snapshot",
               "judge_confidence", "judge_reasoning", "reviewer",
               "review_decision", "review_notes", "created_at", "reviewed_at"]

    @classmethod
    def from_row(cls, row) -> ReviewItem:
        return cls(
            id=row[0], result_id=row[1], run_id=row[2], question_id=row[3],
            nlq_snapshot=row[4], judge_confidence=row[5], judge_reasoning=row[6],
            reviewer=row[7], review_decision=row[8], review_notes=row[9],
            created_at=row[10], reviewed_at=row[11],
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["created_at"] = _ts(self.created_at)
        d["reviewed_at"] = _ts(self.reviewed_at)
        return d


@dataclass
class RunMetrics:
    run_id: str
    total: int | None
    count_passed: int | None
    count_failed: int | None
    count_rule_violation: int | None
    count_low_conf_pass: int | None
    pct_passed: float | None
    pct_failed: float | None
    pct_rule_violation: float | None
    avg_runtime_ms: float | None
    metrics_json: dict | None
    computed_at: Any

    COLUMNS = ["run_id", "total", "count_passed", "count_failed",
               "count_rule_violation", "count_low_conf_pass", "pct_passed",
               "pct_failed", "pct_rule_violation", "avg_runtime_ms",
               "metrics_json", "computed_at"]

    @classmethod
    def from_row(cls, row) -> RunMetrics:
        return cls(
            run_id=row[0], total=row[1], count_passed=row[2],
            count_failed=row[3], count_rule_violation=row[4],
            count_low_conf_pass=row[5], pct_passed=row[6],
            pct_failed=row[7], pct_rule_violation=row[8],
            avg_runtime_ms=row[9], metrics_json=row[10], computed_at=row[11],
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["computed_at"] = _ts(self.computed_at)
        return d
