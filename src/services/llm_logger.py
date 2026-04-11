"""Thread-local LLM call logger.

Usage in call sites (judge.py):
    from src.services import llm_logger
    ...
    llm_logger.log_call("judge", input_tokens=120, output_tokens=40, latency_ms=350)

Usage in orchestrator to attach run/question context:
    llm_logger.set_context(run_id="...", question_id="...")
    try:
        ...
    finally:
        llm_logger.clear_context()
"""
import logging
import threading
import uuid
from src.core.database import get_eval_db, T_LLM_CALL_LOGS

log = logging.getLogger(__name__)

_ctx = threading.local()

COMMIT_TS = "spanner.commit_timestamp()"


def set_context(run_id: str | None, question_id: str | None, model: str | None = None) -> None:
    _ctx.run_id = run_id
    _ctx.question_id = question_id
    _ctx.model = model


def clear_context() -> None:
    _ctx.run_id = None
    _ctx.question_id = None
    _ctx.model = None


def log_call(
    call_type: str,
    input_tokens: int | None,
    output_tokens: int | None,
    latency_ms: int,
) -> None:
    """Write one LLM call record to Spanner. Silently swallows errors so logging
    never interrupts evaluation."""
    try:
        run_id = getattr(_ctx, "run_id", None)
        question_id = getattr(_ctx, "question_id", None)
        model = getattr(_ctx, "model", None)
        total = (input_tokens or 0) + (output_tokens or 0) if (input_tokens or output_tokens) else None

        def _tx(transaction):
            transaction.insert(
                T_LLM_CALL_LOGS,
                columns=["id", "run_id", "question_id", "call_type", "model",
                         "input_tokens", "output_tokens", "total_tokens",
                         "latency_ms", "called_at"],
                values=[[
                    str(uuid.uuid4()), run_id, question_id, call_type, model,
                    input_tokens, output_tokens, total, latency_ms, COMMIT_TS,
                ]],
            )

        get_eval_db().run_in_transaction(_tx)
    except Exception as e:
        log.debug("LLM call logging failed (non-fatal): %s", e)
