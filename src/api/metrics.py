from flask import Blueprint, request, jsonify
from src.services import spanner_eval
from src.core.database import get_eval_db, T_LLM_CALL_LOGS
from google.cloud.spanner_v1 import param_types

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


@bp.get("/llm-calls/<run_id>")
def llm_calls(run_id):
    """Return all LLM call records for a run, ordered by called_at."""
    rows = []
    with get_eval_db().snapshot() as snapshot:
        for row in snapshot.execute_sql(
            f"SELECT id, question_id, call_type, model, input_tokens, output_tokens, "
            f"total_tokens, latency_ms, called_at "
            f"FROM {T_LLM_CALL_LOGS} "
            "WHERE run_id = @run_id ORDER BY called_at ASC",
            params={"run_id": run_id},
            param_types={"run_id": param_types.STRING},
        ):
            rows.append({
                "id": row[0], "question_id": row[1], "call_type": row[2],
                "model": row[3], "input_tokens": row[4], "output_tokens": row[5],
                "total_tokens": row[6], "latency_ms": row[7],
                "called_at": row[8].isoformat() if row[8] else None,
            })
    return jsonify(rows)


@bp.get("/llm-summary/<run_id>")
def llm_summary(run_id):
    """Aggregate LLM call stats for a run, broken down by call_type."""
    summary: dict[str, dict] = {}
    totals = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "latency_ms": 0}

    with get_eval_db().snapshot() as snapshot:
        for row in snapshot.execute_sql(
            f"SELECT call_type, COUNT(*), SUM(input_tokens), SUM(output_tokens), "
            f"SUM(total_tokens), AVG(latency_ms) "
            f"FROM {T_LLM_CALL_LOGS} WHERE run_id = @run_id GROUP BY call_type",
            params={"run_id": run_id},
            param_types={"run_id": param_types.STRING},
        ):
            call_type, count, inp, out, total, avg_lat = row
            summary[call_type] = {
                "calls": count,
                "input_tokens": inp or 0,
                "output_tokens": out or 0,
                "total_tokens": total or 0,
                "avg_latency_ms": round(avg_lat, 1) if avg_lat else None,
            }
            totals["calls"] += count
            totals["input_tokens"] += inp or 0
            totals["output_tokens"] += out or 0
            totals["total_tokens"] += total or 0
            totals["latency_ms"] += (avg_lat or 0) * count

    totals["avg_latency_ms"] = round(totals["latency_ms"] / totals["calls"], 1) if totals["calls"] else None
    del totals["latency_ms"]

    return jsonify({"totals": totals, "by_call_type": summary})
