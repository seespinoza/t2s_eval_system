from google.cloud import spanner
from src.config.settings import get_config

_source_db: spanner.database.Database | None = None
_eval_db: spanner.database.Database | None = None

# Table name constants
T_QUESTIONS = "Questions"
T_LEAKAGE_CHECKS = "LeakageChecks"
T_RUNS = "Runs"
T_RESULTS = "Results"
T_REVIEW_ITEMS = "ReviewItems"
T_RUN_METRICS = "RunMetrics"


def get_source_db() -> spanner.database.Database:
    global _source_db
    if _source_db is None:
        cfg = get_config()
        client = spanner.Client(project=cfg.spanner_source_project)
        instance = client.instance(cfg.spanner_source_instance)
        _source_db = instance.database(cfg.spanner_source_database)
    return _source_db


def get_eval_db() -> spanner.database.Database:
    global _eval_db
    if _eval_db is None:
        cfg = get_config()
        client = spanner.Client(project=cfg.spanner_eval_project)
        instance = client.instance(cfg.spanner_eval_instance)
        _eval_db = instance.database(cfg.spanner_eval_database)
    return _eval_db
