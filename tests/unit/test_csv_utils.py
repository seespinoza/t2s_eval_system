import pytest
from src.utils.csv_utils import questions_to_csv, csv_to_updates, QuestionUpdate
from src.core.models import Question


def _make_question(**kwargs) -> Question:
    defaults = dict(
        id="abc-123",
        nlq="How many orders were placed?",
        table_name="orders",
        task="aggregation",
        tone="neutral",
        status="active",
        is_seeded=False,
        leakage_checked=True,
        leakage_check_id=None,
        notes=None,
        created_at=None,
        updated_at=None,
    )
    defaults.update(kwargs)
    return Question(**defaults)


class TestQuestionsToCsv:
    def test_header_present(self):
        csv_text = questions_to_csv([])
        assert "id,nlq,table_name,task,status,is_seeded,leakage_checked,notes" in csv_text

    def test_single_question(self):
        q = _make_question()
        csv_text = questions_to_csv([q])
        assert "abc-123" in csv_text
        assert "How many orders were placed?" in csv_text
        assert "orders" in csv_text
        assert "aggregation" in csv_text
        assert "active" in csv_text

    def test_notes_none_exported_as_empty(self):
        q = _make_question(notes=None)
        csv_text = questions_to_csv([q])
        lines = csv_text.strip().split("\n")
        assert len(lines) == 2  # header + 1 row
        assert lines[1].endswith(",")  # empty notes at end

    def test_notes_with_value(self):
        q = _make_question(notes="reviewed by team")
        csv_text = questions_to_csv([q])
        assert "reviewed by team" in csv_text

    def test_nlq_with_comma_quoted(self):
        q = _make_question(nlq="How many orders, returns, and refunds?")
        csv_text = questions_to_csv([q])
        # CSV quoting should preserve value on round-trip
        updates, errors = csv_to_updates(csv_text)
        assert len(errors) == 0
        assert updates[0].nlq == "How many orders, returns, and refunds?"

    def test_nlq_with_unicode(self):
        q = _make_question(nlq="Combien d'ordres en français?")
        csv_text = questions_to_csv([q])
        updates, errors = csv_to_updates(csv_text)
        assert len(errors) == 0
        assert updates[0].nlq == "Combien d'ordres en français?"

    def test_multiple_questions(self):
        questions = [
            _make_question(id=f"id-{i}", nlq=f"Question {i}?") for i in range(5)
        ]
        csv_text = questions_to_csv(questions)
        lines = csv_text.strip().split("\n")
        assert len(lines) == 6  # header + 5 rows

    def test_round_trip_preserves_id_and_nlq(self):
        q = _make_question(id="my-uuid-1234", nlq="What is the total revenue?")
        csv_text = questions_to_csv([q])
        updates, errors = csv_to_updates(csv_text)
        assert len(errors) == 0
        assert len(updates) == 1
        assert updates[0].id == "my-uuid-1234"
        assert updates[0].nlq == "What is the total revenue?"


class TestCsvToUpdates:
    def test_empty_csv_missing_id_column(self):
        updates, errors = csv_to_updates("nlq,status\nHello?,active")
        assert len(updates) == 0
        assert len(errors) == 1
        assert "id" in errors[0]

    def test_missing_id_value_skipped(self):
        csv_text = "id,nlq,status\n,New question?,active"
        updates, errors = csv_to_updates(csv_text)
        assert len(updates) == 0
        assert len(errors) == 1
        assert "missing id" in errors[0]

    def test_valid_row_parsed(self):
        csv_text = "id,nlq,status\nabc-123,How many orders?,active"
        updates, errors = csv_to_updates(csv_text)
        assert len(errors) == 0
        assert len(updates) == 1
        assert updates[0].id == "abc-123"
        assert updates[0].nlq == "How many orders?"
        assert updates[0].status == "active"

    def test_valid_statuses(self):
        for status in ("active", "monitoring", "deleted"):
            csv_text = f"id,nlq,status\nabc-123,Q?,{status}"
            updates, errors = csv_to_updates(csv_text)
            assert len(errors) == 0
            assert updates[0].status == status

    def test_invalid_status_skipped(self):
        csv_text = "id,nlq,status\nabc-123,Q?,retired"
        updates, errors = csv_to_updates(csv_text)
        assert len(updates) == 0
        assert len(errors) == 1
        assert "invalid status" in errors[0]

    def test_status_case_normalized(self):
        csv_text = "id,nlq,status\nabc-123,Q?,ACTIVE"
        updates, errors = csv_to_updates(csv_text)
        assert len(errors) == 0
        assert updates[0].status == "active"

    def test_empty_nlq_not_set(self):
        csv_text = "id,nlq,status\nabc-123,,active"
        updates, errors = csv_to_updates(csv_text)
        assert len(errors) == 0
        assert updates[0].nlq is None

    def test_notes_empty_becomes_none(self):
        csv_text = "id,notes\nabc-123,"
        updates, errors = csv_to_updates(csv_text)
        assert len(errors) == 0
        assert updates[0].notes is None

    def test_notes_with_value(self):
        csv_text = "id,notes\nabc-123,check this one"
        updates, errors = csv_to_updates(csv_text)
        assert updates[0].notes == "check this one"

    def test_table_name_and_task_not_mutable(self):
        csv_text = "id,nlq,table_name,task\nabc-123,Q?,new_table,new_task"
        updates, errors = csv_to_updates(csv_text)
        # table_name and task aren't fields on QuestionUpdate
        assert not hasattr(updates[0], "table_name")
        assert not hasattr(updates[0], "task")

    def test_multiple_rows_mixed_validity(self):
        csv_text = (
            "id,nlq,status\n"
            "abc-1,Valid question?,active\n"
            ",Missing id?,active\n"
            "abc-3,Another?,monitoring\n"
        )
        updates, errors = csv_to_updates(csv_text)
        assert len(updates) == 2
        assert len(errors) == 1

    def test_empty_body_returns_empty(self):
        csv_text = "id,nlq,status\n"
        updates, errors = csv_to_updates(csv_text)
        assert len(updates) == 0
        assert len(errors) == 0

    def test_newlines_in_nlq_handled(self):
        csv_text = 'id,nlq\nabc-1,"Line one\nLine two?"\n'
        updates, errors = csv_to_updates(csv_text)
        assert len(errors) == 0
        assert "Line one" in updates[0].nlq
