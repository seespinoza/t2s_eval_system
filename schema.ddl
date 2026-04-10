-- T2S Eval System — Spanner DDL
-- Apply via: gcloud spanner databases ddl update <DATABASE> --instance=<INSTANCE> --ddl-file=schema.ddl

CREATE TABLE Questions (
    id               STRING(36)  NOT NULL,
    nlq              STRING(MAX) NOT NULL,
    table_name       STRING(256) NOT NULL,
    task             STRING(256) NOT NULL,
    status           STRING(32)  NOT NULL,
    is_seeded        BOOL        NOT NULL DEFAULT (FALSE),
    leakage_checked  BOOL        NOT NULL DEFAULT (FALSE),
    leakage_check_id STRING(36),
    notes            STRING(MAX),
    created_at       TIMESTAMP   NOT NULL OPTIONS (allow_commit_timestamp=true),
    updated_at       TIMESTAMP   NOT NULL OPTIONS (allow_commit_timestamp=true),
) PRIMARY KEY (id);

CREATE INDEX QuestionsByTableTask ON Questions(table_name, task);
CREATE INDEX QuestionsByStatus    ON Questions(status);

CREATE TABLE LeakageChecks (
    id                    STRING(36)  NOT NULL,
    question_id           STRING(36)  NOT NULL,
    embedding_flagged     BOOL        NOT NULL,
    embedding_max_sim     FLOAT64,
    embedding_match_text  STRING(MAX),
    llm_flagged           BOOL        NOT NULL,
    llm_reasoning         STRING(MAX),
    overall_passed        BOOL        NOT NULL,
    checked_at            TIMESTAMP   NOT NULL OPTIONS (allow_commit_timestamp=true),
) PRIMARY KEY (question_id, id),
  INTERLEAVE IN PARENT Questions ON DELETE CASCADE;

CREATE TABLE Runs (
    id                   STRING(36)  NOT NULL,
    name                 STRING(256),
    status               STRING(32)  NOT NULL,
    started_at           TIMESTAMP,
    completed_at         TIMESTAMP,
    last_heartbeat       TIMESTAMP,
    question_ids_json    JSON,
    config_json          JSON,
    question_filter_json JSON,
    total_questions      INT64,
    resume_count         INT64       NOT NULL DEFAULT (0),
    created_at           TIMESTAMP   NOT NULL OPTIONS (allow_commit_timestamp=true),
) PRIMARY KEY (id);

CREATE INDEX RunsByCreatedAt ON Runs(created_at DESC);
CREATE INDEX RunsByStatus    ON Runs(status);

CREATE TABLE Results (
    run_id            STRING(36)  NOT NULL,
    id                STRING(36)  NOT NULL,
    question_id       STRING(36)  NOT NULL,
    nlq_snapshot      STRING(MAX) NOT NULL,
    outcome           STRING(32)  NOT NULL,
    sql_generated     STRING(MAX),
    agent_response    STRING(MAX),
    judge_verdict     STRING(16),
    judge_confidence  FLOAT64,
    judge_reasoning   STRING(MAX),
    runtime_ms        INT64,
    route             STRING(64),
    join_count        INT64,
    error_message     STRING(MAX),
    started_at        TIMESTAMP,
    completed_at      TIMESTAMP,
) PRIMARY KEY (run_id, id),
  INTERLEAVE IN PARENT Runs ON DELETE CASCADE;

CREATE INDEX ResultsByOutcome  ON Results(run_id, outcome);
CREATE INDEX ResultsByQuestion ON Results(question_id);

CREATE TABLE ReviewItems (
    id               STRING(36)  NOT NULL,
    result_id        STRING(36)  NOT NULL,
    run_id           STRING(36)  NOT NULL,
    question_id      STRING(36)  NOT NULL,
    nlq_snapshot     STRING(MAX) NOT NULL,
    judge_confidence FLOAT64     NOT NULL,
    judge_reasoning  STRING(MAX),
    reviewer         STRING(256),
    review_decision  STRING(32),
    review_notes     STRING(MAX),
    created_at       TIMESTAMP   NOT NULL OPTIONS (allow_commit_timestamp=true),
    reviewed_at      TIMESTAMP,
) PRIMARY KEY (id);

CREATE INDEX ReviewByRunId  ON ReviewItems(run_id);
CREATE NULL_FILTERED INDEX ReviewPending ON ReviewItems(review_decision);

CREATE TABLE RunMetrics (
    run_id               STRING(36) NOT NULL,
    total                INT64,
    count_passed         INT64,
    count_failed         INT64,
    count_rule_violation INT64,
    count_low_conf_pass  INT64,
    pct_passed           FLOAT64,
    pct_failed           FLOAT64,
    pct_rule_violation   FLOAT64,
    avg_runtime_ms       FLOAT64,
    metrics_json         JSON,
    computed_at          TIMESTAMP  NOT NULL OPTIONS (allow_commit_timestamp=true),
) PRIMARY KEY (run_id),
  INTERLEAVE IN PARENT Runs ON DELETE CASCADE;
