"""Unit tests for the seeder service.

Mocks: spanner_source, spanner_eval (Spanner DB), judge.
Tests cover strata computation, needed logic, deduplication, dry-run, and full seed.
"""
import pytest
from unittest.mock import MagicMock, patch, call
from src.services.seeder import Stratum, SeedReport, seed_all, get_strata_with_targets, _schema_to_text


# ─── Stratum.needed property ─────────────────────────────────────────────────

class TestStratum:
    def test_needed_positive(self):
        s = Stratum(table_name="orders", task="aggregation", description="",
                    current_count=3, target_count=7)
        assert s.needed == 4

    def test_needed_zero_when_at_target(self):
        s = Stratum(table_name="orders", task="aggregation", description="",
                    current_count=7, target_count=7)
        assert s.needed == 0

    def test_needed_zero_when_over_target(self):
        s = Stratum(table_name="orders", task="aggregation", description="",
                    current_count=10, target_count=7)
        assert s.needed == 0


# ─── SeedReport.to_dict ───────────────────────────────────────────────────────

class TestSeedReport:
    def test_to_dict_keys(self):
        report = SeedReport(
            strata_processed=2,
            questions_generated=10,
            questions_written=8,
            skipped_duplicate=2,
            strata_detail=[{"table_name": "orders", "task": "agg"}],
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
        assert "total" in text

    def test_empty_columns(self):
        schema = MagicMock()
        schema.table_name = "empty_table"
        schema.description = "No columns"
        schema.columns = []
        text = _schema_to_text(schema)
        assert "empty_table" in text
        assert "Columns:" in text


# ─── seed_all ─────────────────────────────────────────────────────────────────

def _make_schema(table_name, description="Test table"):
    schema = MagicMock()
    schema.table_name = table_name
    schema.description = description
    schema.columns = [{"name": "id", "description": "Primary key", "type": "STRING"}]
    return schema


def _make_curriculum_entry(table_name, query_text):
    entry = MagicMock()
    entry.table_name = table_name
    entry.query_text = query_text
    return entry


def _patch_seed_dependencies(monkeypatch, *,
                              strata=None,
                              table_schemas=None,
                              curriculum_entries=None,
                              existing_nlqs=None,
                              generated_questions=None,
                              target_count=7):
    cfg = MagicMock()
    cfg.seeder_active_count = target_count
    monkeypatch.setattr("src.services.seeder.get_config", lambda: cfg)

    if strata is None:
        strata = [
            Stratum("orders", "aggregation", "Count queries", current_count=3, target_count=target_count),
        ]

    if table_schemas is None:
        table_schemas = [_make_schema("orders")]

    if curriculum_entries is None:
        curriculum_entries = [_make_curriculum_entry("orders", "Sample curriculum NLQ?")]

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

    # Mock the eval DB snapshot for existing NLQs
    mock_snapshot = MagicMock()
    mock_snapshot.__enter__ = lambda s: s
    mock_snapshot.__exit__ = MagicMock(return_value=False)
    mock_snapshot.execute_sql = MagicMock(return_value=[(nlq,) for nlq in existing_nlqs])

    mock_db = MagicMock()
    mock_db.snapshot = MagicMock(return_value=mock_snapshot)
    monkeypatch.setattr("src.services.seeder.get_eval_db", lambda: mock_db)

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
        assert len(bulk_calls) == 0  # nothing written

    def test_dry_run_report_includes_proposed_questions(self, monkeypatch):
        generated = ["New question A?", "New question B?"]
        _patch_seed_dependencies(monkeypatch, generated_questions=generated)
        report = seed_all(dry_run=True)

        proposed = report.strata_detail[0]["proposed"]
        assert len(proposed) == 2
        assert "New question A?" in proposed

    def test_execute_writes_to_spanner(self, monkeypatch):
        generated = ["New question A?", "New question B?"]
        bulk_calls = _patch_seed_dependencies(monkeypatch, generated_questions=generated)
        report = seed_all(dry_run=False)

        assert len(bulk_calls) == 1
        rows = bulk_calls[0]
        assert len(rows) == 2
        assert all(r["is_seeded"] is True for r in rows)
        assert all(r["table_name"] == "orders" for r in rows)

    def test_deduplication_against_existing(self, monkeypatch):
        existing = {"new question a?"}  # lowercase match
        generated = ["New question A?", "Brand new question B?"]
        bulk_calls = _patch_seed_dependencies(
            monkeypatch, generated_questions=generated, existing_nlqs=existing
        )
        report = seed_all(dry_run=False)

        # Only "Brand new question B?" should be written
        rows = bulk_calls[0]
        assert len(rows) == 1
        assert rows[0]["nlq"] == "Brand new question B?"

    def test_deduplication_within_batch(self, monkeypatch):
        # Same question proposed twice (duplicate within generated list)
        generated = ["Duplicate question?", "Duplicate question?", "Unique question?"]
        bulk_calls = _patch_seed_dependencies(monkeypatch, generated_questions=generated)
        report = seed_all(dry_run=False)

        rows = bulk_calls[0]
        nlqs = [r["nlq"] for r in rows]
        assert len(nlqs) == len(set(nlq.lower() for nlq in nlqs))

    def test_skipped_duplicate_counted(self, monkeypatch):
        existing = {"already here?"}
        generated = ["Already here?", "New one?"]
        _patch_seed_dependencies(
            monkeypatch, generated_questions=generated, existing_nlqs=existing
        )
        report = seed_all(dry_run=False)
        assert report.skipped_duplicate == 1

    def test_stratum_with_no_needed_skipped(self, monkeypatch):
        strata = [
            Stratum("orders", "aggregation", "", current_count=7, target_count=7),
            Stratum("products", "filter", "", current_count=2, target_count=7),
        ]
        table_schemas = [_make_schema("orders"), _make_schema("products")]
        generated = ["Product question?"] * 5

        generate_calls = []
        bulk_calls = _patch_seed_dependencies(
            monkeypatch, strata=strata,
            table_schemas=table_schemas, generated_questions=generated,
        )
        generate_tracker = []
        monkeypatch.setattr(
            "src.services.seeder.judge.generate_questions_for_stratum",
            lambda **kwargs: generate_tracker.append(kwargs["table_name"]) or generated,
        )

        report = seed_all(dry_run=False)
        # Only products stratum needs work
        assert generate_tracker == ["products"]
        assert report.strata_processed == 1

    def test_report_totals_aggregated_correctly(self, monkeypatch):
        strata = [
            Stratum("orders", "aggregation", "", current_count=5, target_count=7),
            Stratum("products", "filter", "", current_count=4, target_count=7),
        ]
        table_schemas = [_make_schema("orders"), _make_schema("products")]

        calls = {"count": 0}
        def fake_generate(**kwargs):
            calls["count"] += 1
            return ["Q1?", "Q2?"] if kwargs["table_name"] == "orders" else ["Q3?"]

        bulk_calls = _patch_seed_dependencies(
            monkeypatch, strata=strata, table_schemas=table_schemas,
        )
        monkeypatch.setattr(
            "src.services.seeder.judge.generate_questions_for_stratum",
            fake_generate,
        )

        report = seed_all(dry_run=False)
        assert report.strata_processed == 2
        assert report.questions_generated == 3  # 2 + 1
        assert report.questions_written == 3

    def test_execute_dry_run_proposed_empty_after_execute(self, monkeypatch):
        generated = ["Q1?", "Q2?"]
        _patch_seed_dependencies(monkeypatch, generated_questions=generated)
        report = seed_all(dry_run=False)

        # proposed list should be empty on execute (not dry-run)
        assert report.strata_detail[0]["proposed"] == []

    def test_questions_marked_as_seeded_and_leakage_unchecked(self, monkeypatch):
        generated = ["New question?"]
        bulk_calls = _patch_seed_dependencies(monkeypatch, generated_questions=generated)
        seed_all(dry_run=False)

        row = bulk_calls[0][0]
        assert row["is_seeded"] is True
        assert row.get("leakage_checked") is not True  # must NOT be pre-checked
