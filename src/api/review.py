from flask import Blueprint, request, jsonify
from src.services import spanner_eval

bp = Blueprint("review", __name__, url_prefix="/api/review")

VALID_DECISIONS = {"confirmed_pass", "override_fail"}


@bp.get("")
def list_items():
    run_id = request.args.get("run_id")
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 50))
    pending_only = request.args.get("pending_only", "true").lower() != "false"
    items = spanner_eval.list_review_items(
        run_id=run_id, pending_only=pending_only,
        page=page, page_size=page_size,
    )
    return jsonify([i.to_dict() for i in items])


@bp.put("/<item_id>")
def submit_review(item_id):
    body = request.get_json(force=True) or {}
    decision = body.get("decision")
    if decision not in VALID_DECISIONS:
        return jsonify({"error": f"decision must be one of {sorted(VALID_DECISIONS)}"}), 400
    item = spanner_eval.submit_review(
        item_id=item_id,
        decision=decision,
        reviewer=body.get("reviewer"),
        notes=body.get("notes"),
    )
    if not item:
        return jsonify({"error": "Not found"}), 404
    return jsonify(item.to_dict())


@bp.get("/stats")
def stats():
    return jsonify(spanner_eval.get_review_stats())
