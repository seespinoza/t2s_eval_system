from flask import Flask, jsonify
from flask_cors import CORS
from src.config.settings import get_config
from src.api import questions, runs, metrics, seeder, review


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app)

    app.register_blueprint(questions.bp)
    app.register_blueprint(runs.bp)
    app.register_blueprint(metrics.bp)
    app.register_blueprint(seeder.bp)
    app.register_blueprint(review.bp)

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok"})

    @app.get("/api/config")
    def config():
        return jsonify(get_config().public_dict())

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def server_error(e):
        return jsonify({"error": "Internal server error"}), 500

    return app


if __name__ == "__main__":
    cfg = get_config()
    app = create_app()
    app.run(host="0.0.0.0", port=cfg.flask_port, debug=cfg.flask_env == "development")
