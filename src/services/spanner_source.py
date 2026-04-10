"""Read-only access to the source Spanner database (semantic layer + curriculum)."""
from dataclasses import dataclass
from src.core.database import get_source_db


@dataclass
class TableSchema:
    table_name: str
    description: str
    columns: list[dict]


@dataclass
class CurriculumEntry:
    query_text: str
    sql: str | None
    table_name: str | None
    task: str | None


def get_all_table_schemas() -> list[TableSchema]:
    """Fetch all table schemas from the semantic layer.

    Assumes a table named `TableSchemas` with columns:
    table_name, description, columns_json (JSON array of column dicts).
    Adjust the query to match your actual Spanner schema.
    """
    db = get_source_db()
    schemas: list[TableSchema] = []
    with db.snapshot() as snapshot:
        rows = snapshot.execute_sql(
            "SELECT table_name, description, columns_json FROM TableSchemas ORDER BY table_name"
        )
        for row in rows:
            schemas.append(TableSchema(
                table_name=row[0],
                description=row[1] or "",
                columns=row[2] or [],
            ))
    return schemas


def get_curriculum_entries() -> list[CurriculumEntry]:
    """Fetch all entries from the curriculum view.

    Assumes a view named `CurriculumView` with columns:
    query_text, sql, table_name, task.
    Adjust to match your actual Spanner schema.
    """
    db = get_source_db()
    entries: list[CurriculumEntry] = []
    with db.snapshot() as snapshot:
        rows = snapshot.execute_sql(
            "SELECT query_text, sql, table_name, task FROM CurriculumView"
        )
        for row in rows:
            entries.append(CurriculumEntry(
                query_text=row[0], sql=row[1], table_name=row[2], task=row[3],
            ))
    return entries


def get_curriculum_nlqs() -> list[str]:
    return [e.query_text for e in get_curriculum_entries() if e.query_text]
