from flask import Blueprint, request, jsonify
from src.services import spanner_eval, spanner_source

bp = Blueprint("question_sets", __name__, url_prefix="/api/question-sets")


@bp.get("")
def list_question_sets():
    limit = int(request.args.get("limit", 50))
    sets = spanner_eval.list_question_sets(limit=limit)
    return jsonify([qs.to_dict() for qs in sets])


@bp.post("")
def create_question_set():
    """Create a named question set snapshot.

    Body:
      name        (required) — display name
      version     (optional) — e.g. 'v1', '2024-01-15'
      description (optional) — free-text notes
      question_ids (optional) — explicit list of question UUIDs.
                                If omitted, snapshots all currently active+leakage-checked questions.
      filter      (optional) — {status, table_name, task, tone} to scope the auto-snapshot.
    """
    body = request.get_json(force=True) or {}
    name = body.get("name")
    if not name:
        return jsonify({"error": "'name' is required"}), 400

    question_ids = body.get("question_ids")
    if not question_ids:
        # Auto-snapshot from filter
        filt = body.get("filter", {})
        statuses = filt.get("statuses") or ([filt["status"]] if "status" in filt else ["active", "monitoring"])
        table_name = filt.get("table_name") or None
        task = filt.get("task") or None
        tone = filt.get("tone") or None

        questions = []
        for status in statuses:
            questions.extend(spanner_eval.list_questions(
                status=status, leakage_checked=True,
                table_name=table_name, task=task, tone=tone,
                page=1, page_size=10000,
            ))
        question_ids = [q.id for q in questions]

    if not question_ids:
        return jsonify({"error": "No eligible questions found for this filter"}), 400

    qs = spanner_eval.create_question_set(
        name=name,
        question_ids=question_ids,
        version=body.get("version"),
        description=body.get("description"),
    )
    return jsonify(qs.to_dict()), 201


@bp.get("/<qs_id>")
def get_question_set(qs_id):
    qs = spanner_eval.get_question_set(qs_id)
    if not qs:
        return jsonify({"error": "Not found"}), 404
    return jsonify(qs.to_dict())


@bp.delete("/<qs_id>")
def delete_question_set(qs_id):
    qs = spanner_eval.get_question_set(qs_id)
    if not qs:
        return jsonify({"error": "Not found"}), 404
    spanner_eval.delete_question_set(qs_id)
    return jsonify({"deleted": qs_id})
