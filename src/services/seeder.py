"""Auto-seeds test questions stratified by table/task/tone using LLM + HyDE retrieval."""
import logging
from dataclasses import dataclass, field
from src.config.settings import get_config
from src.core.database import get_eval_db, T_QUESTIONS
from src.core.models import VALID_TONES
from src.services import spanner_source, spanner_eval, judge, embedding

log = logging.getLogger(__name__)

TONES = sorted(VALID_TONES)  # ['casual', 'formal', 'neutral']


@dataclass
class Stratum:
    table_name: str
    task: str
    tone: str
    description: str
    current_count: int
    target_count: int

    @property
    def needed(self) -> int:
        return max(0, self.target_count - self.current_count)


@dataclass
class SeedReport:
    strata_processed: int
    questions_generated: int
    questions_written: int
    skipped_duplicate: int
    strata_detail: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "strata_processed": self.strata_processed,
            "questions_generated": self.questions_generated,
            "questions_written": self.questions_written,
            "skipped_duplicate": self.skipped_duplicate,
            "strata_detail": self.strata_detail,
        }


def _get_current_counts() -> dict[tuple[str, str, str], int]:
    counts: dict[tuple[str, str, str], int] = {}
    with get_eval_db().snapshot() as snapshot:
        for row in snapshot.execute_sql(
            f"SELECT table_name, task, tone, COUNT(*) FROM {T_QUESTIONS} "
            "WHERE status != 'deleted' GROUP BY table_name, task, tone"
        ):
            counts[(row[0], row[1], row[2])] = row[3]
    return counts


def get_strata_with_targets() -> list[Stratum]:
    cfg = get_config()
    table_schemas = spanner_source.get_all_table_schemas()
    curriculum_entries = spanner_source.get_curriculum_entries()
    current_counts = _get_current_counts()

    # discover (table, task) combinations — tone is applied separately
    discovered = judge.discover_strata(table_schemas, curriculum_entries)
    strata: list[Stratum] = []
    for item in discovered:
        for tone in TONES:
            key = (item["table_name"], item["task"], tone)
            strata.append(Stratum(
                table_name=item["table_name"],
                task=item["task"],
                tone=tone,
                description=item.get("description", ""),
                current_count=current_counts.get(key, 0),
                target_count=cfg.seeder_active_count,
            ))
    return strata


def _schema_to_text(schema) -> str:
    lines = [f"Table: {schema.table_name}", f"Description: {schema.description}", "Columns:"]
    for col in schema.columns:
        lines.append(f"  - {col.get('name', '')}: {col.get('description', '')} ({col.get('type', '')})")
    return "\n".join(lines)


def _hyde_retrieve_examples(
    table_name: str,
    task: str,
    tone: str,
    schema_text: str,
    curriculum_entries: list,
    existing_nlqs: set[str],
    agent_prompt_examples: list[str],
    top_k: int = 5,
) -> list[str]:
    """Use HyDE to find relevant curriculum examples for few-shot seeding.

    Steps:
    1. Generate a hypothetical ideal question for this (table, task, tone).
    2. Embed it.
    3. Find top-k most similar questions from the curriculum.
    4. Filter out: already in the eval bank, or substantially similar to agent prompt examples.
    """
    cfg = get_config()

    # Step 1 + 2: hypothetical question → embedding
    try:
        hypothetical = judge.generate_hypothetical_question(table_name, task, tone, schema_text)
    except Exception as e:
        log.warning("HyDE generation failed for %s/%s/%s: %s", table_name, task, tone, e)
        return []

    if not hypothetical:
        return []

    try:
        hyp_emb = embedding.embed_text(hypothetical)
    except Exception as e:
        log.warning("HyDE embedding failed: %s", e)
        return []

    # Step 3: find top-k similar in curriculum (with buffer for filtering)
    curriculum_nlqs = [e.query_text for e in curriculum_entries if e.query_text]
    if not curriculum_nlqs:
        return []

    curriculum_embs = embedding.get_corpus_embeddings(curriculum_nlqs)
    candidates_raw = embedding.top_k_similar(hyp_emb, curriculum_embs, k=top_k * 3)

    # Step 4: filter
    agent_embs = (
        embedding.get_corpus_embeddings(agent_prompt_examples)
        if agent_prompt_examples else []
    )

    examples: list[str] = []
    for idx, _score in candidates_raw:
        nlq = curriculum_nlqs[idx]

        # Skip if already in the eval question bank
        if nlq.lower().strip() in existing_nlqs:
            continue

        # Skip if substantially similar to any agent prompt example
        if agent_embs:
            max_sim, _ = embedding.find_max_similarity(curriculum_embs[idx], agent_embs)
            if max_sim > cfg.leakage_embedding_threshold:
                log.debug("HyDE: skipping curriculum example (agent prompt match, sim=%.2f): %s", max_sim, nlq[:80])
                continue

        examples.append(nlq)
        if len(examples) >= top_k:
            break

    return examples


def seed_all(dry_run: bool = False) -> SeedReport:
    cfg = get_config()
    strata = get_strata_with_targets()
    table_schemas = {s.table_name: s for s in spanner_source.get_all_table_schemas()}
    curriculum_entries = spanner_source.get_curriculum_entries()

    # Pre-fetch agent prompt examples once (used in HyDE filtering)
    agent_prompt_examples: list[str] = []
    if cfg.agent_repo_path:
        from src.services.leakage import _extract_prompt_examples
        agent_prompt_examples = _extract_prompt_examples(cfg.agent_repo_path)

    existing_nlqs: set[str] = set()
    with get_eval_db().snapshot() as snapshot:
        for row in snapshot.execute_sql(
            f"SELECT nlq FROM {T_QUESTIONS} WHERE status != 'deleted'"
        ):
            existing_nlqs.add(row[0].lower().strip())

    total_generated = total_written = total_skipped = 0
    detail: list[dict] = []

    for stratum in strata:
        if stratum.needed <= 0:
            continue

        schema = table_schemas.get(stratum.table_name)
        schema_text = _schema_to_text(schema) if schema else f"Table: {stratum.table_name}"

        # HyDE: retrieve relevant curriculum examples for this (table, task, tone)
        examples = _hyde_retrieve_examples(
            table_name=stratum.table_name,
            task=stratum.task,
            tone=stratum.tone,
            schema_text=schema_text,
            curriculum_entries=curriculum_entries,
            existing_nlqs=existing_nlqs,
            agent_prompt_examples=agent_prompt_examples,
        )

        generated = judge.generate_questions_for_stratum(
            table_name=stratum.table_name,
            task=stratum.task,
            tone=stratum.tone,
            schema_text=schema_text,
            examples=examples,
            count=stratum.needed,
        )

        unique = []
        for q in generated:
            if q.lower().strip() not in existing_nlqs:
                unique.append(q)
                existing_nlqs.add(q.lower().strip())
        skipped = len(generated) - len(unique)
        total_generated += len(generated)
        total_skipped += skipped

        if not dry_run and unique:
            spanner_eval.bulk_insert_questions([
                {
                    "nlq": q,
                    "table_name": stratum.table_name,
                    "task": stratum.task,
                    "tone": stratum.tone,
                    "status": "active",
                    "is_seeded": True,
                }
                for q in unique
            ])
            total_written += len(unique)

        detail.append({
            "table_name": stratum.table_name,
            "task": stratum.task,
            "tone": stratum.tone,
            "needed": stratum.needed,
            "generated": len(generated),
            "unique": len(unique),
            "written": len(unique) if not dry_run else 0,
            "skipped_duplicate": skipped,
            "proposed": unique if dry_run else [],
        })

    return SeedReport(
        strata_processed=len([s for s in strata if s.needed > 0]),
        questions_generated=total_generated,
        questions_written=total_written,
        skipped_duplicate=total_skipped,
        strata_detail=detail,
    )
