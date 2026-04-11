# T2S Eval System

An automated evaluation framework for a multi-agent text-to-SQL pipeline. The system runs a curated question bank against the live agent, judges each response with an LLM, surfaces low-confidence results for human review, and presents all results in a dark-themed React dashboard.

---

## How Evaluation Works

### The Pipeline Under Test

The agent under test is a multi-step pipeline:

```
User NLQ → Router → Schema Selector → Text-to-SQL → Synthesizer → Response
```

Evaluation is **end-to-end**: the system submits a natural language question (NLQ) and receives the final synthesized response, including the SQL the agent generated internally. No intermediate steps are stubbed or bypassed.

### Question Bank and Stratification

All test questions live in a managed **question bank** stored in Spanner. Every question is tagged along three dimensions:

- **Table** — the primary table the question targets
- **Task** — the type of SQL operation required (e.g. `aggregate_sum`, `filter_by_date`, `join_related_table`, `rank_top_n`)
- **Tone** — the formality level of the question: `casual`, `neutral`, or `formal`

Tone reflects how real users phrase queries. Formal questions are precise and verbose ("What is the total aggregate revenue, broken down by product category, for the fiscal year ending Q4?"). Casual questions are terse and potentially ambiguous ("top customers by spend?"). The agent should handle all three, so metrics are broken down by tone to detect regression in any register.

This three-dimensional stratification (`table × task × tone`) is what allows the system to reason about **coverage gaps** rather than treating the question set as a flat list. The seeder computes how many questions each stratum currently has and generates exactly the number needed to meet targets.

Questions enter the bank in three ways:

1. **LLM auto-seeding** — the system discovers all logical `(table, task)` strata from the source semantic layer, expands each across the three tones, and calls Gemini to generate exactly the needed questions per stratum.
2. **Dashboard CRUD** — individual questions can be created, edited, or soft-deleted through the web UI.
3. **CSV import** — the full question bank can be exported as a CSV, edited offline by domain experts, and re-imported. Only `nlq`, `status`, and `notes` are mutable via CSV to prevent bulk corruption of the stratification metadata.

### Data Leakage Prevention

Before any question is used in an evaluation run, it must pass a two-part **leakage check**. The concern is that a test question might already appear — verbatim or semantically — in the agent's own prompt examples, turning the evaluation into a memorization test rather than a generalization test.

**Check A — Embedding similarity vs. curriculum:**
The question is embedded via Vertex AI (`text-embedding-004`) and compared against a cached corpus of all curriculum NLQs from the source Spanner database. If cosine similarity exceeds the configured threshold (default 0.85), the question is flagged.

**Check B — LLM comparison vs. prompt examples:**
The system globs all `*.py` files in the agent repository, extracts strings from variables named `examples`, `sample_queries`, `nlq`, etc., and passes them to Gemini alongside the test question. Gemini returns a JSON verdict on whether the test question is substantially similar to any prompt example.

Both checks must pass. Questions that fail are not automatically excluded — they remain in the bank marked as failed, preserving the audit trail. Only questions with `leakage_checked = true` are eligible for a run.

### Seeding with HyDE (Hypothetical Document Embeddings)

When generating questions for a new stratum, the system uses HyDE to find the most relevant real examples from the curriculum to use as few-shot guidance for Gemini:

1. For each `(table, task, tone)` stratum, Gemini first generates one *hypothetical ideal question* — a representative example of what a good question for this stratum would look like.
2. That hypothetical question is embedded and compared against all curriculum NLQ embeddings using cosine similarity.
3. The top-k most similar curriculum questions are retrieved, but each candidate is filtered out if it:
   - Already exists in the question bank (would be a duplicate)
   - Is too similar to a known agent prompt example (would introduce leakage)
4. The surviving candidates are passed as few-shot style examples to Gemini, which generates the actual questions for the stratum.

This approach produces questions that are stylistically and semantically grounded in real usage patterns, without copying them.

### Run Lifecycle

A run is a snapshot evaluation of the entire eligible question bank (or a filtered subset). The lifecycle is:

1. **Pending** — a run record is created with optional filter config (e.g. `active` questions only).
2. **Running** — the orchestrator starts the ADK server as a subprocess, snapshots the full list of eligible question IDs into `question_ids_json`, sets `status = running`, and begins parallel evaluation via a thread pool.
3. **Per-question evaluation** — each worker thread calls the ADK HTTP endpoint with one NLQ, parses the SQL from the response, counts JOINs, and calls the Gemini judge.
4. **Outcome mapping** — each result is classified into one of four outcomes (see below) and written to Spanner immediately as it completes. Results are never batched, so no work is lost if the process is interrupted mid-run.
5. **Completed** — after all questions finish, the orchestrator computes aggregate metrics (including breakdowns by route, table, task, tone, and join count), writes them to `RunMetrics`, and sets `status = completed`.

### Outcome Classification

| Outcome | Condition |
|---|---|
| `passed` | Judge verdict is `pass` and confidence ≥ threshold (default 0.75) |
| `low_confidence_pass` | Judge verdict is `pass` but confidence < threshold |
| `rule_violation` | Judge verdict is `fail` |
| `failed` | ADK error, timeout, or no SQL returned |

The confidence threshold mirrors the approach used with ML classifiers: a "pass" with 55% confidence is not the same as one with 95% confidence. Low-confidence passes are surfaced in a separate human review queue so a domain expert can confirm or override before the result counts as a genuine pass.

### LLM Judge

The judge receives the original NLQ, the SQL the agent generated, the full synthesized response, and a summary of the source schema and business rules. It returns three fields:

- `verdict` — `pass` or `fail`
- `confidence` — a float from 0.0 to 1.0
- `reasoning` — a plain-English explanation of the decision

The judge uses Gemini via Vertex AI with `response_mime_type: "application/json"`, so there is no fragile regex parsing of LLM output.

### LLM Call Telemetry

Every Gemini call made during a run — including judging, seeding, leakage checks, and HyDE generation — is logged to the `LlmCallLogs` Spanner table with:

- `call_type` — what the call was for (`judge`, `leakage_llm`, `seed_generate`, `hyde_hypothetical`, `discover_strata`)
- `input_tokens`, `output_tokens`, `total_tokens` — from the response's `usage_metadata`
- `latency_ms` — wall-clock time for the API call
- `run_id` and `question_id` — for attribution

This data powers the **LLM Usage** dashboard page, which shows per-call latency and token usage over the course of a run, a 10-call rolling average on latency, and a per-call-type breakdown table. Use it to track cost trends across runs and spot expensive outliers.

### Checkpoint and Resume

Cloud Run Jobs have a 24-hour limit, and infrastructure can be interrupted. To handle this, the orchestrator maintains a **heartbeat**: a background thread updates `last_heartbeat` on the `Runs` row every 60 seconds. On startup, the runner checks for any run with `status = running` and a heartbeat older than 5 minutes. If found, it resumes that run.

Resume is deterministic: the original question IDs were snapshotted into `question_ids_json` at run start, so the resume scope is always the same set of questions regardless of any changes to the question bank since the run began. The orchestrator diffs the snapshotted IDs against already-completed `Results` rows and evaluates only the remainder.

### Human Review Queue

Any `low_confidence_pass` result automatically creates a `ReviewItems` row. Reviewers see the NLQ, the judge's confidence (rendered as a 10-dot rating), and the judge's reasoning. They can confirm the pass or override it to a fail. Review decisions are written in-place but rows are never deleted — the full audit trail is preserved.

---

## Quick Start Guide

### Prerequisites

- Python 3.11+
- Node.js 18+
- A Google Cloud project with the following APIs enabled:
  - Cloud Spanner
  - Vertex AI
  - (For the runner) Google ADK installed: `pip install google-adk`
- A service account with roles: `roles/spanner.databaseUser`, `roles/aiplatform.user`
- `gcloud` CLI installed and authenticated

### 1. Clone and configure

```bash
git clone <repo-url>
cd t2s_eval_system
```

Copy the example env file:

```bash
# Linux / macOS
cp .env.example .env

# Windows (PowerShell)
Copy-Item .env.example .env
```

Open `.env` and fill in every variable. The minimum set to get the backend running locally:

```
VERTEX_AI_PROJECT=your-gcp-project
VERTEX_AI_LOCATION=us-central1

SPANNER_SOURCE_PROJECT=your-gcp-project
SPANNER_SOURCE_INSTANCE=your-instance
SPANNER_SOURCE_DATABASE=source-db-name

SPANNER_EVAL_PROJECT=your-gcp-project
SPANNER_EVAL_INSTANCE=your-instance
SPANNER_EVAL_DATABASE=eval-db-name

JUDGE_MODEL=gemini-2.0-flash
EMBEDDING_MODEL=text-embedding-004
```

For the service account credentials key (local dev only):

```
# Linux / macOS
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json

# Windows — backslashes or forward slashes both work
GOOGLE_APPLICATION_CREDENTIALS=C:/path/to/service-account-key.json
```

For the agent repo path used in leakage checks:

```
# Linux / macOS
AGENT_REPO_PATH=/path/to/your/agent/repo

# Windows
AGENT_REPO_PATH=C:/path/to/your/agent/repo
```

### 2. Apply the Spanner schema

Run this once to create the eval database tables. Replace the variable placeholders with your actual values:

```bash
gcloud spanner databases ddl update YOUR_EVAL_DATABASE \
  --instance=YOUR_EVAL_INSTANCE \
  --ddl-file=schema.ddl
```

### 3. Start the backend

**Linux / macOS:**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app src.main run --port 5000
```

**Windows (PowerShell):**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
flask --app src.main run --port 5000
```

> **Note:** `gunicorn` (the production WSGI server) is Linux-only and is skipped automatically on Windows. `waitress` is installed instead and used as the WSGI server when running under Docker-for-Windows or any Windows server context. For local development, `flask run` works on both platforms.

The API is now available at `http://localhost:5000/api`.

### 4. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

The dashboard is now available at `http://localhost:5173`. All `/api/*` requests are proxied to the Flask server on port 5000.

### 5. Seed the question bank

With the app running, open the **Seeder** page in the dashboard:

1. The strata table shows all discovered `(table × task × tone)` combinations with their current vs. target counts.
2. Click **Dry Run** to preview what questions would be generated without writing anything.
3. Click **Run Seeder** to generate and write the questions to Spanner.
4. Newly seeded questions have `leakage_checked = false`. Return to the **Question Bank** page and click **Check All** to run leakage checks in batch.

### 6. Run an evaluation

Open the **Dashboard** page:

1. Click **New Run** to create a run record.
2. Click **Start** to begin evaluation. The UI polls for progress.
3. Once complete, click into the run to see per-question results, outcomes, SQL, and judge reasoning.
4. Review any flagged low-confidence passes in the **Review Queue** page.

### 7. Run the unit tests

No GCP credentials needed for unit tests:

```bash
pytest tests/unit/
```

For integration tests and the full smoke test, GCP credentials and a live Spanner database are required:

```bash
pytest tests/integration/
python scripts/smoke_test.py
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Google Cloud                         │
│                                                          │
│  Cloud Scheduler ──► Cloud Run Job (eval runner)         │
│                           │                              │
│                           ▼                              │
│                    Cloud Spanner ◄──── Cloud Run         │
│                    (all eval data)      Service          │
│                                         (Flask API)      │
│                                            ▲             │
└────────────────────────────────────────────┼─────────────┘
                                             │
                                      React dashboard
                                      (served from
                                       Cloud Run or
                                       static hosting)
```

**Cloud Run Job (eval runner)** — runs to completion on a schedule. No persistent HTTP server. Reads questions from Spanner, runs the eval, writes results back.

**Cloud Run Service (Flask API)** — always-on HTTP service. Serves the dashboard API and handles question CRUD, seeding, and review.

**Both services share the same Spanner instance** — the job writes results; the API reads them. No shared filesystem or message queue needed.

**Two logical Spanner databases:**
- **Source DB** — the production semantic layer and curriculum (read-only from eval's perspective). Contains table schemas and curriculum NLQs used for leakage detection and seeding.
- **Eval DB** — questions, runs, results, review items, metrics, and LLM call logs. Owned by this system.

---

## Directory Structure

```
t2s_eval_system/
├── src/                         # Python backend (Flask API + shared services)
│   ├── config/
│   │   └── settings.py          # Typed Config dataclass, get_config() singleton
│   ├── core/
│   │   ├── database.py          # Spanner client init (source + eval), table constants
│   │   └── models.py            # @dataclass for Question, Run, Result, ReviewItem, etc.
│   ├── services/
│   │   ├── adk_client.py        # Subprocess + HTTP wrapper for adk api_server
│   │   ├── embedding.py         # Vertex AI embeddings, cosine similarity, corpus cache
│   │   ├── judge.py             # Gemini judge + HyDE generation + seeder generation
│   │   ├── leakage.py           # Leakage guard: embedding + LLM checks
│   │   ├── llm_logger.py        # Thread-local LLM call telemetry → LlmCallLogs
│   │   ├── orchestrator.py      # Run lifecycle: startup/resume/parallel eval/metrics
│   │   ├── seeder.py            # Strata discovery + HyDE retrieval + NLQ generation
│   │   ├── spanner_eval.py      # CRUD layer for eval DB (questions, runs, results)
│   │   └── spanner_source.py    # Read-only access to source DB (schemas, curriculum)
│   ├── api/
│   │   ├── questions.py         # /api/questions — CRUD + CSV + leakage
│   │   ├── runs.py              # /api/runs — lifecycle management
│   │   ├── metrics.py           # /api/metrics — compare, breakdown, timeseries, LLM usage
│   │   ├── seeder.py            # /api/seed — strata, dry-run, execute
│   │   └── review.py            # /api/review — human queue
│   ├── utils/
│   │   ├── sql_parser.py        # count_joins(), extract_table_names()
│   │   └── csv_utils.py         # questions_to_csv(), csv_to_updates()
│   └── main.py                  # Flask app factory
│
├── runner/
│   ├── main.py                  # Cloud Run Job entrypoint
│   └── Dockerfile               # Eval runner image (includes google-adk)
│
├── frontend/                    # React + Vite + TypeScript dashboard
│   ├── src/
│   │   ├── api/client.ts        # Typed fetch wrappers for all API routes
│   │   ├── theme.ts             # Design tokens (colors, fonts, spacing)
│   │   ├── pages/               # Dashboard, RunDetail, Compare, Questions,
│   │   │                        #   ReviewQueue, Seed, LlmUsage
│   │   ├── components/          # layout/, ui/ (Card, DotRating, RunBar, StatusBadge, ...)
│   │   └── hooks/               # useRuns, useQuestions, useMetrics, useReviewQueue
│   └── package.json
│
├── tests/
│   ├── unit/                    # Fast, hermetic — all external deps mocked
│   │   ├── test_sql_parser.py
│   │   ├── test_csv_utils.py
│   │   ├── test_leakage.py
│   │   ├── test_orchestrator.py
│   │   └── test_seeder.py
│   └── integration/             # Require real Spanner + Flask test client
│       ├── test_spanner_schema.py
│       ├── test_api_questions.py
│       └── test_api_runs.py
│
├── scripts/
│   └── smoke_test.py            # End-to-end smoke test against real GCP services
│
├── schema.ddl                   # Spanner DDL for the eval database
├── Dockerfile                   # Flask API image
├── cloudbuild.yaml              # Builds + pushes both images to GCR
├── requirements.txt
├── pytest.ini
└── .env.example
```

---

## Spanner Schema Design

All primary keys use `STRING(36)` UUIDs generated in Python (`str(uuid.uuid4())`). Spanner splits data across servers by key range — monotonically increasing integer keys create a write hotspot on the last split. Random UUIDs distribute writes evenly.

Child tables (`Results`, `RunMetrics`, `LeakageChecks`) are **interleaved** under their parents (`Runs`, `Questions`). Interleaving co-locates parent and child rows on the same Spanner server, making per-run or per-question reads significantly faster than cross-server joins.

Timestamps use `PENDING_COMMIT_TIMESTAMP()` (Spanner's server-side commit timestamp). This avoids clock skew between multiple Cloud Run instances writing concurrently.

`ReviewItems` uses a `NULL_FILTERED INDEX` on `review_decision` so the pending queue query (`WHERE review_decision IS NULL`) hits an index rather than doing a full table scan.

`LlmCallLogs` is not interleaved — LLM calls span multiple question evaluations and a single run, so there is no meaningful parent to interleave under. It has two indexes: one by `run_id` (for fetching all calls for a run) and one by `called_at DESC` (for time-ordered queries).

See `schema.ddl` for the full DDL.

---

## API Reference

### Questions — `/api/questions`

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | List questions (filter by `status`, `table_name`, `task`, `tone`, `leakage_checked`) |
| `POST` | `/` | Create a question |
| `GET` | `/<id>` | Get question with leakage check details |
| `PUT` | `/<id>` | Update `nlq`, `status`, `notes`, `table_name`, `task`, `tone` |
| `DELETE` | `/<id>` | Soft delete (sets `status = deleted`) |
| `POST` | `/<id>/check-leakage` | Run leakage guard for one question |
| `POST` | `/check-leakage-batch` | Run for all questions with `leakage_checked = false` |
| `GET` | `/export.csv` | Download question bank as CSV |
| `POST` | `/import-csv` | Upload CSV — mutates `nlq`, `status`, `notes` only |

### Runs — `/api/runs`

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | List runs |
| `POST` | `/` | Create a run (status: `pending`) |
| `GET` | `/<id>` | Run details + progress |
| `POST` | `/<id>/start` | Start run (spawns background thread) |
| `POST` | `/<id>/cancel` | Cancel an in-progress run |
| `DELETE` | `/<id>` | Delete a completed run |
| `GET` | `/<id>/results` | Paginated results (filter by `outcome`) |
| `GET` | `/<id>/metrics` | Aggregated metrics for the run |

### Metrics — `/api/metrics`

| Method | Path | Description |
|---|---|---|
| `GET` | `/compare?run_ids=1,2,3` | Side-by-side metrics for up to 10 runs |
| `GET` | `/breakdown/<run_id>` | Breakdown by route, task, table, tone, join count |
| `GET` | `/timeseries` | `pct_passed` over time (trend line) |
| `GET` | `/llm-calls/<run_id>` | All LLM call records for a run, ordered by `called_at` |
| `GET` | `/llm-summary/<run_id>` | Aggregate token + latency stats, broken down by call type |

### Seeder — `/api/seed`

| Method | Path | Description |
|---|---|---|
| `GET` | `/strata` | Current `(table × task × tone)` strata with current vs. target counts |
| `POST` | `/dry-run` | Preview proposed questions without writing |
| `POST` | `/run` | Execute seeding — writes new questions to Spanner |

### Review — `/api/review`

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | List review items (filter by `run_id`, pending-only) |
| `PUT` | `/<id>` | Submit decision: `confirmed_pass` or `override_fail` |
| `GET` | `/stats` | Pending vs. reviewed counts |

---

## Configuration

Copy `.env.example` to `.env` and fill in values for local development. In Cloud Run, set these as environment variables — the service account provides GCP credentials via Workload Identity (no key file needed in production).

| Variable | Description |
|---|---|
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to service account key (local dev only) |
| `VERTEX_AI_PROJECT` | GCP project for Vertex AI (embeddings + Gemini) |
| `VERTEX_AI_LOCATION` | Vertex AI region (e.g. `us-central1`) |
| `SPANNER_SOURCE_PROJECT/INSTANCE/DATABASE` | Source DB (semantic layer + curriculum) |
| `SPANNER_EVAL_PROJECT/INSTANCE/DATABASE` | Eval DB (questions, runs, results) |
| `ADK_AGENT_MODULE` | Module path passed to `adk api_server` (runner only) |
| `ADK_HOST` / `ADK_PORT` | ADK server address (runner only) |
| `AGENT_REPO_PATH` | Path to agent repo for leakage prompt extraction |
| `EMBEDDING_MODEL` | Vertex AI embedding model (default: `text-embedding-004`) |
| `JUDGE_MODEL` | Gemini model for judging (default: `gemini-2.0-flash`) |
| `LEAKAGE_EMBEDDING_THRESHOLD` | Cosine similarity cutoff for leakage (default: `0.85`) |
| `JUDGE_CONFIDENCE_THRESHOLD` | Minimum confidence to classify as `passed` (default: `0.75`) |
| `RUN_CONCURRENCY` | Parallel workers per eval run (default: `4`) |
| `SEEDER_ACTIVE_COUNT` | Target questions per stratum for `active` status (default: `7`) |
| `SEEDER_MONITORING_COUNT` | Target questions per stratum for `monitoring` status (default: `2`) |
| `HEARTBEAT_INTERVAL_SECONDS` | How often the orchestrator updates `last_heartbeat` (default: `60`) |
| `HEARTBEAT_STALE_MINUTES` | Age threshold for treating a run as interrupted (default: `5`) |

---

## Deployment

### Apply Spanner Schema

```bash
gcloud spanner databases ddl update $SPANNER_EVAL_DATABASE \
  --instance=$SPANNER_EVAL_INSTANCE \
  --ddl-file=schema.ddl
```

### Build and Push Images

```bash
gcloud builds submit --config cloudbuild.yaml
```

This builds two images:
- `gcr.io/$PROJECT/t2s-eval-api` — Flask API (Cloud Run Service)
- `gcr.io/$PROJECT/t2s-eval-runner` — Eval runner (Cloud Run Job)

### Deploy

```bash
# Flask API
gcloud run deploy t2s-eval-api \
  --image gcr.io/$PROJECT/t2s-eval-api \
  --region us-central1 \
  --set-env-vars SPANNER_EVAL_PROJECT=...,SPANNER_EVAL_INSTANCE=...,...

# Eval runner (Cloud Run Job)
gcloud run jobs create t2s-eval-runner \
  --image gcr.io/$PROJECT/t2s-eval-runner \
  --region us-central1 \
  --set-env-vars ADK_AGENT_MODULE=...,SPANNER_EVAL_PROJECT=...,...

# Schedule the job (e.g. nightly at 2 AM)
gcloud scheduler jobs create http t2s-eval-nightly \
  --schedule "0 2 * * *" \
  --uri "https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT/jobs/t2s-eval-runner:run" \
  --oauth-service-account-email $SA_EMAIL
```

---

## Dashboard Pages

| Page | Purpose |
|---|---|
| **Dashboard** | Headline pass rate, trend line, recent runs with stacked outcome bars |
| **Run Detail** | Per-question results, filterable by outcome, expandable SQL + judge reasoning |
| **Compare** | Side-by-side metrics for up to 10 runs with best-value highlighting |
| **Question Bank** | Full CRUD, filter by status/tone/leakage, tone badges, CSV export/import |
| **Review Queue** | Low-confidence passes awaiting human verdict |
| **Seeder** | Strata view (current vs. target counts by table/task/tone), dry-run preview, execute |
| **LLM Usage** | Per-run token usage and latency charts; call type breakdown table |
