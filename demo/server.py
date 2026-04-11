"""
Demo server — serves realistic fake data for all API endpoints.

No GCP credentials, Spanner connection, or Vertex AI required.
All state is in-memory and resets when the server restarts.

Usage:
    python demo/server.py

Then in a separate terminal:
    cd frontend && npm run dev

Dashboard: http://localhost:3000
"""
import csv
import io
import random
import time
import uuid
from datetime import datetime, timedelta, timezone

from flask import Flask, Response, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

random.seed(42)


# ── Time helpers ───────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _ago(**kwargs) -> datetime:
    return _now() - timedelta(**kwargs)


# ── Static reference data ──────────────────────────────────────────────────────

TABLES = ["orders", "products", "customers", "inventory", "transactions"]
TONES = ["casual", "neutral", "formal"]

# Representative NLQs per (table, task, tone)
_NLQ_MAP = {
    ("orders", "aggregate_sum", "casual"):   "total revenue last month?",
    ("orders", "aggregate_sum", "neutral"):  "What was the total revenue for last month?",
    ("orders", "aggregate_sum", "formal"):   "What is the aggregate total revenue for the preceding calendar month, categorized by payment method?",
    ("orders", "filter_by_date", "casual"):  "orders from last week",
    ("orders", "filter_by_date", "neutral"): "Show me all orders placed in the last 7 days.",
    ("orders", "filter_by_date", "formal"):  "Retrieve all order records with a placement timestamp within the trailing 7-day period.",
    ("orders", "rank_top_n", "casual"):      "top 10 customers by spend",
    ("orders", "rank_top_n", "neutral"):     "Who are the top 10 customers by total spend?",
    ("orders", "rank_top_n", "formal"):      "Identify the ten customers with the highest aggregate order value, sorted in descending order.",
    ("products", "filter_by_category", "casual"):  "electronics under $200",
    ("products", "filter_by_category", "neutral"): "Show all electronics products priced under $200.",
    ("products", "filter_by_category", "formal"):  "Retrieve all products classified under the Electronics category with a listed price below $200.",
    ("products", "aggregate_count", "casual"):     "how many products are out of stock",
    ("products", "aggregate_count", "neutral"):    "How many products are currently out of stock?",
    ("products", "aggregate_count", "formal"):     "What is the total count of products with a current inventory quantity of zero?",
    ("products", "join_related_table", "casual"):  "products with their supplier names",
    ("products", "join_related_table", "neutral"): "List all products along with the name of their supplier.",
    ("products", "join_related_table", "formal"):  "Retrieve all product records joined with their associated supplier names from the supplier reference table.",
    ("customers", "filter_by_date", "casual"):     "new customers this month",
    ("customers", "filter_by_date", "neutral"):    "How many new customers signed up this month?",
    ("customers", "filter_by_date", "formal"):     "How many customer accounts were created during the current calendar month?",
    ("customers", "aggregate_count", "casual"):    "customers by region",
    ("customers", "aggregate_count", "neutral"):   "How many customers do we have in each region?",
    ("customers", "aggregate_count", "formal"):    "Provide a count of active customer accounts grouped by geographic region.",
    ("customers", "search_by_name", "casual"):     "find customers named Smith",
    ("customers", "search_by_name", "neutral"):    "Find all customers with the last name Smith.",
    ("customers", "search_by_name", "formal"):     "Retrieve all customer records where the surname field contains the value 'Smith'.",
    ("inventory", "trend_over_time", "casual"):    "inventory levels past 90 days",
    ("inventory", "trend_over_time", "neutral"):   "Show inventory levels over the past 90 days.",
    ("inventory", "trend_over_time", "formal"):    "Provide a time-series view of inventory quantity levels aggregated by week over the preceding 90-day period.",
    ("transactions", "aggregate_sum", "casual"):   "total transaction volume today",
    ("transactions", "aggregate_sum", "neutral"):  "What is the total transaction volume for today?",
    ("transactions", "aggregate_sum", "formal"):   "Calculate the aggregate monetary value of all transactions processed during the current calendar day.",
}

_SQL_MAP = {
    ("orders", "aggregate_sum"):
        "SELECT payment_method, SUM(total_amount) AS total_revenue\nFROM orders\nWHERE order_date >= DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 1 MONTH), MONTH)\n  AND order_date < DATE_TRUNC(CURRENT_DATE(), MONTH)\nGROUP BY payment_method",
    ("orders", "filter_by_date"):
        "SELECT *\nFROM orders\nWHERE order_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)\nORDER BY order_date DESC",
    ("orders", "rank_top_n"):
        "SELECT customer_id, SUM(total_amount) AS total_spend\nFROM orders\nGROUP BY customer_id\nORDER BY total_spend DESC\nLIMIT 10",
    ("products", "filter_by_category"):
        "SELECT *\nFROM products\nWHERE category = 'Electronics'\n  AND price < 200",
    ("products", "aggregate_count"):
        "SELECT COUNT(*) AS out_of_stock_count\nFROM products\nWHERE stock_quantity = 0",
    ("products", "join_related_table"):
        "SELECT p.product_name, p.sku, s.supplier_name\nFROM products p\nJOIN suppliers s ON p.supplier_id = s.id",
    ("customers", "filter_by_date"):
        "SELECT COUNT(*) AS new_customers\nFROM customers\nWHERE created_at >= DATE_TRUNC(CURRENT_DATE(), MONTH)",
    ("customers", "aggregate_count"):
        "SELECT region, COUNT(*) AS customer_count\nFROM customers\nGROUP BY region\nORDER BY customer_count DESC",
    ("customers", "search_by_name"):
        "SELECT *\nFROM customers\nWHERE LOWER(last_name) = 'smith'\nORDER BY last_name, first_name",
    ("inventory", "trend_over_time"):
        "SELECT DATE_TRUNC(recorded_at, WEEK) AS week, AVG(quantity) AS avg_quantity\nFROM inventory\nWHERE recorded_at >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)\nGROUP BY week\nORDER BY week",
    ("transactions", "aggregate_sum"):
        "SELECT SUM(amount) AS total_volume, COUNT(*) AS transaction_count\nFROM transactions\nWHERE DATE(processed_at) = CURRENT_DATE()",
}

_PASS_REASONINGS = [
    "The SQL correctly implements the requested aggregation with appropriate date filtering. The GROUP BY clause matches the question's intent and all business rules are satisfied.",
    "Query correctly identifies the target table and applies the specified filter conditions. The ORDER BY and LIMIT clauses properly implement the ranking requirement.",
    "The JOIN operation correctly relates the two tables using the expected foreign key relationship. Column selections match what the question is asking for.",
    "Aggregation function and grouping are correct. Date truncation logic matches the business intent of the question.",
    "The WHERE clause correctly filters by the specified category and price constraint. No business rule violations detected.",
    "The SQL uses the correct table and applies appropriate search conditions. Case-insensitive comparison is correctly handled via LOWER().",
    "Time-series aggregation is correctly implemented with DATE_TRUNC. The 90-day interval matches the requested window and the weekly grouping is appropriate.",
]

_LOW_CONF_REASONINGS = [
    "The SQL structure is correct but the question uses informal phrasing that could be interpreted as either a filter or an aggregation. Confidence reduced accordingly.",
    "Query returns the right general shape but the date range interpretation is slightly ambiguous given the casual phrasing of the question.",
    "Approach is sound but the question's intent around grouping granularity is unclear, resulting in a conservative confidence estimate.",
]

_FAIL_REASONINGS = [
    "The SQL uses a hardcoded date literal instead of a relative date function. Results would be incorrect outside the current date context.",
    "The JOIN condition is missing an ON clause, which would produce a Cartesian product rather than the intended joined result set.",
    "The aggregate function is applied to a non-numeric column. This violates the data dictionary schema for this table.",
    "The WHERE clause filters on the wrong column, which does not match the business intent of the question as stated.",
]


# ── Build question bank ────────────────────────────────────────────────────────

QUESTIONS: dict[str, dict] = {}

for _i, ((tbl, task, tone), nlq) in enumerate(_NLQ_MAP.items()):
    _qid = f"q-{_i + 1:04d}"
    _checked = _i < 26
    _check_id = f"lc-{_i + 1:04d}" if _checked else None
    _status = "active" if _i < 23 else ("monitoring" if _i < 28 else "deleted")
    QUESTIONS[_qid] = {
        "id": _qid,
        "nlq": nlq,
        "table_name": tbl,
        "task": task,
        "tone": tone,
        "status": _status,
        "is_seeded": _i % 3 != 0,
        "leakage_checked": _checked,
        "leakage_check_id": _check_id,
        "notes": "Auto-seeded via HyDE seeder." if _i % 3 != 0 else None,
        "created_at": _iso(_ago(days=random.randint(3, 30))),
        "updated_at": _iso(_ago(days=random.randint(0, 3))),
        "leakage_check": {
            "id": _check_id,
            "question_id": _qid,
            "embedding_flagged": False,
            "embedding_max_sim": round(random.uniform(0.25, 0.68), 4),
            "embedding_match_text": None,
            "llm_flagged": False,
            "llm_reasoning": "No substantial similarity found in agent prompt examples.",
            "overall_passed": True,
            "checked_at": _iso(_ago(days=random.randint(0, 10))),
        } if _checked else None,
    }

ELIGIBLE_IDS = [
    qid for qid, q in QUESTIONS.items()
    if q["status"] in ("active", "monitoring") and q["leakage_checked"]
]


# ── Result / metrics factory ───────────────────────────────────────────────────

_ROUTES = ["text_to_sql_direct", "schema_selector_join", "text_to_sql_direct", "text_to_sql_direct"]


def _make_results(run_id: str, q_ids: list[str], pass_rate: float) -> list[dict]:
    results = []
    for i, qid in enumerate(q_ids):
        q = QUESTIONS.get(qid, {})
        tbl = q.get("table_name", "orders")
        task = q.get("task", "aggregate_sum")
        tone = q.get("tone", "neutral")
        sql_key = (tbl, task)
        roll = random.random()
        if roll < pass_rate:
            outcome, verdict = "passed", "pass"
            confidence = round(random.uniform(0.77, 0.99), 2)
            reasoning = random.choice(_PASS_REASONINGS)
        elif roll < pass_rate + 0.09:
            outcome, verdict = "low_confidence_pass", "pass"
            confidence = round(random.uniform(0.55, 0.74), 2)
            reasoning = random.choice(_LOW_CONF_REASONINGS)
        elif roll < pass_rate + 0.09 + 0.07:
            outcome, verdict = "rule_violation", "fail"
            confidence = round(random.uniform(0.80, 0.99), 2)
            reasoning = random.choice(_FAIL_REASONINGS)
        else:
            outcome, verdict = "failed", None
            confidence, reasoning = None, None
        sql = _SQL_MAP.get(sql_key) if outcome != "failed" else None
        results.append({
            "run_id": run_id,
            "id": f"res-{run_id[-4:]}-{i + 1:04d}",
            "question_id": qid,
            "nlq_snapshot": q.get("nlq", ""),
            "tone_snapshot": tone,
            "outcome": outcome,
            "sql_generated": sql,
            "agent_response": f"Based on your question, here is what I found:\n\n{sql}" if sql else None,
            "judge_verdict": verdict,
            "judge_confidence": confidence,
            "judge_reasoning": reasoning,
            "runtime_ms": random.randint(1100, 9200),
            "route": random.choice(_ROUTES),
            "join_count": sql.upper().count(" JOIN ") if sql else 0,
            "error_message": "ADK request timed out after 30000ms" if outcome == "failed" and random.random() > 0.4 else None,
            "completed_at": _iso(_ago(minutes=random.randint(2, 120))),
        })
    return results


def _make_metrics(run_id: str, run_name: str, completed_at: datetime, results: list[dict]) -> dict:
    total = len(results)
    counts = {o: sum(1 for r in results if r["outcome"] == o)
              for o in ("passed", "failed", "rule_violation", "low_confidence_pass")}
    runtimes = [r["runtime_ms"] for r in results if r["runtime_ms"]]
    by_route: dict = {}
    by_table: dict = {}
    by_task: dict = {}
    by_tone: dict = {}
    by_joins: dict = {}
    for r in results:
        q = QUESTIONS.get(r["question_id"], {})
        for bucket, key in [
            (by_route, r.get("route") or "unknown"),
            (by_table, q.get("table_name", "unknown")),
            (by_task, q.get("task", "unknown")),
            (by_tone, r.get("tone_snapshot") or "neutral"),
            (by_joins, str(r.get("join_count", 0))),
        ]:
            if key not in bucket:
                bucket[key] = {"total": 0, "passed": 0, "failed": 0,
                               "rule_violation": 0, "low_confidence_pass": 0}
            bucket[key]["total"] += 1
            bucket[key][r["outcome"]] += 1
    return {
        "run_id": run_id,
        "run_name": run_name,
        "completed_at": _iso(completed_at),
        "total": total,
        "count_passed": counts["passed"],
        "count_failed": counts["failed"],
        "count_rule_violation": counts["rule_violation"],
        "count_low_conf_pass": counts["low_confidence_pass"],
        "pct_passed": round(counts["passed"] / total * 100, 1) if total else 0.0,
        "pct_failed": round(counts["failed"] / total * 100, 1) if total else 0.0,
        "pct_rule_violation": round(counts["rule_violation"] / total * 100, 1) if total else 0.0,
        "avg_runtime_ms": round(sum(runtimes) / len(runtimes)) if runtimes else None,
        "metrics_json": {
            "by_route": by_route,
            "by_table": by_table,
            "by_task": by_task,
            "by_tone": by_tone,
            "by_joins": by_joins,
        },
        "computed_at": _iso(_ago(seconds=30)),
    }


def _make_llm_calls(run_id: str, n: int) -> list[dict]:
    calls = []
    t0 = _ago(minutes=n * 0.35 + 3)
    for i in range(n):
        inp = random.randint(900, 2400)
        out = random.randint(60, 280)
        calls.append({
            "id": f"llm-{run_id[-4:]}-j-{i + 1:04d}",
            "question_id": ELIGIBLE_IDS[i % len(ELIGIBLE_IDS)],
            "call_type": "judge",
            "model": "gemini-2.0-flash",
            "input_tokens": inp,
            "output_tokens": out,
            "total_tokens": inp + out,
            "latency_ms": random.randint(500, 4000),
            "called_at": _iso(t0 + timedelta(seconds=i * 20 + random.randint(0, 8))),
        })
    # A handful of seeder/hyde calls before the eval started
    for j in range(min(8, n // 6)):
        inp = random.randint(300, 800)
        out = random.randint(150, 500)
        ct = "seed_generate" if j % 3 == 0 else ("hyde_hypothetical" if j % 3 == 1 else "leakage_llm")
        calls.append({
            "id": f"llm-{run_id[-4:]}-s-{j + 1:04d}",
            "question_id": None,
            "call_type": ct,
            "model": "gemini-2.0-flash",
            "input_tokens": inp,
            "output_tokens": out,
            "total_tokens": inp + out,
            "latency_ms": random.randint(300, 1800),
            "called_at": _iso(t0 - timedelta(minutes=j + 1)),
        })
    calls.sort(key=lambda c: c["called_at"])
    return calls


# ── Seed completed runs ────────────────────────────────────────────────────────

RUNS: dict[str, dict] = {}
RESULTS: dict[str, list[dict]] = {}
RUN_METRICS: dict[str, dict] = {}
LLM_CALLS: dict[str, list[dict]] = {}

_RUN_SPECS = [
    ("run-0001", "Baseline v1.0",        50, 0.74, _ago(days=21)),
    ("run-0002", "Baseline v1.1",        50, 0.80, _ago(days=14)),
    ("run-0003", "After schema fix",     50, 0.72, _ago(days=10)),
    ("run-0004", "Post-prompt tuning",   50, 0.86, _ago(days=7)),
    ("run-0005", "Regression check",     25, 0.60, _ago(days=5)),
    ("run-0006", "Nightly eval v2.2",    50, 0.88, _ago(days=3)),
    ("run-0007", "Nightly eval v2.3",    50, 0.92, _ago(days=1)),
]

for _rid, _name, _n, _pr, _completed in _RUN_SPECS:
    _qids = (ELIGIBLE_IDS * 10)[:_n]
    _res = _make_results(_rid, _qids, _pr)
    _metrics = _make_metrics(_rid, _name, _completed, _res)
    _llm = _make_llm_calls(_rid, _n)
    _started = _completed - timedelta(minutes=_n * 0.4)
    RUNS[_rid] = {
        "id": _rid, "name": _name, "status": "completed",
        "started_at": _iso(_started),
        "completed_at": _iso(_completed),
        "last_heartbeat": _iso(_completed),
        "total_questions": _n,
        "resume_count": 0,
        "created_at": _iso(_started - timedelta(minutes=3)),
        "progress": {"completed": _n, "total": _n},
    }
    RESULTS[_rid] = _res
    RUN_METRICS[_rid] = _metrics
    LLM_CALLS[_rid] = _llm

# A run that was resumed (shows resume_count > 0)
_res_r = _make_results("run-0008", (ELIGIBLE_IDS * 10)[:50], 0.84)
_metrics_r = _make_metrics("run-0008", "Recovered nightly", _ago(days=8), _res_r)
RUNS["run-0008"] = {
    "id": "run-0008", "name": "Recovered nightly", "status": "completed",
    "started_at": _iso(_ago(days=9)),
    "completed_at": _iso(_ago(days=8)),
    "last_heartbeat": _iso(_ago(days=8)),
    "total_questions": 50, "resume_count": 2,
    "created_at": _iso(_ago(days=9, minutes=5)),
    "progress": {"completed": 50, "total": 50},
}
RESULTS["run-0008"] = _res_r
RUN_METRICS["run-0008"] = _metrics_r
LLM_CALLS["run-0008"] = _make_llm_calls("run-0008", 50)

# A failed run
RUNS["run-0009"] = {
    "id": "run-0009", "name": "Failed run", "status": "failed",
    "started_at": _iso(_ago(days=6, hours=2)),
    "completed_at": None, "last_heartbeat": _iso(_ago(days=6, hours=2)),
    "total_questions": 0, "resume_count": 0,
    "created_at": _iso(_ago(days=6, hours=2, minutes=3)),
    "progress": None,
}

# Two pending runs available to "start"
RUNS["run-0010"] = {
    "id": "run-0010", "name": "Scheduled nightly", "status": "pending",
    "started_at": None, "completed_at": None, "last_heartbeat": None,
    "total_questions": None, "resume_count": 0,
    "created_at": _iso(_ago(hours=2)),
    "progress": None,
}
RUNS["run-0011"] = {
    "id": "run-0011", "name": "Demo run (start me!)", "status": "pending",
    "started_at": None, "completed_at": None, "last_heartbeat": None,
    "total_questions": None, "resume_count": 0,
    "created_at": _iso(_ago(minutes=15)),
    "progress": None,
}

# Tracks unix timestamp when a run was "started" so we can simulate progress
_RUNNING_STARTS: dict[str, float] = {}
_DEMO_RUN_Q_COUNT = 50


# ── Review items ───────────────────────────────────────────────────────────────

REVIEW_ITEMS: dict[str, dict] = {}
_low_conf = [r for res_list in RESULTS.values() for r in res_list if r["outcome"] == "low_confidence_pass"][:12]
for _ri, _r in enumerate(_low_conf):
    _riid = f"rev-{_ri + 1:04d}"
    _reviewed = _ri < 4
    REVIEW_ITEMS[_riid] = {
        "id": _riid,
        "result_id": _r["id"],
        "run_id": _r["run_id"],
        "question_id": _r["question_id"],
        "nlq_snapshot": _r["nlq_snapshot"],
        "judge_confidence": _r["judge_confidence"],
        "judge_reasoning": _r["judge_reasoning"],
        "reviewer": "alice@example.com" if _reviewed else None,
        "review_decision": ("confirmed_pass" if _ri < 3 else "override_fail") if _reviewed else None,
        "review_notes": (
            "Verified against production data — correct."
            if _ri < 3
            else "SQL produces incorrect date range for this question."
        ) if _reviewed else None,
        "created_at": _r["completed_at"],
        "reviewed_at": _iso(_ago(hours=random.randint(2, 72))) if _reviewed else None,
    }

# ── Strata ─────────────────────────────────────────────────────────────────────

STRATA: list[dict] = []
for _tbl in ("orders", "products", "customers"):
    for _task in ("aggregate_sum", "filter_by_date", "rank_top_n", "filter_by_category"):
        for _tone in TONES:
            _cur = len([
                q for q in QUESTIONS.values()
                if q["table_name"] == _tbl and q["task"] == _task
                and q["tone"] == _tone and q["status"] == "active"
            ])
            _target = 7
            STRATA.append({
                "table_name": _tbl, "task": _task, "tone": _tone,
                "description": f"{_task.replace('_', ' ').title()} on {_tbl} ({_tone} tone)",
                "current_count": _cur,
                "target_count": _target,
                "needed": max(0, _target - _cur),
            })


# ── Run view helper (simulates progress for running runs) ──────────────────────

def _run_view(run: dict) -> dict:
    r = dict(run)
    rid = r["id"]
    if rid in _RUNNING_STARTS:
        elapsed = time.time() - _RUNNING_STARTS[rid]
        total = _DEMO_RUN_Q_COUNT
        # simulate ~10 seconds per question
        completed = min(total, int(elapsed / 10))
        r["progress"] = {"completed": completed, "total": total}
        r["total_questions"] = total
        r["status"] = "running"
        r["last_heartbeat"] = _iso(_now())
        if completed >= total:
            # auto-complete
            r["status"] = "completed"
            r["completed_at"] = _iso(_now())
            del _RUNNING_STARTS[rid]
            RUNS[rid]["status"] = "completed"
            RUNS[rid]["completed_at"] = r["completed_at"]
            RUNS[rid]["progress"] = {"completed": total, "total": total}
            if rid not in RESULTS:
                _qids = (ELIGIBLE_IDS * 10)[:total]
                _res = _make_results(rid, _qids, 0.88)
                RESULTS[rid] = _res
                RUN_METRICS[rid] = _make_metrics(rid, run["name"] or rid, _now(), _res)
                LLM_CALLS[rid] = _make_llm_calls(rid, total)
    return r


# ════════════════════════════════════════════════════════════════════════════════
# API Routes
# ════════════════════════════════════════════════════════════════════════════════

@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "mode": "demo"})


@app.get("/api/config")
def config():
    return jsonify({
        "embedding_model": "text-embedding-004",
        "judge_model": "gemini-2.0-flash",
        "leakage_embedding_threshold": 0.85,
        "judge_confidence_threshold": 0.75,
        "run_concurrency": 4,
        "seeder_active_count": 7,
        "seeder_monitoring_count": 2,
        "heartbeat_interval_seconds": 60,
        "heartbeat_stale_minutes": 5,
    })


# ── Questions ──────────────────────────────────────────────────────────────────

@app.get("/api/questions")
def list_questions():
    qs = list(QUESTIONS.values())
    if s := request.args.get("status"):
        qs = [q for q in qs if q["status"] == s]
    if t := request.args.get("table_name"):
        qs = [q for q in qs if q["table_name"] == t]
    if t := request.args.get("task"):
        qs = [q for q in qs if q["task"] == t]
    if t := request.args.get("tone"):
        qs = [q for q in qs if q["tone"] == t]
    if lc := request.args.get("leakage_checked"):
        want = lc.lower() == "true"
        qs = [q for q in qs if q["leakage_checked"] == want]
    return jsonify(qs)


@app.get("/api/questions/export.csv")
def export_questions_csv():
    out = io.StringIO()
    fields = ["id", "nlq", "table_name", "task", "tone", "status", "notes"]
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    for q in QUESTIONS.values():
        writer.writerow({k: q.get(k, "") or "" for k in fields})
    return Response(
        out.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=questions.csv"},
    )


@app.post("/api/questions/import-csv")
def import_questions_csv():
    return jsonify({"imported": 0, "skipped": 0, "errors": []})


@app.post("/api/questions/check-leakage-batch")
def check_leakage_batch():
    unchecked = [q for q in QUESTIONS.values() if not q["leakage_checked"]]
    for q in unchecked:
        _cid = str(uuid.uuid4())
        q["leakage_checked"] = True
        q["leakage_check_id"] = _cid
        q["leakage_check"] = {
            "id": _cid, "question_id": q["id"],
            "embedding_flagged": False,
            "embedding_max_sim": round(random.uniform(0.2, 0.65), 4),
            "embedding_match_text": None,
            "llm_flagged": False,
            "llm_reasoning": "No substantial similarity found.",
            "overall_passed": True,
            "checked_at": _iso(_now()),
        }
    return jsonify({"processed": len(unchecked), "errors": []})


@app.get("/api/questions/<qid>")
def get_question(qid):
    q = QUESTIONS.get(qid)
    return (jsonify(q) if q else (jsonify({"error": "Not found"}), 404))


@app.post("/api/questions")
def create_question():
    body = request.get_json() or {}
    qid = str(uuid.uuid4())
    q = {
        "id": qid,
        "nlq": body.get("nlq", ""),
        "table_name": body.get("table_name", ""),
        "task": body.get("task", ""),
        "tone": body.get("tone", "neutral"),
        "status": body.get("status", "active"),
        "is_seeded": False,
        "leakage_checked": False,
        "leakage_check_id": None,
        "notes": body.get("notes"),
        "created_at": _iso(_now()),
        "updated_at": _iso(_now()),
        "leakage_check": None,
    }
    QUESTIONS[qid] = q
    return jsonify(q), 201


@app.put("/api/questions/<qid>")
def update_question(qid):
    q = QUESTIONS.get(qid)
    if not q:
        return jsonify({"error": "Not found"}), 404
    body = request.get_json() or {}
    for field in ("nlq", "status", "notes", "table_name", "task", "tone"):
        if field in body:
            q[field] = body[field]
    q["updated_at"] = _iso(_now())
    return jsonify(q)


@app.delete("/api/questions/<qid>")
def delete_question(qid):
    if qid not in QUESTIONS:
        return jsonify({"error": "Not found"}), 404
    QUESTIONS[qid]["status"] = "deleted"
    return jsonify({"deleted": qid})


@app.post("/api/questions/<qid>/check-leakage")
def check_leakage_single(qid):
    q = QUESTIONS.get(qid)
    if not q:
        return jsonify({"error": "Not found"}), 404
    time.sleep(0.6)  # simulate API latency
    cid = str(uuid.uuid4())
    lc = {
        "id": cid, "question_id": qid,
        "embedding_flagged": False,
        "embedding_max_sim": round(random.uniform(0.2, 0.65), 4),
        "embedding_match_text": None,
        "llm_flagged": False,
        "llm_reasoning": "No substantial similarity found in agent prompt examples.",
        "overall_passed": True,
        "checked_at": _iso(_now()),
    }
    q.update(leakage_checked=True, leakage_check_id=cid, leakage_check=lc)
    return jsonify(lc)


# ── Runs ───────────────────────────────────────────────────────────────────────

@app.get("/api/runs")
def list_runs():
    limit = int(request.args.get("limit", 20))
    runs = sorted(RUNS.values(), key=lambda r: r["created_at"], reverse=True)[:limit]
    return jsonify([_run_view(r) for r in runs])


@app.get("/api/runs/<run_id>")
def get_run(run_id):
    run = RUNS.get(run_id)
    return (jsonify(_run_view(run)) if run else (jsonify({"error": "Not found"}), 404))


@app.post("/api/runs")
def create_run():
    body = request.get_json() or {}
    rid = str(uuid.uuid4())[:8]
    run = {
        "id": rid,
        "name": body.get("name") or f"Run {rid[:4]}",
        "status": "pending",
        "started_at": None, "completed_at": None, "last_heartbeat": None,
        "total_questions": None, "resume_count": 0,
        "created_at": _iso(_now()),
        "progress": None,
    }
    RUNS[rid] = run
    return jsonify(_run_view(run)), 201


@app.post("/api/runs/<run_id>/start")
def start_run(run_id):
    run = RUNS.get(run_id)
    if not run:
        return jsonify({"error": "Not found"}), 404
    run.update(status="running", started_at=_iso(_now()),
               total_questions=_DEMO_RUN_Q_COUNT,
               progress={"completed": 0, "total": _DEMO_RUN_Q_COUNT})
    _RUNNING_STARTS[run_id] = time.time()
    return jsonify({"started": run_id})


@app.post("/api/runs/<run_id>/cancel")
def cancel_run(run_id):
    run = RUNS.get(run_id)
    if not run:
        return jsonify({"error": "Not found"}), 404
    run["status"] = "cancelled"
    _RUNNING_STARTS.pop(run_id, None)
    return jsonify({"cancelled": run_id})


@app.delete("/api/runs/<run_id>")
def delete_run(run_id):
    if run_id not in RUNS:
        return jsonify({"error": "Not found"}), 404
    del RUNS[run_id]
    return jsonify({"deleted": run_id})


@app.get("/api/runs/<run_id>/results")
def get_results(run_id):
    all_res = RESULTS.get(run_id, [])
    if oc := request.args.get("outcome"):
        all_res = [r for r in all_res if r["outcome"] == oc]
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 50))
    start = (page - 1) * page_size
    return jsonify(all_res[start: start + page_size])


@app.get("/api/runs/<run_id>/metrics")
def get_run_metrics(run_id):
    m = RUN_METRICS.get(run_id)
    return (jsonify(m) if m else (jsonify({"error": "Metrics not yet computed"}), 404))


# ── Metrics ────────────────────────────────────────────────────────────────────

@app.get("/api/metrics/compare")
def compare_runs():
    raw = request.args.get("run_ids", "")
    ids = [r.strip() for r in raw.split(",") if r.strip()]
    return jsonify([m for rid in ids if (m := RUN_METRICS.get(rid))])


@app.get("/api/metrics/breakdown/<run_id>")
def get_breakdown(run_id):
    m = RUN_METRICS.get(run_id)
    return (jsonify(m["metrics_json"] or {}) if m else (jsonify({"error": "Not found"}), 404))


@app.get("/api/metrics/timeseries")
def timeseries():
    limit = int(request.args.get("limit", 50))
    points = []
    for rid, run in sorted(RUNS.items(), key=lambda x: x[1]["created_at"]):
        m = RUN_METRICS.get(rid)
        if m and run.get("completed_at"):
            points.append({
                "run_id": rid, "name": run["name"],
                "completed_at": run["completed_at"],
                "pct_passed": m["pct_passed"],
                "total": m["total"],
            })
    return jsonify(points[-limit:])


@app.get("/api/metrics/llm-calls/<run_id>")
def get_llm_calls(run_id):
    return jsonify(LLM_CALLS.get(run_id, []))


@app.get("/api/metrics/llm-summary/<run_id>")
def get_llm_summary(run_id):
    calls = LLM_CALLS.get(run_id, [])
    if not calls:
        return jsonify({"error": "No LLM call data for this run"}), 404
    by_type: dict = {}
    for c in calls:
        ct = c["call_type"]
        if ct not in by_type:
            by_type[ct] = {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                           "total_tokens": 0, "latency_sum": 0}
        by_type[ct]["calls"] += 1
        by_type[ct]["input_tokens"] += c["input_tokens"] or 0
        by_type[ct]["output_tokens"] += c["output_tokens"] or 0
        by_type[ct]["total_tokens"] += c["total_tokens"] or 0
        by_type[ct]["latency_sum"] += c["latency_ms"] or 0
    summary_by_type = {}
    t_calls = t_in = t_out = t_tok = t_lat = 0
    for ct, v in by_type.items():
        summary_by_type[ct] = {
            "calls": v["calls"],
            "input_tokens": v["input_tokens"],
            "output_tokens": v["output_tokens"],
            "total_tokens": v["total_tokens"],
            "avg_latency_ms": round(v["latency_sum"] / v["calls"], 1) if v["calls"] else None,
        }
        t_calls += v["calls"]
        t_in += v["input_tokens"]
        t_out += v["output_tokens"]
        t_tok += v["total_tokens"]
        t_lat += v["latency_sum"]
    return jsonify({
        "totals": {
            "calls": t_calls, "input_tokens": t_in, "output_tokens": t_out,
            "total_tokens": t_tok,
            "avg_latency_ms": round(t_lat / t_calls, 1) if t_calls else None,
        },
        "by_call_type": summary_by_type,
    })


# ── Seeder ─────────────────────────────────────────────────────────────────────

@app.get("/api/seed/strata")
def get_strata():
    return jsonify(STRATA)


@app.post("/api/seed/dry-run")
def seed_dry_run():
    time.sleep(1.2)  # simulate generation latency
    details = []
    total = 0
    for s in STRATA:
        if s["needed"] > 0:
            proposed = [
                f"[PREVIEW] {s['task'].replace('_', ' ').title()} on {s['table_name']}, "
                f"{s['tone']} tone — example question {i + 1}?"
                for i in range(s["needed"])
            ]
            details.append({
                "table_name": s["table_name"], "task": s["task"],
                "needed": s["needed"], "generated": s["needed"],
                "unique": s["needed"], "written": 0,
                "skipped_duplicate": 0, "proposed": proposed,
            })
            total += s["needed"]
    return jsonify({
        "strata_processed": len(details),
        "questions_generated": total,
        "questions_written": 0,
        "skipped_duplicate": 0,
        "strata_detail": details,
    })


@app.post("/api/seed/run")
def seed_run():
    time.sleep(2.0)
    details = []
    written = 0
    for s in STRATA:
        if s["needed"] > 0:
            for i in range(s["needed"]):
                qid = str(uuid.uuid4())
                QUESTIONS[qid] = {
                    "id": qid,
                    "nlq": f"{s['task'].replace('_', ' ').title()} on {s['table_name']} ({s['tone']})?",
                    "table_name": s["table_name"], "task": s["task"], "tone": s["tone"],
                    "status": "active", "is_seeded": True,
                    "leakage_checked": False, "leakage_check_id": None,
                    "notes": "Auto-seeded (demo).",
                    "created_at": _iso(_now()), "updated_at": _iso(_now()),
                    "leakage_check": None,
                }
                written += 1
            details.append({
                "table_name": s["table_name"], "task": s["task"],
                "needed": s["needed"], "generated": s["needed"],
                "unique": s["needed"], "written": s["needed"],
                "skipped_duplicate": 0, "proposed": [],
            })
            s["current_count"] += s["needed"]
            s["needed"] = 0
    return jsonify({
        "strata_processed": len(details),
        "questions_generated": written,
        "questions_written": written,
        "skipped_duplicate": 0,
        "strata_detail": details,
    })


# ── Review ─────────────────────────────────────────────────────────────────────

@app.get("/api/review")
def list_review():
    items = list(REVIEW_ITEMS.values())
    if rid := request.args.get("run_id"):
        items = [i for i in items if i["run_id"] == rid]
    if request.args.get("pending_only", "").lower() == "true":
        items = [i for i in items if i["review_decision"] is None]
    return jsonify(items)


@app.put("/api/review/<item_id>")
def submit_review(item_id):
    item = REVIEW_ITEMS.get(item_id)
    if not item:
        return jsonify({"error": "Not found"}), 404
    body = request.get_json() or {}
    item.update(
        review_decision=body.get("decision"),
        reviewer=body.get("reviewer"),
        review_notes=body.get("notes"),
        reviewed_at=_iso(_now()),
    )
    return jsonify(item)


@app.get("/api/review/stats")
def review_stats():
    items = list(REVIEW_ITEMS.values())
    return jsonify({
        "pending": sum(1 for i in items if i["review_decision"] is None),
        "confirmed_pass": sum(1 for i in items if i["review_decision"] == "confirmed_pass"),
        "override_fail": sum(1 for i in items if i["review_decision"] == "override_fail"),
    })


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print()
    print("  T2S Eval — Demo Mode")
    print("  " + "─" * 55)
    print("  Fake data pre-loaded. No GCP credentials required.")
    print("  All state is in-memory and resets on restart.")
    print()
    print("  Demo API:  http://localhost:5000/api/health")
    print()
    print("  To view the dashboard:")
    print("    cd frontend && npm run dev")
    print("    Open http://localhost:3000")
    print("  " + "─" * 55)
    print()
    app.run(host="0.0.0.0", port=5000, debug=False)
