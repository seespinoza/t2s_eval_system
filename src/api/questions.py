import io
from flask import Blueprint, request, jsonify, Response
from src.services import spanner_eval, leakage
from src.utils.csv_utils import questions_to_csv, csv_to_updates

bp = Blueprint("questions", __name__, url_prefix="/api/questions")


@bp.get("")
def list_questions():
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 50))
    lc = request.args.get("leakage_checked")
    questions = spanner_eval.list_questions(
        status=request.args.get("status"),
        table_name=request.args.get("table_name"),
        task=request.args.get("task"),
        tone=request.args.get("tone"),
        leakage_checked=(lc.lower() == "true") if lc is not None else None,
        page=page,
        page_size=page_size,
    )
    return jsonify([q.to_dict() for q in questions])


@bp.post("")
def create_question():
    body = request.get_json(force=True)
    if not all(k in body for k in ("nlq", "table_name", "task")):
        return jsonify({"error": "nlq, table_name, and task are required"}), 400
    q = spanner_eval.create_question(
        nlq=body["nlq"],
        table_name=body["table_name"],
        task=body["task"],
        tone=body.get("tone", "neutral"),
        status=body.get("status", "active"),
        notes=body.get("notes"),
    )
    return jsonify(q.to_dict()), 201


@bp.get("/<question_id>")
def get_question(question_id):
    q = spanner_eval.get_question(question_id)
    if not q:
        return jsonify({"error": "Not found"}), 404
    data = q.to_dict()
    if q.leakage_check_id:
        lc = spanner_eval.get_leakage_check(q.id, q.leakage_check_id)
        data["leakage_check"] = lc.to_dict() if lc else None
    return jsonify(data)


@bp.put("/<question_id>")
def update_question(question_id):
    body = request.get_json(force=True)
    allowed = {"nlq", "table_name", "task", "tone", "status", "notes"}
    fields = {k: v for k, v in body.items() if k in allowed}
    q = spanner_eval.update_question(question_id, **fields)
    if not q:
        return jsonify({"error": "Not found"}), 404
    return jsonify(q.to_dict())


@bp.delete("/<question_id>")
def delete_question(question_id):
    q = spanner_eval.get_question(question_id)
    if not q:
        return jsonify({"error": "Not found"}), 404
    spanner_eval.soft_delete_question(question_id)
    return jsonify({"deleted": question_id})


@bp.post("/<question_id>/check-leakage")
def check_leakage_single(question_id):
    q = spanner_eval.get_question(question_id)
    if not q:
        return jsonify({"error": "Not found"}), 404
    lc = leakage.run_leakage_check(q)
    return jsonify(lc.to_dict())


@bp.post("/check-leakage-batch")
def check_leakage_batch():
    questions = spanner_eval.list_unchecked_questions()
    results = []
    errors = []
    for q in questions:
        try:
            lc = leakage.run_leakage_check(q)
            results.append({"question_id": q.id, "overall_passed": lc.overall_passed})
        except Exception as e:
            errors.append({"question_id": q.id, "error": str(e)})
    return jsonify({"processed": len(results), "errors": errors, "results": results})


@bp.get("/export.csv")
def export_csv():
    questions = spanner_eval.list_questions(page=1, page_size=10000)
    csv_text = questions_to_csv(questions)
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=questions.csv"},
    )


@bp.post("/import-csv")
def import_csv():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    csv_text = request.files["file"].read().decode("utf-8")
    updates, parse_errors = csv_to_updates(csv_text)

    applied = 0
    apply_errors = []
    for upd in updates:
        try:
            fields = {}
            if upd.nlq is not None:
                fields["nlq"] = upd.nlq
            if upd.status is not None:
                fields["status"] = upd.status
            if upd.notes is not None:
                fields["notes"] = upd.notes
            if fields:
                spanner_eval.update_question(upd.id, **fields)
                applied += 1
        except Exception as e:
            apply_errors.append({"id": upd.id, "error": str(e)})

    return jsonify({
        "applied": applied,
        "parse_errors": parse_errors,
        "apply_errors": apply_errors,
    })
