import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # GCP
    gcp_credentials: str = field(default_factory=lambda: os.getenv("GOOGLE_APPLICATION_CREDENTIALS", ""))
    vertex_ai_project: str = field(default_factory=lambda: os.getenv("VERTEX_AI_PROJECT", ""))
    vertex_ai_location: str = field(default_factory=lambda: os.getenv("VERTEX_AI_LOCATION", "us-central1"))

    # Spanner — source (semantic layer + curriculum)
    spanner_source_project: str = field(default_factory=lambda: os.getenv("SPANNER_SOURCE_PROJECT", ""))
    spanner_source_instance: str = field(default_factory=lambda: os.getenv("SPANNER_SOURCE_INSTANCE", ""))
    spanner_source_database: str = field(default_factory=lambda: os.getenv("SPANNER_SOURCE_DATABASE", ""))

    # Spanner — eval (questions, runs, results)
    spanner_eval_project: str = field(default_factory=lambda: os.getenv("SPANNER_EVAL_PROJECT", ""))
    spanner_eval_instance: str = field(default_factory=lambda: os.getenv("SPANNER_EVAL_INSTANCE", ""))
    spanner_eval_database: str = field(default_factory=lambda: os.getenv("SPANNER_EVAL_DATABASE", ""))

    # ADK
    adk_agent_module: str = field(default_factory=lambda: os.getenv("ADK_AGENT_MODULE", ""))
    adk_host: str = field(default_factory=lambda: os.getenv("ADK_HOST", "localhost"))
    adk_port: int = field(default_factory=lambda: int(os.getenv("ADK_PORT", "8080")))
    # ADK response field mapping — set these once you know your agent's response shape.
    # Each value is a comma-separated list of field names tried in order (first non-empty wins).
    adk_field_sql: str = field(default_factory=lambda: os.getenv("ADK_FIELD_SQL", "sql_generated,sql,query"))
    adk_field_route: str = field(default_factory=lambda: os.getenv("ADK_FIELD_ROUTE", "route"))
    adk_field_response: str = field(default_factory=lambda: os.getenv("ADK_FIELD_RESPONSE", "response,output,text"))
    adk_run_path: str = field(default_factory=lambda: os.getenv("ADK_RUN_PATH", "/run"))
    agent_repo_path: str = field(default_factory=lambda: os.getenv("AGENT_REPO_PATH", ""))

    # Models
    embedding_model: str = field(default_factory=lambda: os.getenv("EMBEDDING_MODEL", "text-embedding-004"))
    judge_model: str = field(default_factory=lambda: os.getenv("JUDGE_MODEL", "gemini-2.0-flash"))

    # Thresholds
    leakage_embedding_threshold: float = field(
        default_factory=lambda: float(os.getenv("LEAKAGE_EMBEDDING_THRESHOLD", "0.85"))
    )
    judge_confidence_threshold: float = field(
        default_factory=lambda: float(os.getenv("JUDGE_CONFIDENCE_THRESHOLD", "0.75"))
    )

    # Run settings
    run_concurrency: int = field(default_factory=lambda: int(os.getenv("RUN_CONCURRENCY", "4")))
    seeder_active_count: int = field(default_factory=lambda: int(os.getenv("SEEDER_ACTIVE_COUNT", "7")))
    seeder_monitoring_count: int = field(default_factory=lambda: int(os.getenv("SEEDER_MONITORING_COUNT", "2")))
    heartbeat_interval_seconds: int = field(
        default_factory=lambda: int(os.getenv("HEARTBEAT_INTERVAL_SECONDS", "60"))
    )
    heartbeat_stale_minutes: int = field(
        default_factory=lambda: int(os.getenv("HEARTBEAT_STALE_MINUTES", "5"))
    )

    # Flask
    flask_env: str = field(default_factory=lambda: os.getenv("FLASK_ENV", "production"))
    flask_port: int = field(default_factory=lambda: int(os.getenv("FLASK_PORT", "5000")))

    @property
    def adk_base_url(self) -> str:
        return f"http://{self.adk_host}:{self.adk_port}"

    def public_dict(self) -> dict:
        return {
            "embedding_model": self.embedding_model,
            "judge_model": self.judge_model,
            "leakage_embedding_threshold": self.leakage_embedding_threshold,
            "judge_confidence_threshold": self.judge_confidence_threshold,
            "run_concurrency": self.run_concurrency,
            "seeder_active_count": self.seeder_active_count,
            "seeder_monitoring_count": self.seeder_monitoring_count,
            "heartbeat_interval_seconds": self.heartbeat_interval_seconds,
            "heartbeat_stale_minutes": self.heartbeat_stale_minutes,
        }


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config
