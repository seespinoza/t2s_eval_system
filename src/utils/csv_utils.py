import csv
import io
from dataclasses import dataclass
from src.core.models import Question

EXPORT_COLUMNS = ["id", "nlq", "table_name", "task", "status", "is_seeded", "leakage_checked", "notes"]
VALID_STATUSES = {"active", "monitoring", "deleted"}


@dataclass
class QuestionUpdate:
    id: str
    nlq: str | None = None
    status: str | None = None
    notes: str | None = None


def questions_to_csv(questions: list[Question]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=EXPORT_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for q in questions:
        writer.writerow({
            "id": q.id, "nlq": q.nlq, "table_name": q.table_name,
            "task": q.task, "status": q.status, "is_seeded": q.is_seeded,
            "leakage_checked": q.leakage_checked, "notes": q.notes or "",
        })
    return output.getvalue()


def csv_to_updates(csv_text: str) -> tuple[list[QuestionUpdate], list[str]]:
    updates: list[QuestionUpdate] = []
    errors: list[str] = []
    reader = csv.DictReader(io.StringIO(csv_text))

    if reader.fieldnames is None or "id" not in reader.fieldnames:
        return [], ["CSV must have an 'id' column"]

    for i, row in enumerate(reader, start=2):
        qid = row.get("id", "").strip()
        if not qid:
            errors.append(f"Row {i}: missing id, skipped")
            continue

        update = QuestionUpdate(id=qid)

        if "nlq" in row and row["nlq"].strip():
            update.nlq = row["nlq"].strip()

        if "status" in row and row["status"].strip():
            status = row["status"].strip().lower()
            if status not in VALID_STATUSES:
                errors.append(f"Row {i}: invalid status '{status}', skipped")
                continue
            update.status = status

        if "notes" in row:
            update.notes = row["notes"].strip() or None

        updates.append(update)

    return updates, errors
