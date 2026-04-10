"""Auto-seeds test questions stratified by table/task using LLM."""
from dataclasses import dataclass, field
from src.config.settings import get_config
from src.core.database import get_eval_db, T_QUESTIONS
from src.services import spanner_source, spanner_eval, judge


@dataclass
class Stratum:
    table_name: str
    task: str
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


def _get_current_counts() -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    with get_eval_db().snapshot() as snapshot:
        for row in snapshot.execute_sql(
            f"SELECT table_name, task, COUNT(*) FROM {T_QUESTIONS} "
            "WHERE status != 'deleted' GROUP BY table_name, task"
        ):
            counts[(row[0], row[1])] = row[2]
    return counts


def get_strata_with_targets() -> list[Stratum]:
    cfg = get_config()
    table_schemas = spanner_source.get_all_table_schemas()
    curriculum_entries = spanner_source.get_curriculum_entries()
    current_counts = _get_current_counts()

    discovered = judge.discover_strata(table_schemas, curriculum_entries)
    strata: list[Stratum] = []
    for item in discovered:
        key = (item["table_name"], item["task"])
        strata.append(Stratum(
            table_name=item["table_name"],
            task=item["task"],
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


def seed_all(dry_run: bool = False) -> SeedReport:
    strata = get_strata_with_targets()
    table_schemas = {s.table_name: s for s in spanner_source.get_all_table_schemas()}
    curriculum_entries = spanner_source.get_curriculum_entries()

    curriculum_by_table: dict[str, list[str]] = {}
    for entry in curriculum_entries:
        if entry.table_name and entry.query_text:
            curriculum_by_table.setdefault(entry.table_name, []).append(entry.query_text)

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
        curriculum_examples = curriculum_by_table.get(stratum.table_name, [])

        generated = judge.generate_questions_for_stratum(
            table_name=stratum.table_name,
            task=stratum.task,
            schema_text=schema_text,
            curriculum_examples=curriculum_examples,
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
                {"nlq": q, "table_name": stratum.table_name,
                 "task": stratum.task, "status": "active", "is_seeded": True}
                for q in unique
            ])
            total_written += len(unique)

        detail.append({
            "table_name": stratum.table_name,
            "task": stratum.task,
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
