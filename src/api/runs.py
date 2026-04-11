import threading
from flask import Blueprint, request, jsonify
from src.services import spanner_eval, orchestrator

bp = Blueprint("runs", __name__, url_prefix="/api/runs")


@bp.get("")
def list_runs():
    limit = int(request.args.get("limit", 20))
    runs = spanner_eval.list_runs(limit=limit)
    return jsonify([r.to_dict() for r in runs])


@bp.post("")
def create_run():
    body = request.get_json(force=True) or {}
    run = spanner_eval.create_run(
        name=body.get("name"),
        config=body.get("config", {}),
        question_filter=body.get("question_filter", {"statuses": ["active", "monitoring"]}),
        agent_version=body.get("agent_version"),
        description=body.get("description"),
        question_set_id=body.get("question_set_id"),
    )
    return jsonify(run.to_dict()), 201


@bp.get("/<run_id>")
def get_run(run_id):
    run = spanner_eval.get_run(run_id)
    if not run:
        return jsonify({"error": "Not found"}), 404
    data = run.to_dict()
    data["progress"] = spanner_eval.get_run_progress(run_id)
    return jsonify(data)


@bp.post("/<run_id>/start")
def start_run(run_id):
    run = spanner_eval.get_run(run_id)
    if not run:
        return jsonify({"error": "Not found"}), 404
    if run.status not in ("pending",):
        return jsonify({"error": f"Run is {run.status}, cannot start"}), 409
    t = threading.Thread(target=orchestrator.start_run, args=(run_id,), daemon=True)
    t.start()
    return jsonify({"started": run_id})


@bp.post("/<run_id>/cancel")
def cancel_run(run_id):
    cancelled = orchestrator.cancel_run(run_id)
    if not cancelled:
        return jsonify({"error": "Run not currently active"}), 404
    return jsonify({"cancelled": run_id})


@bp.delete("/<run_id>")
def delete_run(run_id):
    run = spanner_eval.get_run(run_id)
    if not run:
        return jsonify({"error": "Not found"}), 404
    if run.status == "running":
        return jsonify({"error": "Cannot delete a running run"}), 409
    spanner_eval.delete_run(run_id)
    return jsonify({"deleted": run_id})


@bp.get("/<run_id>/results")
def list_results(run_id):
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 50))
    results = spanner_eval.list_results(
        run_id=run_id,
        outcome=request.args.get("outcome"),
        table_name=request.args.get("table_name"),
        task=request.args.get("task"),
        page=page,
        page_size=page_size,
    )
    return jsonify([r.to_dict() for r in results])


@bp.get("/<run_id>/metrics")
def get_metrics(run_id):
    metrics = spanner_eval.get_run_metrics(run_id)
    if not metrics:
        return jsonify({"error": "Metrics not yet computed"}), 404
    return jsonify(metrics.to_dict())
