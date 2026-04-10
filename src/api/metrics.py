from flask import Blueprint, request, jsonify
from src.services import spanner_eval

bp = Blueprint("metrics", __name__, url_prefix="/api/metrics")


@bp.get("/compare")
def compare_runs():
    raw = request.args.get("run_ids", "")
    run_ids = [r.strip() for r in raw.split(",") if r.strip()]
    if not run_ids:
        return jsonify({"error": "Provide run_ids as comma-separated query param"}), 400
    if len(run_ids) > 10:
        return jsonify({"error": "Maximum 10 runs per comparison"}), 400

    metrics_list = spanner_eval.get_metrics_for_runs(run_ids)
    runs = {r.id: r for r in spanner_eval.list_runs(limit=200) if r.id in run_ids}

    result = []
    for m in metrics_list:
        run = runs.get(m.run_id)
        d = m.to_dict()
        d["run_name"] = run.name if run else None
        d["run_status"] = run.status if run else None
        d["completed_at"] = run.to_dict()["completed_at"] if run else None
        result.append(d)

    return jsonify(result)


@bp.get("/breakdown/<run_id>")
def get_breakdown(run_id):
    metrics = spanner_eval.get_run_metrics(run_id)
    if not metrics:
        return jsonify({"error": "Metrics not yet computed"}), 404
    return jsonify(metrics.metrics_json or {})


@bp.get("/timeseries")
def timeseries():
    limit = int(request.args.get("limit", 50))
    return jsonify(spanner_eval.get_timeseries_metrics(limit=limit))
