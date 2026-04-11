"""Unit tests for the seeder service.

Mocks: spanner_source, spanner_eval (Spanner DB), judge, embedding.
Tests cover strata computation, needed logic, deduplication, dry-run, full seed, and HyDE retrieval.
"""
import pytest
from unittest.mock import MagicMock, patch, call
from src.services.seeder import Stratum, SeedReport, seed_all, get_strata_with_targets, _schema_to_text, _hyde_retrieve_examples, TONES


# ─── Stratum.needed property ─────────────────────────────────────────────────

class TestStratum:
    def test_needed_positive(self):
        s = Stratum(table_name="orders", task="aggregation", tone="neutral",
                    description="", current_count=3, target_count=7)
        assert s.needed == 4

    def test_needed_zero_when_at_target(self):
        s = Stratum(table_name="orders", task="aggregation", tone="neutral",
                    description="", current_count=7, target_count=7)
        assert s.needed == 0

    def test_needed_zero_when_over_target(self):
        s = Stratum(table_name="orders", task="aggregation", tone="casual",
                    description="", current_count=10, target_count=7)
        assert s.needed == 0

    def test_all_tones_represented(self):
        assert set(TONES) == {"casual", "neutral", "formal"}


# ─── SeedReport.to_dict ───────────────────────────────────────────────────────

class TestSeedReport:
    def test_to_dict_keys(self):
        report = SeedReport(
            strata_processed=2,
            questions_generated=10,
            questions_written=8,
            skipped_duplicate=2,
            strata_detail=[{"table_name": "orders", "task": "agg", "tone": "neutral"}],
        )
        d = report.to_dict()
        assert d["strata_processed"] == 2
        assert d["questions_generated"] == 10
        assert d["questions_written"] == 8
        assert d["skipped_duplicate"] == 2
        assert len(d["strata_detail"]) == 1


# ─── _schema_to_text ─────────────────────────────────────────────────────────

class TestSchemaToText:
    def test_basic_formatting(self):
        schema = MagicMock()
        schema.table_name = "orders"
        schema.description = "Contains all orders"
        schema.columns = [
            {"name": "id", "description": "Primary key", "type": "STRING"},
            {"name": "total", "description": "Order total", "type": "FLOAT64"},
        ]
        text = _schema_to_text(schema)
        assert "Table: orders" in text
        assert "Contains all orders" in text
        assert "id" in text
        assert "Primary key" in text

    def test_empty_columns(self):
        schema = MagicMock()
        schema.table_name = "empty_table"
        schema.description = "No columns"
        schema.columns = []
        text = _schema_to_text(schema)
        assert "empty_table" in text
        assert "Columns:" in text


# ─── _hyde_retrieve_examples ─────────────────────────────────────────────────

def _make_curriculum_entry(query_text, table_name="orders", task="aggregation"):
    entry = MagicMock()
    entry.query_text = query_text
    entry.table_name = table_name
    entry.task = task
    return entry


class TestHydeRetrieveExamples:
    def _patch_hyde(self, monkeypatch, *,
                    hypothetical="How many orders were placed last quarter?",
                    hyp_emb=None,
                    top_k_result=None,
                    agent_embs=None):
        cfg = MagicMock()
        cfg.leakage_embedding_threshold = 0.85
        monkeypatch.setattr("src.services.seeder.get_config", lambda: cfg)

        monkeypatch.setattr(
            "src.services.seeder.judge.generate_hypothetical_question",
            lambda *args, **kwargs: hypothetical,
        )
        monkeypatch.setattr(
            "src.services.seeder.embedding.embed_text",
            lambda text: hyp_emb or [0.5] * 768,
        )
        # Return 3 items: indices 0, 1, 2 with descending scores
        monkeypatch.setattr(
            "src.services.seeder.embedding.get_corpus_embeddings",
            lambda texts: [[float(i)] * 768 for i in range(len(texts))],
        )
        monkeypatch.setattr(
            "src.services.seeder.embedding.top_k_similar",
            lambda q, c, k: top_k_result or [(0, 0.9), (1, 0.8), (2, 0.7)],
        )
        monkeypatch.setattr(
            "src.services.seeder.embedding.find_max_similarity",
            lambda q, c: (0.1, 0),  # low similarity → not leaking
        )

    def test_returns_top_examples(self, monkeypatch):
        self._patch_hyde(monkeypatch)
        entries = [
            _make_curriculum_entry("Q1?"),
            _make_curriculum_entry("Q2?"),
            _make_curriculum_entry("Q3?"),
        ]
        result = _hyde_retrieve_examples(
            "orders", "aggregation", "neutral", "schema",
            entries, existing_nlqs=set(), agent_prompt_examples=[], top_k=2,
        )
        assert len(result) == 2
        assert result[0] == "Q1?"
        assert result[1] == "Q2?"

    def test_skips_existing_nlqs(self, monkeypatch):
        self._patch_hyde(monkeypatch)
        entries = [
            _make_curriculum_entry("Q1?"),
            _make_curriculum_entry("Q2?"),
            _make_curriculum_entry("Q3?"),
        ]
        # Q1 is already in the eval bank
        result = _hyde_retrieve_examples(
            "orders", "aggregation", "neutral", "schema",
            entries, existing_nlqs={"q1?"}, agent_prompt_examples=[], top_k=2,
        )
        assert "Q1?" not in result
        assert len(result) == 2

    def test_skips_agent_prompt_matches(self, monkeypatch):
        cfg = MagicMock()
        cfg.leakage_embedding_threshold = 0.85
        monkeypatch.setattr("src.services.seeder.get_config", lambda: cfg)
        monkeypatch.setattr(
            "src.services.seeder.judge.generate_hypothetical_question",
            lambda *a, **kw: "Hypothetical?",
        )
        monkeypatch.setattr(
            "src.services.seeder.embedding.embed_text",
            lambda t: [0.5] * 768,
        )
        monkeypatch.setattr(
            "src.services.seeder.embedding.get_corpus_embeddings",
            lambda texts: [[0.1] * 768 for _ in texts],
        )
        monkeypatch.setattr(
            "src.services.seeder.embedding.top_k_similar",
            lambda q, c, k: [(0, 0.9), (1, 0.8)],
        )
        # First curriculum entry has high similarity to agent prompts → skip
        sim_calls = []
        def fake_max_sim(q, c):
            sim_calls.append(True)
            return (0.95 if len(sim_calls) == 1 else 0.1, 0)
        monkeypatch.setattr("src.services.seeder.embedding.find_max_similarity", fake_max_sim)

        entries = [_make_curriculum_entry("Leaked?"), _make_curriculum_entry("Safe?")]
        result = _hyde_retrieve_examples(
            "orders", "aggregation", "neutral", "schema",
            entries, existing_nlqs=set(), agent_prompt_examples=["agent example"],
            top_k=2,
        )
        assert "Leaked?" not in result
        assert "Safe?" in result

    def test_empty_curriculum_returns_empty(self, monkeypatch):
        cfg = MagicMock()
        cfg.leakage_embedding_threshold = 0.85
        monkeypatch.setattr("src.services.seeder.get_config", lambda: cfg)
        monkeypatch.setattr(
            "src.services.seeder.judge.generate_hypothetical_question",
            lambda *a, **kw: "Q?",
        )
        monkeypatch.setattr("src.services.seeder.embedding.embed_text", lambda t: [0.1] * 768)
        result = _hyde_retrieve_examples(
            "orders", "aggregation", "neutral", "schema",
            [], existing_nlqs=set(), agent_prompt_examples=[], top_k=5,
        )
        assert result == []

    def test_hyde_generation_failure_returns_empty(self, monkeypatch):
        cfg = MagicMock()
        cfg.leakage_embedding_threshold = 0.85
        monkeypatch.setattr("src.services.seeder.get_config", lambda: cfg)
        monkeypatch.setattr(
            "src.services.seeder.judge.generate_hypothetical_question",
            lambda *a, **kw: (_ for _ in ()).throw(Exception("LLM down")),
        )
        entries = [_make_curriculum_entry("Q?")]
        result = _hyde_retrieve_examples(
            "orders", "aggregation", "neutral", "schema",
            entries, existing_nlqs=set(), agent_prompt_examples=[], top_k=3,
        )
        assert result == []


# ─── seed_all ─────────────────────────────────────────────────────────────────

def _make_schema(table_name, description="Test table"):
    schema = MagicMock()
    schema.table_name = table_name
    schema.description = description
    schema.columns = [{"name": "id", "description": "Primary key", "type": "STRING"}]
    return schema


def _patch_seed_dependencies(monkeypatch, *,
                              strata=None,
                              table_schemas=None,
                              curriculum_entries=None,
                              existing_nlqs=None,
                              generated_questions=None,
                              target_count=7):
    cfg = MagicMock()
    cfg.seeder_active_count = target_count
    cfg.agent_repo_path = None
    monkeypatch.setattr("src.services.seeder.get_config", lambda: cfg)

    if strata is None:
        strata = [
            Stratum("orders", "aggregation", "neutral", "", current_count=3, target_count=target_count),
        ]

    if table_schemas is None:
        table_schemas = [_make_schema("orders")]

    if curriculum_entries is None:
        curriculum_entries = [_make_curriculum_entry("Sample curriculum NLQ?")]

    if existing_nlqs is None:
        existing_nlqs = set()

    if generated_questions is None:
        generated_questions = [f"Generated question {i}?" for i in range(4)]

    monkeypatch.setattr("src.services.seeder.get_strata_with_targets", lambda: strata)
    monkeypatch.setattr(
        "src.services.seeder.spanner_source.get_all_table_schemas",
        lambda: table_schemas,
    )
    monkeypatch.setattr(
        "src.services.seeder.spanner_source.get_curriculum_entries",
        lambda: curriculum_entries,
    )

    mock_snapshot = MagicMock()
    mock_snapshot.__enter__ = lambda s: s
    mock_snapshot.__exit__ = MagicMock(return_value=False)
    mock_snapshot.execute_sql = MagicMock(return_value=[(nlq,) for nlq in existing_nlqs])
    mock_db = MagicMock()
    mock_db.snapshot = MagicMock(return_value=mock_snapshot)
    monkeypatch.setattr("src.services.seeder.get_eval_db", lambda: mock_db)

    # Stub out HyDE so it doesn't make real embedding calls
    monkeypatch.setattr(
        "src.services.seeder._hyde_retrieve_examples",
        lambda **kwargs: [],
    )

    generated = list(generated_questions)
    monkeypatch.setattr(
        "src.services.seeder.judge.generate_questions_for_stratum",
        lambda **kwargs: generated,
    )

    bulk_insert_calls = []
    monkeypatch.setattr(
        "src.services.seeder.spanner_eval.bulk_insert_questions",
        lambda rows: bulk_insert_calls.append(rows),
    )

    return bulk_insert_calls


class TestSeedAll:
    def test_dry_run_returns_report_without_writing(self, monkeypatch):
        bulk_calls = _patch_seed_dependencies(monkeypatch)
        report = seed_all(dry_run=True)
        assert isinstance(report, SeedReport)
        assert len(bulk_calls) == 0

    def test_dry_run_report_includes_proposed_questions(self, monkeypatch):
        generated = ["New question A?", "New question B?"]
        _patch_seed_dependencies(monkeypatch, generated_questions=generated)
        report = seed_all(dry_run=True)
        proposed = report.strata_detail[0]["proposed"]
        assert len(proposed) == 2
        assert "New question A?" in proposed

    def test_strata_detail_includes_tone(self, monkeypatch):
        strata = [Stratum("orders", "aggregation", "formal", "", current_count=5, target_count=7)]
        _patch_seed_dependencies(monkeypatch, strata=strata, generated_questions=["Q1?", "Q2?"])
        report = seed_all(dry_run=True)
        assert report.strata_detail[0]["tone"] == "formal"

    def test_execute_writes_to_spanner(self, monkeypatch):
        generated = ["New question A?", "New question B?"]
        bulk_calls = _patch_seed_dependencies(monkeypatch, generated_questions=generated)
        report = seed_all(dry_run=False)
        assert len(bulk_calls) == 1
        rows = bulk_calls[0]
        assert len(rows) == 2
        assert all(r["is_seeded"] is True for r in rows)
        assert all(r["table_name"] == "orders" for r in rows)
        assert all(r["tone"] == "neutral" for r in rows)

    def test_tone_written_to_spanner_row(self, monkeypatch):
        strata = [Stratum("orders", "aggregation", "casual", "", current_count=5, target_count=7)]
        bulk_calls = _patch_seed_dependencies(
            monkeypatch, strata=strata, generated_questions=["Casual Q?"]
        )
        seed_all(dry_run=False)
        assert bulk_calls[0][0]["tone"] == "casual"

    def test_deduplication_against_existing(self, monkeypatch):
        existing = {"new question a?"}
        generated = ["New question A?", "Brand new question B?"]
        bulk_calls = _patch_seed_dependencies(
            monkeypatch, generated_questions=generated, existing_nlqs=existing
        )
        report = seed_all(dry_run=False)
        rows = bulk_calls[0]
        assert len(rows) == 1
        assert rows[0]["nlq"] == "Brand new question B?"

    def test_deduplication_within_batch(self, monkeypatch):
        generated = ["Duplicate question?", "Duplicate question?", "Unique question?"]
        bulk_calls = _patch_seed_dependencies(monkeypatch, generated_questions=generated)
        report = seed_all(dry_run=False)
        rows = bulk_calls[0]
        nlqs = [r["nlq"] for r in rows]
        assert len(nlqs) == len(set(nlq.lower() for nlq in nlqs))

    def test_skipped_duplicate_counted(self, monkeypatch):
        existing = {"already here?"}
        generated = ["Already here?", "New one?"]
        _patch_seed_dependencies(monkeypatch, generated_questions=generated, existing_nlqs=existing)
        report = seed_all(dry_run=False)
        assert report.skipped_duplicate == 1

    def test_stratum_with_no_needed_skipped(self, monkeypatch):
        strata = [
            Stratum("orders", "aggregation", "neutral", "", current_count=7, target_count=7),
            Stratum("products", "filter", "neutral", "", current_count=2, target_count=7),
        ]
        generate_tracker = []
        bulk_calls = _patch_seed_dependencies(
            monkeypatch, strata=strata, generated_questions=["Q?"] * 5,
        )
        monkeypatch.setattr(
            "src.services.seeder.judge.generate_questions_for_stratum",
            lambda **kwargs: generate_tracker.append(kwargs["table_name"]) or ["Q?"] * 5,
        )
        report = seed_all(dry_run=False)
        assert generate_tracker == ["products"]
        assert report.strata_processed == 1

    def test_questions_marked_as_seeded_and_leakage_unchecked(self, monkeypatch):
        generated = ["New question?"]
        bulk_calls = _patch_seed_dependencies(monkeypatch, generated_questions=generated)
        seed_all(dry_run=False)
        row = bulk_calls[0][0]
        assert row["is_seeded"] is True
        assert row.get("leakage_checked") is not True

    def test_execute_dry_run_proposed_empty_after_execute(self, monkeypatch):
        generated = ["Q1?", "Q2?"]
        _patch_seed_dependencies(monkeypatch, generated_questions=generated)
        report = seed_all(dry_run=False)
        assert report.strata_detail[0]["proposed"] == []
