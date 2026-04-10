#!/usr/bin/env python3
"""End-to-end smoke test against real GCP services. Requires a valid .env file."""
import sys
import uuid
import logging
from pathlib import Path

# Add repo root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("smoke_test")

PASS = "✓"
FAIL = "✗"


def check(label: str, fn):
    try:
        fn()
        log.info(f"  {PASS}  {label}")
        return True
    except Exception as e:
        log.error(f"  {FAIL}  {label}: {e}")
        return False


def main():
    log.info("\n=== T2S Eval System — Smoke Test ===\n")
    results = []

    # 1. Spanner source: fetch schemas
    def test_spanner_source():
        from src.services.spanner_source import get_all_table_schemas
        schemas = get_all_table_schemas()
        assert len(schemas) >= 1, "Expected at least 1 table schema"

    results.append(check("Spanner source: fetch table schemas", test_spanner_source))

    # 2. Spanner eval: write + read + delete a test row
    def test_spanner_eval():
        from src.services import spanner_eval
        q = spanner_eval.create_question(
            nlq="Smoke test question — delete me?",
            table_name="_smoke_test",
            task="_smoke_test",
            status="active",
        )
        assert q.id, "Expected a UUID id"
        fetched = spanner_eval.get_question(q.id)
        assert fetched.nlq == q.nlq
        spanner_eval.soft_delete_question(q.id)

    results.append(check("Spanner eval: create/read/delete question", test_spanner_eval))

    # 3. Vertex AI embeddings
    def test_embeddings():
        from src.services.embedding import embed_text
        emb = embed_text("What are the total sales last month?")
        assert isinstance(emb, list) and len(emb) > 100, "Expected embedding vector"

    results.append(check("Vertex AI: embed text", test_embeddings))

    # 4. Gemini judge
    def test_judge():
        from src.services.judge import judge_result
        result = judge_result(
            nlq="What were total orders in January 2024?",
            sql="SELECT COUNT(*) FROM orders WHERE order_date >= '2024-01-01' AND order_date < '2024-02-01'",
            agent_response="There were 1,234 orders in January 2024.",
            business_rules_summary="The orders table stores all customer orders. Filter by order_date.",
        )
        assert result.verdict in ("pass", "fail")
        assert 0.0 <= result.confidence <= 1.0

    results.append(check("Gemini judge: verdict + confidence", test_judge))

    # 5. Leakage guard
    def test_leakage():
        from src.services import spanner_eval, leakage
        q = spanner_eval.create_question(
            nlq=f"Smoke test leakage question {uuid.uuid4()}?",
            table_name="_smoke_test",
            task="_smoke_test",
            status="active",
        )
        lc = leakage.run_leakage_check(q)
        assert lc.id, "Expected a leakage check id"
        spanner_eval.soft_delete_question(q.id)

    results.append(check("Leakage guard: run check + persist", test_leakage))

    # 6. ADK server
    def test_adk():
        from src.services import adk_client
        adk_client.start_server()
        try:
            resp = adk_client.send_nlq("How many orders were placed last month?")
            assert resp.error is None or resp.sql_generated, \
                f"Expected sql_generated or no error, got: {resp.error}"
        finally:
            adk_client.stop_server()

    results.append(check("ADK api_server: start + send NLQ + stop", test_adk))

    # 7. Full run (mock-friendly: creates run, invokes orchestrator)
    def test_full_run():
        from src.services import spanner_eval
        # Create a question that's already leakage-checked
        q = spanner_eval.create_question(
            nlq=f"Smoke test full run {uuid.uuid4()}?",
            table_name="_smoke_test",
            task="_smoke_test",
            status="active",
        )
        # Manually mark as leakage_checked so it's eligible
        spanner_eval.update_question(q.id, leakage_checked=True)

        run = spanner_eval.create_run(
            name="smoke-test-run",
            config={},
            question_filter={"statuses": ["active"]},
        )
        # Run synchronously (blocking)
        from src.services.orchestrator import start_run
        start_run(run.id)

        finished = spanner_eval.get_run(run.id)
        assert finished.status in ("completed", "failed"), \
            f"Expected completed/failed, got {finished.status}"

        results_list = spanner_eval.list_results(run.id)
        assert len(results_list) >= 1, "Expected at least one result"

        # Cleanup
        spanner_eval.soft_delete_question(q.id)
        spanner_eval.delete_run(run.id)

    results.append(check("Full run: create → execute → results persisted", test_full_run))

    # Summary
    passed = sum(results)
    total = len(results)
    log.info(f"\n{'='*40}")
    log.info(f"  {passed}/{total} checks passed")
    if passed < total:
        log.info("  Some checks failed. See errors above.")
        sys.exit(1)
    else:
        log.info("  All checks passed!")


if __name__ == "__main__":
    main()
