import traceback

from flask import Flask, jsonify
from flask_cors import CORS

from .config import Config
from .models import db
from .routes import register_blueprints


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    CORS(app, origins=app.config["CORS_ORIGINS"])
    db.init_app(app)
    register_blueprints(app)

    # Register agent tools with the tool registry
    from .services.analyze_tools import ANALYZE_TOOLS
    from .services.campaign_tools import CAMPAIGN_TOOLS
    from .services.company_research_tool import COMPANY_RESEARCH_TOOLS
    from .services.enrichment_gap_tools import ENRICHMENT_TOOLS
    from .services.enrichment_trigger_tools import ENRICHMENT_TRIGGER_TOOLS
    from .services.icp_filter_tools import ICP_FILTER_TOOLS
    from .services.search_tools import SEARCH_TOOLS
    from .services.strategy_refinement_tools import STRATEGY_REFINEMENT_TOOLS
    from .services.strategy_tools import STRATEGY_TOOLS
    from .services.tool_registry import register_tool
    from .tools.enrichment_tools import ENRICHMENT_AGENT_TOOLS

    for tool in (
        STRATEGY_TOOLS
        + ANALYZE_TOOLS
        + SEARCH_TOOLS
        + COMPANY_RESEARCH_TOOLS
        + CAMPAIGN_TOOLS
        + ICP_FILTER_TOOLS
        + ENRICHMENT_TOOLS
        + ENRICHMENT_TRIGGER_TOOLS
        + STRATEGY_REFINEMENT_TOOLS
        + ENRICHMENT_AGENT_TOOLS
    ):
        try:
            register_tool(tool)
        except ValueError:
            pass  # Already registered (e.g. during testing)

    # Clean up orphaned pipeline/stage runs left by container restarts
    with app.app_context():
        try:
            from sqlalchemy import text

            db.session.execute(
                text("""
                UPDATE stage_runs SET status = 'failed',
                    error = 'Orphaned by container restart',
                    completed_at = CURRENT_TIMESTAMP
                WHERE status IN ('running', 'pending', 'stopping')
            """)
            )
            db.session.execute(
                text("""
                UPDATE pipeline_runs SET status = 'failed',
                    completed_at = CURRENT_TIMESTAMP
                WHERE status IN ('running', 'stopping')
            """)
            )
            db.session.commit()
            app.logger.info("Cleaned up orphaned pipeline/stage runs")
        except Exception:
            db.session.rollback()
            app.logger.warning("Could not clean orphaned runs (likely first boot)")

    # Verify DB connectivity at startup (non-fatal — health endpoint surfaces it)
    with app.app_context():
        try:
            from sqlalchemy import text as _text

            db.session.execute(_text("SELECT 1"))
            db.session.rollback()
            app.logger.info("Startup DB connectivity check: OK")
        except Exception as exc:
            app.logger.critical(
                "Startup DB connectivity check FAILED: %s — "
                "the /api/health endpoint will report unhealthy until DB is reachable",
                exc,
            )

    @app.errorhandler(500)
    def handle_500(e):
        app.logger.error("Unhandled 500:\n%s", traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500

    @app.errorhandler(404)
    def handle_404(e):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(405)
    def handle_405(e):
        return jsonify({"error": "Method not allowed"}), 405

    return app
