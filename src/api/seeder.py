from flask import Blueprint, jsonify
from src.services import seeder
from src.services.seeder import get_strata_with_targets

bp = Blueprint("seeder", __name__, url_prefix="/api/seed")


@bp.get("/strata")
def get_strata():
    strata = get_strata_with_targets()
    return jsonify([
        {
            "table_name": s.table_name,
            "task": s.task,
            "tone": s.tone,
            "description": s.description,
            "current_count": s.current_count,
            "target_count": s.target_count,
            "needed": s.needed,
        }
        for s in strata
    ])


@bp.post("/dry-run")
def dry_run():
    report = seeder.seed_all(dry_run=True)
    return jsonify(report.to_dict())


@bp.post("/run")
def run_seed():
    report = seeder.seed_all(dry_run=False)
    return jsonify(report.to_dict())
