"""Unit tests for leakage guard service.

All external dependencies (spanner_source, embedding, judge, spanner_eval)
are mocked to keep tests fast and hermetic.
"""
import textwrap
import tempfile
import os
import pytest
from unittest.mock import patch, MagicMock

from src.core.models import Question, LeakageCheck
from src.services import leakage


def _make_question(id="q-1", nlq="How many orders were placed?") -> Question:
    return Question(
        id=id, nlq=nlq, table_name="orders", task="aggregation",
        tone="neutral", status="active", is_seeded=False, leakage_checked=False,
        leakage_check_id=None, notes=None, created_at=None, updated_at=None,
    )


def _make_leakage_check(**kwargs) -> LeakageCheck:
    defaults = dict(
        id="lc-1", question_id="q-1",
        embedding_flagged=False, embedding_max_sim=0.1, embedding_match_text=None,
        llm_flagged=False, llm_reasoning="No match found.",
        overall_passed=True, checked_at=None,
    )
    defaults.update(kwargs)
    return LeakageCheck(**defaults)


# ─── _extract_prompt_examples ─────────────────────────────────────────────────

class TestExtractPromptExamples:
    def _write_py(self, tmpdir, filename, content):
        path = os.path.join(tmpdir, filename)
        with open(path, "w") as f:
            f.write(textwrap.dedent(content))
        return path

    def test_extracts_from_examples_variable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_py(tmpdir, "prompts.py", """
                examples = [
                    "How many orders were placed last month?",
                    "What is the total revenue by product?",
                ]
            """)
            result = leakage._extract_prompt_examples(tmpdir)
            assert any("orders" in e for e in result)
            assert any("revenue" in e for e in result)

    def test_extracts_from_sample_queries_variable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_py(tmpdir, "agent.py", """
                sample_queries = [
                    "List all customers who made a purchase in Q1?",
                ]
            """)
            result = leakage._extract_prompt_examples(tmpdir)
            assert any("Q1" in e for e in result)

    def test_question_strings_in_any_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_py(tmpdir, "agent.py", """
                SYSTEM_PROMPT = "Use these guidelines when answering."
                EXAMPLE = "What are the top 5 selling products by revenue?"
            """)
            result = leakage._extract_prompt_examples(tmpdir)
            assert any("top 5" in e for e in result)

    def test_non_question_strings_excluded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_py(tmpdir, "agent.py", """
                url = "https://example.com/api"
                description = "This is a description without a question mark"
            """)
            result = leakage._extract_prompt_examples(tmpdir)
            assert not any("example.com" in e for e in result)

    def test_short_strings_excluded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_py(tmpdir, "agent.py", """
                q = "Short?"
            """)
            result = leakage._extract_prompt_examples(tmpdir)
            assert not any(e == "Short?" for e in result)

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = leakage._extract_prompt_examples(tmpdir)
            assert result == []

    def test_recursive_search(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = os.path.join(tmpdir, "subdir", "nested")
            os.makedirs(subdir)
            self._write_py(subdir, "deep.py", """
                examples = ["How many items are in inventory right now?"]
            """)
            result = leakage._extract_prompt_examples(tmpdir)
            assert any("inventory" in e for e in result)


# ─── run_leakage_check ────────────────────────────────────────────────────────

class TestRunLeakageCheck:
    def _mock_all(self, monkeypatch, *,
                  corpus_nlqs=None,
                  corpus_embs=None,
                  query_emb=None,
                  max_sim=0.2,
                  best_idx=0,
                  llm_flagged=False,
                  llm_reasoning="No match.",
                  agent_repo_path=None,
                  returned_check=None):
        cfg = MagicMock()
        cfg.leakage_embedding_threshold = 0.85
        cfg.agent_repo_path = agent_repo_path
        monkeypatch.setattr("src.services.leakage.get_config", lambda: cfg)

        monkeypatch.setattr(
            "src.services.leakage.spanner_source.get_curriculum_nlqs",
            lambda: corpus_nlqs or ["Sample curriculum question?"],
        )
        monkeypatch.setattr(
            "src.services.leakage.embedding.get_corpus_embeddings",
            lambda nlqs: corpus_embs or [[0.1] * 768],
        )
        monkeypatch.setattr(
            "src.services.leakage.embedding.embed_text",
            lambda text: query_emb or [0.2] * 768,
        )
        monkeypatch.setattr(
            "src.services.leakage.embedding.find_max_similarity",
            lambda q, c: (max_sim, best_idx),
        )

        llm_result = MagicMock()
        llm_result.flagged = llm_flagged
        llm_result.reasoning = llm_reasoning
        monkeypatch.setattr(
            "src.services.leakage.judge.check_against_prompts",
            lambda nlq, examples: llm_result,
        )

        if returned_check is None:
            returned_check = _make_leakage_check()
        monkeypatch.setattr(
            "src.services.leakage.spanner_eval.insert_leakage_check",
            lambda **kwargs: returned_check,
        )

        return returned_check

    def test_clean_question_passes(self, monkeypatch):
        expected = _make_leakage_check(overall_passed=True)
        self._mock_all(monkeypatch, max_sim=0.2, llm_flagged=False, returned_check=expected)
        q = _make_question()
        result = leakage.run_leakage_check(q)
        assert result.overall_passed is True

    def test_embedding_flagged_fails(self, monkeypatch):
        expected = _make_leakage_check(embedding_flagged=True, overall_passed=False)
        self._mock_all(monkeypatch, max_sim=0.95, llm_flagged=False, returned_check=expected)
        q = _make_question()
        result = leakage.run_leakage_check(q)
        assert result.overall_passed is False

    def test_llm_flagged_fails(self, monkeypatch):
        expected = _make_leakage_check(llm_flagged=True, overall_passed=False)
        self._mock_all(monkeypatch, max_sim=0.2, llm_flagged=True, returned_check=expected)
        q = _make_question()
        result = leakage.run_leakage_check(q)
        assert result.overall_passed is False

    def test_both_flagged_fails(self, monkeypatch):
        expected = _make_leakage_check(
            embedding_flagged=True, llm_flagged=True, overall_passed=False
        )
        self._mock_all(monkeypatch, max_sim=0.97, llm_flagged=True, returned_check=expected)
        q = _make_question()
        result = leakage.run_leakage_check(q)
        assert result.overall_passed is False

    def test_empty_corpus_no_embedding_check(self, monkeypatch):
        """With no curriculum NLQs, embedding check should not flag."""
        cfg = MagicMock()
        cfg.leakage_embedding_threshold = 0.85
        cfg.agent_repo_path = None
        monkeypatch.setattr("src.services.leakage.get_config", lambda: cfg)
        monkeypatch.setattr(
            "src.services.leakage.spanner_source.get_curriculum_nlqs", lambda: []
        )
        monkeypatch.setattr(
            "src.services.leakage.embedding.get_corpus_embeddings", lambda nlqs: []
        )
        # embed_text should still be called but find_max_similarity should NOT
        embed_called = []
        monkeypatch.setattr(
            "src.services.leakage.embedding.embed_text",
            lambda text: embed_called.append(text) or [0.1] * 768,
        )
        similarity_called = []
        monkeypatch.setattr(
            "src.services.leakage.embedding.find_max_similarity",
            lambda q, c: similarity_called.append(True) or (0.0, -1),
        )
        llm_result = MagicMock(flagged=False, reasoning="ok")
        monkeypatch.setattr(
            "src.services.leakage.judge.check_against_prompts",
            lambda nlq, examples: llm_result,
        )
        captured = {}
        def fake_insert(**kwargs):
            captured.update(kwargs)
            return _make_leakage_check(**{k: v for k, v in kwargs.items() if k != "question_id"})
        monkeypatch.setattr("src.services.leakage.spanner_eval.insert_leakage_check", fake_insert)

        leakage.run_leakage_check(_make_question())
        assert not similarity_called
        assert captured["embedding_flagged"] is False
        assert captured["embedding_max_sim"] == 0.0

    def test_insert_leakage_check_called_with_correct_args(self, monkeypatch):
        cfg = MagicMock()
        cfg.leakage_embedding_threshold = 0.85
        cfg.agent_repo_path = None
        monkeypatch.setattr("src.services.leakage.get_config", lambda: cfg)
        monkeypatch.setattr(
            "src.services.leakage.spanner_source.get_curriculum_nlqs",
            lambda: ["Curriculum example?"],
        )
        monkeypatch.setattr(
            "src.services.leakage.embedding.get_corpus_embeddings",
            lambda nlqs: [[0.1] * 768],
        )
        monkeypatch.setattr(
            "src.services.leakage.embedding.embed_text",
            lambda text: [0.9] * 768,
        )
        monkeypatch.setattr(
            "src.services.leakage.embedding.find_max_similarity",
            lambda q, c: (0.92, 0),
        )
        llm_result = MagicMock(flagged=False, reasoning="No match.")
        monkeypatch.setattr(
            "src.services.leakage.judge.check_against_prompts",
            lambda nlq, examples: llm_result,
        )

        captured = {}
        def fake_insert(**kwargs):
            captured.update(kwargs)
            return _make_leakage_check(
                embedding_flagged=True,
                embedding_max_sim=0.92,
                embedding_match_text="Curriculum example?",
                overall_passed=False,
            )
        monkeypatch.setattr("src.services.leakage.spanner_eval.insert_leakage_check", fake_insert)

        q = _make_question(id="q-42")
        leakage.run_leakage_check(q)

        assert captured["question_id"] == "q-42"
        assert captured["embedding_flagged"] is True
        assert abs(captured["embedding_max_sim"] - 0.92) < 1e-5
        assert captured["embedding_match_text"] == "Curriculum example?"
        assert captured["llm_flagged"] is False
        assert captured["overall_passed"] is False
