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


@bp.get("/compare-stratum")
def compare_stratum():
    """Filtered metrics for a set of runs scoped to a specific stratum combination.

    Query params:
      run_ids  — comma-separated run IDs (required)
      table    — filter by table_name (optional)
      task     — filter by task (optional)
      tone     — filter by tone_snapshot (optional)
    """
    raw = request.args.get("run_ids", "")
    run_ids = [r.strip() for r in raw.split(",") if r.strip()]
    if not run_ids:
        return jsonify({"error": "run_ids required"}), 400

    table = request.args.get("table") or None
    task = request.args.get("task") or None
    tone = request.args.get("tone") or None

    from src.core.database import T_RESULTS, T_QUESTIONS
    placeholders = ", ".join(f"@id{i}" for i in range(len(run_ids)))
    params = {f"id{i}": v for i, v in enumerate(run_ids)}
    pt = {f"id{i}": param_types.STRING for i in range(len(run_ids))}

    conditions = [f"res.run_id IN ({placeholders})"]
    if table:
        conditions.append("q.table_name = @table")
        params["table"] = table
        pt["table"] = param_types.STRING
    if task:
        conditions.append("q.task = @task")
        params["task"] = task
        pt["task"] = param_types.STRING
    if tone:
        conditions.append("res.tone_snapshot = @tone")
        params["tone"] = tone
        pt["tone"] = param_types.STRING

    where = " AND ".join(conditions)
    sql = (
        f"SELECT res.run_id, res.outcome, COUNT(*) as cnt, AVG(res.runtime_ms) as avg_rt "
        f"FROM {T_RESULTS} res JOIN {T_QUESTIONS} q ON res.question_id = q.id "
        f"WHERE {where} GROUP BY res.run_id, res.outcome"
    )

    rows: dict[str, dict] = {}
    with get_eval_db().snapshot() as snapshot:
        for row in snapshot.execute_sql(sql, params=params, param_types=pt):
            run_id, outcome, cnt, avg_rt = row
            if run_id not in rows:
                rows[run_id] = {"run_id": run_id, "total": 0, "count_passed": 0,
                                "count_failed": 0, "count_rule_violation": 0,
                                "count_low_conf_pass": 0, "avg_runtime_ms": None, "_rt_sum": 0, "_rt_n": 0}
            rows[run_id]["total"] += cnt
            rows[run_id][f"count_{outcome}"] = rows[run_id].get(f"count_{outcome}", 0) + cnt
            if avg_rt:
                rows[run_id]["_rt_sum"] += avg_rt * cnt
                rows[run_id]["_rt_n"] += cnt

    runs = {r.id: r for r in spanner_eval.list_runs(limit=200) if r.id in run_ids}
    result = []
    for run_id in run_ids:
        d = rows.get(run_id, {"run_id": run_id, "total": 0, "count_passed": 0,
                               "count_failed": 0, "count_rule_violation": 0, "count_low_conf_pass": 0})
        total = d["total"]
        d["pct_passed"] = round(d["count_passed"] / total * 100, 2) if total else 0
        d["pct_failed"] = round(d["count_failed"] / total * 100, 2) if total else 0
        d["pct_rule_violation"] = round(d.get("count_rule_violation", 0) / total * 100, 2) if total else 0
        rt_n = d.pop("_rt_n", 0)
        rt_sum = d.pop("_rt_sum", 0)
        d["avg_runtime_ms"] = round(rt_sum / rt_n, 2) if rt_n else None
        run = runs.get(run_id)
        d["run_name"] = run.name if run else None
        result.append(d)
    return jsonify(result)


@bp.get("/compare-questions")
def compare_questions():
    """Search for questions across selected runs and return per-run results.

    Query params:
      run_ids — comma-separated run IDs (required)
      q       — search string: substring match on nlq_snapshot, or question_id prefix (required)
    """
    raw = request.args.get("run_ids", "")
    run_ids = [r.strip() for r in raw.split(",") if r.strip()]
    q = (request.args.get("q") or "").strip()
    if not run_ids or not q:
        return jsonify({"error": "run_ids and q are required"}), 400

    from src.core.database import T_RESULTS
    placeholders = ", ".join(f"@id{i}" for i in range(len(run_ids)))
    params = {f"id{i}": v for i, v in enumerate(run_ids)}
    pt = {f"id{i}": param_types.STRING for i in range(len(run_ids))}

    # UUID-prefix search vs NLQ text search
    import re
    is_id_search = bool(re.match(r'^[0-9a-f\-]{4,}$', q, re.IGNORECASE))
    if is_id_search:
        conditions = f"res.run_id IN ({placeholders}) AND STARTS_WITH(res.question_id, @q)"
    else:
        conditions = f"res.run_id IN ({placeholders}) AND LOWER(res.nlq_snapshot) LIKE @q"
        q = f"%{q.lower()}%"

    params["q"] = q
    pt["q"] = param_types.STRING

    cols = ("res.run_id, res.id, res.question_id, res.nlq_snapshot, res.tone_snapshot, "
            "res.outcome, res.sql_generated, res.judge_verdict, res.judge_confidence, "
            "res.judge_reasoning, res.runtime_ms, res.route, res.error_message")
    sql = (f"SELECT {cols} FROM {T_RESULTS} res "
           f"WHERE {conditions} ORDER BY res.question_id, res.run_id LIMIT 300")

    by_question: dict[str, dict] = {}
    with get_eval_db().snapshot() as snapshot:
        for row in snapshot.execute_sql(sql, params=params, param_types=pt):
            (run_id, res_id, question_id, nlq, tone, outcome, sql_gen,
             verdict, confidence, reasoning, runtime_ms, route, error) = row
            if question_id not in by_question:
                by_question[question_id] = {"question_id": question_id, "nlq": nlq,
                                            "tone": tone, "results": {}}
            by_question[question_id]["results"][run_id] = {
                "result_id": res_id, "outcome": outcome,
                "sql_generated": sql_gen, "judge_verdict": verdict,
                "judge_confidence": confidence, "judge_reasoning": reasoning,
                "runtime_ms": runtime_ms, "route": route, "error_message": error,
            }

    return jsonify(list(by_question.values()))


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
