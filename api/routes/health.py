import logging

from flask import Blueprint, jsonify
from sqlalchemy import text

from ..models import db

logger = logging.getLogger(__name__)

health_bp = Blueprint("health", __name__)

DB_CHECK_TIMEOUT_SECONDS = 3


@health_bp.route("/api/health")
def health():
    """Readiness check — verifies the app can actually serve requests (DB connected)."""
    try:
        db.session.execute(
            text("SELECT 1"),
            execution_options={"timeout": DB_CHECK_TIMEOUT_SECONDS},
        )
        return jsonify({"status": "healthy", "db": "connected"}), 200
    except Exception as exc:
        logger.error("Health check failed — DB unreachable: %s", exc)
        return (
            jsonify(
                {
                    "status": "unhealthy",
                    "db": "unreachable",
                    "error": str(exc),
                }
            ),
            503,
        )


@health_bp.route("/api/health/liveness")
def liveness():
    """Liveness check — confirms the process is running. No dependency checks."""
    return jsonify({"status": "alive"}), 200
