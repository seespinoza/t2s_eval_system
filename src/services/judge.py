"""Gemini-based LLM judge and prompt leakage checker."""
import json
from dataclasses import dataclass
import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig
from src.config.settings import get_config

_model: GenerativeModel | None = None


def _get_model() -> GenerativeModel:
    global _model
    if _model is None:
        cfg = get_config()
        vertexai.init(project=cfg.vertex_ai_project, location=cfg.vertex_ai_location)
        _model = GenerativeModel(cfg.judge_model)
    return _model


@dataclass
class JudgeResult:
    verdict: str       # 'pass' | 'fail'
    confidence: float  # 0.0–1.0
    reasoning: str


@dataclass
class LlmLeakageResult:
    flagged: bool
    reasoning: str


def judge_result(nlq: str, sql: str, agent_response: str, business_rules_summary: str) -> JudgeResult:
    prompt = f"""You are evaluating whether a SQL query correctly answers a natural language question
and adheres to all business rules defined in the data dictionary.

NATURAL LANGUAGE QUESTION:
{nlq}

GENERATED SQL:
{sql}

AGENT RESPONSE / COMMENTARY:
{agent_response}

BUSINESS RULES AND DATA DICTIONARY SUMMARY:
{business_rules_summary}

Evaluate whether the SQL query:
1. Correctly addresses the user's question
2. Applies all required filters specified in the business rules
3. Uses the correct tables and joins as defined in the data dictionary
4. Does not violate any querying constraints

Respond in JSON:
{{"verdict": "pass" or "fail", "confidence": <float 0.0-1.0>, "reasoning": "<concise explanation>"}}
"""
    response = _get_model().generate_content(
        prompt,
        generation_config=GenerationConfig(response_mime_type="application/json", temperature=0.1),
    )
    data = json.loads(response.text)
    return JudgeResult(
        verdict=data["verdict"],
        confidence=float(data["confidence"]),
        reasoning=data.get("reasoning", ""),
    )


def check_against_prompts(nlq: str, prompt_examples: list[str]) -> LlmLeakageResult:
    if not prompt_examples:
        return LlmLeakageResult(flagged=False, reasoning="No prompt examples found.")

    examples_text = "\n".join(f"{i+1}. {ex}" for i, ex in enumerate(prompt_examples[:200]))
    prompt = f"""You are checking whether a test question has already been used as an example in an AI agent's prompts.

TEST QUESTION:
{nlq}

KNOWN PROMPT EXAMPLES:
{examples_text}

Is the test question substantially similar (same intent, same entities, same filters, essentially the same question rephrased) to ANY of the prompt examples above?

Respond in JSON: {{"flagged": true or false, "reasoning": "<brief explanation>"}}
"""
    response = _get_model().generate_content(
        prompt,
        generation_config=GenerationConfig(response_mime_type="application/json", temperature=0.1),
    )
    data = json.loads(response.text)
    return LlmLeakageResult(flagged=bool(data["flagged"]), reasoning=data.get("reasoning", ""))


def generate_questions_for_stratum(
    table_name: str, task: str, schema_text: str,
    curriculum_examples: list[str], count: int,
) -> list[str]:
    exclusion = ""
    if curriculum_examples:
        exclusion = "\nExisting examples to AVOID duplicating:\n" + "\n".join(
            f"- {ex}" for ex in curriculum_examples[:50]
        ) + "\n"

    prompt = f"""You are generating test questions for a text-to-SQL evaluation system.

TABLE: {table_name}
TASK TYPE: {task}

TABLE SCHEMA AND DOCUMENTATION:
{schema_text}
{exclusion}
Generate exactly {count} natural language questions that:
1. Are clearly answerable using the {table_name} table
2. Require the "{task}" type of SQL operation
3. Are NOT substantially similar to any existing example above
4. Sound like questions a business analyst would ask

Return ONLY a JSON array of strings: ["question 1", "question 2", ...]
"""
    response = _get_model().generate_content(
        prompt,
        generation_config=GenerationConfig(response_mime_type="application/json", temperature=0.7),
    )
    questions = json.loads(response.text)
    if not isinstance(questions, list):
        return []
    return [str(q).strip() for q in questions if q]


def discover_strata(table_schemas: list, curriculum_entries: list) -> list[dict]:
    schema_summary = "\n".join(f"- {s.table_name}: {s.description}" for s in table_schemas)
    curriculum_sample = "\n".join(
        f"- [{e.table_name}] [{e.task}] {e.query_text}"
        for e in curriculum_entries[:100]
        if e.table_name and e.task
    )
    prompt = f"""You are analyzing a database to identify all logical query patterns for evaluation.

AVAILABLE TABLES:
{schema_summary}

SAMPLE EXISTING QUERIES (table, task, question):
{curriculum_sample}

Identify all meaningful (table_name, task) combinations. Task types include but are not limited to:
filter_by_date, filter_by_category, aggregate_sum, aggregate_count, aggregate_average,
join_related_table, rank_top_n, trend_over_time, compare_groups, search_by_name.

Return ONLY a JSON array:
[{{"table_name": "...", "task": "...", "description": "brief description"}}, ...]
"""
    response = _get_model().generate_content(
        prompt,
        generation_config=GenerationConfig(response_mime_type="application/json", temperature=0.3),
    )
    strata = json.loads(response.text)
    if not isinstance(strata, list):
        return []
    return [s for s in strata if isinstance(s, dict) and "table_name" in s and "task" in s]
