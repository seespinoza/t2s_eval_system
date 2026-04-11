"""Orchestrates both data leakage checks for a question."""
import re
from pathlib import Path
from src.config.settings import get_config
from src.core.models import Question, LeakageCheck
from src.services import spanner_source, embedding, judge, spanner_eval

_EXAMPLE_VAR_PATTERN = re.compile(
    r'(?:examples?|sample_queries?|nlqs?|test_questions?|query_examples?)\s*=\s*\[([^\]]+)\]',
    re.IGNORECASE | re.DOTALL,
)
_STRING_LITERAL_PATTERN = re.compile(r'["\']([^"\']{10,300}[?])["\']')


def _extract_prompt_examples(agent_repo_path: str) -> list[str]:
    examples: set[str] = set()
    for filepath in Path(agent_repo_path).glob("**/*.py"):
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
            for match in _EXAMPLE_VAR_PATTERN.finditer(content):
                for s in _STRING_LITERAL_PATTERN.finditer(match.group(1)):
                    examples.add(s.group(1).strip())
            for s in _STRING_LITERAL_PATTERN.finditer(content):
                candidate = s.group(1).strip()
                if len(candidate) > 15 and candidate.endswith("?"):
                    examples.add(candidate)
        except Exception:
            continue
    return list(examples)


def run_leakage_check(question: Question) -> LeakageCheck:
    cfg = get_config()

    # Check A: embedding similarity vs curriculum
    corpus_nlqs = spanner_source.get_curriculum_nlqs()
    corpus_embs = embedding.get_corpus_embeddings(corpus_nlqs)
    query_emb = embedding.embed_text(question.nlq)

    if corpus_embs:
        max_sim, best_idx = embedding.find_max_similarity(query_emb, corpus_embs)
        embedding_flagged = max_sim > cfg.leakage_embedding_threshold
        match_text = corpus_nlqs[best_idx] if best_idx >= 0 else None
    else:
        max_sim, embedding_flagged, match_text = 0.0, False, None

    # Check B: LLM vs prompt examples
    prompt_examples: list[str] = []
    if cfg.agent_repo_path:
        prompt_examples = _extract_prompt_examples(cfg.agent_repo_path)

    llm_result = judge.check_against_prompts(question.nlq, prompt_examples)

    return spanner_eval.insert_leakage_check(
        question_id=question.id,
        embedding_flagged=embedding_flagged,
        embedding_max_sim=round(max_sim, 6),
        embedding_match_text=match_text,
        llm_flagged=llm_result.flagged,
        llm_reasoning=llm_result.reasoning,
        overall_passed=not embedding_flagged and not llm_result.flagged,
    )
