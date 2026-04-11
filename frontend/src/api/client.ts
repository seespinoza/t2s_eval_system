const BASE = "/api";

async function req<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || res.statusText);
  }
  return res.json();
}

// ── Questions ──────────────────────────────────────────────────────────────

export type QuestionStatus = "active" | "monitoring" | "deleted";
export type QuestionTone = "casual" | "neutral" | "formal";

export interface Question {
  id: string;
  nlq: string;
  table_name: string;
  task: string;
  tone: QuestionTone;
  status: QuestionStatus;
  is_seeded: boolean;
  leakage_checked: boolean;
  leakage_check_id: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  leakage_check?: LeakageCheck;
}

export interface LeakageCheck {
  id: string;
  question_id: string;
  embedding_flagged: boolean;
  embedding_max_sim: number | null;
  embedding_match_text: string | null;
  llm_flagged: boolean;
  llm_reasoning: string | null;
  overall_passed: boolean;
  checked_at: string;
}

export const questionsApi = {
  list: (params?: Record<string, string>) =>
    req<Question[]>(`/questions?${new URLSearchParams(params)}`),
  get: (id: string) => req<Question>(`/questions/${id}`),
  create: (body: Partial<Question>) =>
    req<Question>("/questions", { method: "POST", body: JSON.stringify(body) }),
  update: (id: string, body: Partial<Question>) =>
    req<Question>(`/questions/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  delete: (id: string) =>
    req<{ deleted: string }>(`/questions/${id}`, { method: "DELETE" }),
  checkLeakage: (id: string) =>
    req<LeakageCheck>(`/questions/${id}/check-leakage`, { method: "POST" }),
  checkLeakageBatch: () =>
    req<{ processed: number; errors: unknown[] }>("/questions/check-leakage-batch", { method: "POST" }),
  exportCsv: () => fetch(`${BASE}/questions/export.csv`),
  importCsv: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch(`${BASE}/questions/import-csv`, { method: "POST", body: fd }).then((r) => r.json());
  },
};

// ── Runs ───────────────────────────────────────────────────────────────────

export type RunStatus = "pending" | "running" | "completed" | "failed" | "cancelled";

export interface QuestionSet {
  id: string;
  name: string;
  version: string | null;
  description: string | null;
  question_count: number;
  created_at: string;
}

export interface Run {
  id: string;
  name: string | null;
  status: RunStatus;
  agent_version: string | null;
  description: string | null;
  question_set_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  last_heartbeat: string | null;
  total_questions: number | null;
  resume_count: number;
  created_at: string;
  progress?: { completed: number; total: number };
}

export interface Result {
  run_id: string;
  id: string;
  question_id: string;
  nlq_snapshot: string;
  tone_snapshot: string | null;
  outcome: string;
  sql_generated: string | null;
  agent_response: string | null;
  judge_verdict: string | null;
  judge_confidence: number | null;
  judge_reasoning: string | null;
  runtime_ms: number | null;
  route: string | null;
  join_count: number | null;
  error_message: string | null;
  completed_at: string | null;
}

export const questionSetsApi = {
  list: (limit = 50) => req<QuestionSet[]>(`/question-sets?limit=${limit}`),
  get: (id: string) => req<QuestionSet>(`/question-sets/${id}`),
  create: (body: { name: string; version?: string; description?: string; filter?: object }) =>
    req<QuestionSet>("/question-sets", { method: "POST", body: JSON.stringify(body) }),
  delete: (id: string) =>
    req<{ deleted: string }>(`/question-sets/${id}`, { method: "DELETE" }),
};

export const runsApi = {
  list: (limit = 20) => req<Run[]>(`/runs?limit=${limit}`),
  get: (id: string) => req<Run>(`/runs/${id}`),
  create: (body: { name?: string; config?: object; question_filter?: object }) =>
    req<Run>("/runs", { method: "POST", body: JSON.stringify(body) }),
  start: (id: string) =>
    req<{ started: string }>(`/runs/${id}/start`, { method: "POST" }),
  cancel: (id: string) =>
    req<{ cancelled: string }>(`/runs/${id}/cancel`, { method: "POST" }),
  delete: (id: string) =>
    req<{ deleted: string }>(`/runs/${id}`, { method: "DELETE" }),
  results: (id: string, params?: Record<string, string>) =>
    req<Result[]>(`/runs/${id}/results?${new URLSearchParams(params)}`),
  metrics: (id: string) => req<RunMetrics>(`/runs/${id}/metrics`),
};

// ── Metrics ────────────────────────────────────────────────────────────────

export interface RunMetrics {
  run_id: string;
  total: number;
  count_passed: number;
  count_failed: number;
  count_rule_violation: number;
  count_low_conf_pass: number;
  pct_passed: number;
  pct_failed: number;
  pct_rule_violation: number;
  avg_runtime_ms: number | null;
  metrics_json: {
    by_route: Record<string, unknown>;
    by_table: Record<string, unknown>;
    by_task: Record<string, unknown>;
    by_joins: Record<string, unknown>;
    by_tone: Record<string, unknown>;
  } | null;
  computed_at: string;
  run_name?: string;
  completed_at?: string;
}

export interface TimeseriesPoint {
  run_id: string;
  name: string | null;
  completed_at: string;
  pct_passed: number;
  total: number;
}

export interface StratumMetrics {
  run_id: string;
  run_name: string | null;
  total: number;
  count_passed: number;
  count_failed: number;
  count_rule_violation: number;
  count_low_conf_pass: number;
  pct_passed: number;
  pct_failed: number;
  pct_rule_violation: number;
  avg_runtime_ms: number | null;
}

export interface QuestionCompareResult {
  result_id: string;
  outcome: string;
  sql_generated: string | null;
  judge_verdict: string | null;
  judge_confidence: number | null;
  judge_reasoning: string | null;
  runtime_ms: number | null;
  route: string | null;
  error_message: string | null;
}

export interface QuestionCompareRow {
  question_id: string;
  nlq: string;
  tone: string | null;
  results: Record<string, QuestionCompareResult>; // keyed by run_id
}

export const metricsApi = {
  compare: (runIds: string[]) =>
    req<RunMetrics[]>(`/metrics/compare?run_ids=${runIds.join(",")}`),
  compareStratum: (runIds: string[], filters: { table?: string; task?: string; tone?: string }) => {
    const p = new URLSearchParams({ run_ids: runIds.join(",") });
    if (filters.table) p.set("table", filters.table);
    if (filters.task) p.set("task", filters.task);
    if (filters.tone) p.set("tone", filters.tone);
    return req<StratumMetrics[]>(`/metrics/compare-stratum?${p}`);
  },
  compareQuestions: (runIds: string[], q: string) =>
    req<QuestionCompareRow[]>(
      `/metrics/compare-questions?run_ids=${runIds.join(",")}&q=${encodeURIComponent(q)}`
    ),
  breakdown: (runId: string) =>
    req<Record<string, unknown>>(`/metrics/breakdown/${runId}`),
  timeseries: (limit = 50) =>
    req<TimeseriesPoint[]>(`/metrics/timeseries?limit=${limit}`),
  llmCalls: (runId: string) =>
    req<LlmCall[]>(`/metrics/llm-calls/${runId}`),
  llmSummary: (runId: string) =>
    req<LlmSummary>(`/metrics/llm-summary/${runId}`),
};

// ── LLM Usage ──────────────────────────────────────────────────────────────

export interface LlmCall {
  id: string;
  question_id: string | null;
  call_type: string;
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  latency_ms: number | null;
  called_at: string;
}

export interface LlmSummary {
  totals: {
    calls: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    avg_latency_ms: number | null;
  };
  by_call_type: Record<string, {
    calls: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    avg_latency_ms: number | null;
  }>;
}

// ── Seeder ─────────────────────────────────────────────────────────────────

export interface Stratum {
  table_name: string;
  task: string;
  tone: string;
  description: string;
  current_count: number;
  target_count: number;
  needed: number;
}

export interface SeedReport {
  strata_processed: number;
  questions_generated: number;
  questions_written: number;
  skipped_duplicate: number;
  strata_detail: Array<{
    table_name: string;
    task: string;
    needed: number;
    generated: number;
    unique: number;
    written: number;
    skipped_duplicate: number;
    proposed: string[];
  }>;
}

export const seederApi = {
  strata: () => req<Stratum[]>("/seed/strata"),
  dryRun: () => req<SeedReport>("/seed/dry-run", { method: "POST" }),
  run: () => req<SeedReport>("/seed/run", { method: "POST" }),
};

// ── Review ─────────────────────────────────────────────────────────────────

export interface ReviewItem {
  id: string;
  result_id: string;
  run_id: string;
  question_id: string;
  nlq_snapshot: string;
  judge_confidence: number;
  judge_reasoning: string | null;
  reviewer: string | null;
  review_decision: string | null;
  review_notes: string | null;
  created_at: string;
  reviewed_at: string | null;
}

export const reviewApi = {
  list: (params?: Record<string, string>) =>
    req<ReviewItem[]>(`/review?${new URLSearchParams(params)}`),
  submit: (id: string, body: { decision: string; reviewer?: string; notes?: string }) =>
    req<ReviewItem>(`/review/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  stats: () => req<{ pending: number; confirmed_pass: number; override_fail: number }>("/review/stats"),
};
