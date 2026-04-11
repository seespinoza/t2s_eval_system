"""Gemini-based LLM judge and prompt leakage checker."""
import json
import time
from dataclasses import dataclass
import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig
from src.config.settings import get_config
from src.services import llm_logger

_model: GenerativeModel | None = None


def _get_model() -> GenerativeModel:
    global _model
    if _model is None:
        cfg = get_config()
        vertexai.init(project=cfg.vertex_ai_project, location=cfg.vertex_ai_location)
        _model = GenerativeModel(cfg.judge_model)
    return _model


def _generate(prompt: str, config: GenerationConfig, call_type: str):
    """Thin wrapper around generate_content that records latency and token usage."""
    t0 = time.monotonic()
    response = _get_model().generate_content(prompt, generation_config=config)
    latency_ms = int((time.monotonic() - t0) * 1000)

    usage = getattr(response, "usage_metadata", None)
    input_tokens = getattr(usage, "prompt_token_count", None) if usage else None
    output_tokens = getattr(usage, "candidates_token_count", None) if usage else None
    llm_logger.log_call(call_type, input_tokens=input_tokens,
                        output_tokens=output_tokens, latency_ms=latency_ms)
    return response


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
    response = _generate(prompt, GenerationConfig(response_mime_type="application/json", temperature=0.1), "judge")
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
    response = _generate(prompt, GenerationConfig(response_mime_type="application/json", temperature=0.1), "leakage_llm")
    data = json.loads(response.text)
    return LlmLeakageResult(flagged=bool(data["flagged"]), reasoning=data.get("reasoning", ""))


_TONE_INSTRUCTIONS = {
    "formal": (
        "Use precise, technical language. Questions should be verbose and unambiguous, "
        "like those written by a data analyst in a formal report request. "
        'Example style: "What is the total aggregate revenue, broken down by product category, for the fiscal year ending Q4?"'
    ),
    "neutral": (
        "Use clear, professional but conversational language, like a business analyst asking a colleague. "
        'Example style: "What were the top 5 products by revenue last quarter?"'
    ),
    "casual": (
        "Use informal, shorthand language — potentially terse or ambiguous, like a Slack message. "
        'Example style: "how many orders last month?" or "top customers by spend?"'
    ),
}


def generate_hypothetical_question(
    table_name: str, task: str, tone: str, schema_text: str,
) -> str:
    """Generate a single hypothetical 'ideal' question for HyDE-based curriculum retrieval."""
    tone_instruction = _TONE_INSTRUCTIONS.get(tone, _TONE_INSTRUCTIONS["neutral"])
    prompt = f"""Generate a single representative natural language question for a text-to-SQL system.

TABLE: {table_name}
TASK TYPE: {task}
TONE: {tone}
TONE GUIDANCE: {tone_instruction}

TABLE SCHEMA:
{schema_text}

Return ONLY a JSON object: {{"question": "<the question>"}}
"""
    response = _generate(prompt, GenerationConfig(response_mime_type="application/json", temperature=0.5), "hyde_hypothetical")
    data = json.loads(response.text)
    return str(data.get("question", "")).strip()


def generate_questions_for_stratum(
    table_name: str, task: str, tone: str, schema_text: str,
    examples: list[str], count: int,
) -> list[str]:
    tone_instruction = _TONE_INSTRUCTIONS.get(tone, _TONE_INSTRUCTIONS["neutral"])
    few_shot = ""
    if examples:
        few_shot = "\nExample questions (for style reference — do NOT copy these):\n" + "\n".join(
            f"- {ex}" for ex in examples[:10]
        ) + "\n"

    prompt = f"""You are generating test questions for a text-to-SQL evaluation system.

TABLE: {table_name}
TASK TYPE: {task}
TONE: {tone}
TONE GUIDANCE: {tone_instruction}

TABLE SCHEMA AND DOCUMENTATION:
{schema_text}
{few_shot}
Generate exactly {count} natural language questions that:
1. Are clearly answerable using the {table_name} table
2. Require the "{task}" type of SQL operation
3. Match the "{tone}" tone described above
4. Are NOT copies of any example above (those are style references only)

Return ONLY a JSON array of strings: ["question 1", "question 2", ...]
"""
    response = _generate(prompt, GenerationConfig(response_mime_type="application/json", temperature=0.7), "seed_generate")
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
    response = _generate(prompt, GenerationConfig(response_mime_type="application/json", temperature=0.3), "discover_strata")
    strata = json.loads(response.text)
    if not isinstance(strata, list):
        return []
    return [s for s in strata if isinstance(s, dict) and "table_name" in s and "task" in s]
