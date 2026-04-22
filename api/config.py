import os


class Config:
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "postgresql://localhost/leadgen"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "change-me-in-production")
    JWT_ACCESS_EXPIRY = 3600  # 1 hour
    JWT_REFRESH_EXPIRY = 7 * 24 * 3600  # 7 days
    CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*").split(",")
    N8N_BASE_URL = os.environ.get("N8N_BASE_URL", "https://n8n.visionvolve.com")

    # Google OAuth
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "")

    # Token encryption (Fernet key)
    OAUTH_ENCRYPTION_KEY = os.environ.get("OAUTH_ENCRYPTION_KEY", "")

    # Gmail OAuth (BL-1044) -- separate credentials for the inbound-mail
    # connection flow so the reply-tracking integration can be managed
    # independently from the generic OAuth store.
    GOOGLE_GMAIL_CLIENT_ID = os.environ.get("GOOGLE_GMAIL_CLIENT_ID", "")
    GOOGLE_GMAIL_CLIENT_SECRET = os.environ.get("GOOGLE_GMAIL_CLIENT_SECRET", "")
    # Defaults derived from request host when unset.
    GMAIL_OAUTH_REDIRECT_URI = os.environ.get("GMAIL_OAUTH_REDIRECT_URI", "")
    # Fernet key for BL-1044 Gmail connection tokens (keep isolated from the
    # generic OAUTH_ENCRYPTION_KEY so Gmail keys can be rotated separately).
    GMAIL_TOKEN_ENCRYPTION_KEY = os.environ.get("GMAIL_TOKEN_ENCRYPTION_KEY", "")
    # Frontend origin used when building the post-callback redirect URL.
    # Falls back to the request origin when unset.
    FRONTEND_BASE_URL = os.environ.get("FRONTEND_BASE_URL", "")

    # Perplexity API
    PERPLEXITY_API_KEY = os.environ.get("PERPLEXITY_API_KEY", "")
    PERPLEXITY_BASE_URL = os.environ.get(
        "PERPLEXITY_BASE_URL", "https://api.perplexity.ai"
    )
    PERPLEXITY_MAX_RPM = int(os.environ.get("PERPLEXITY_MAX_RPM", "20"))

    # Enrichment pipeline parallelism
    ENRICHMENT_MAX_WORKERS = int(os.environ.get("ENRICHMENT_MAX_WORKERS", "20"))
    ENRICHMENT_SKIP_RECENT_HOURS = int(
        os.environ.get("ENRICHMENT_SKIP_RECENT_HOURS", "24")
    )

    # IAM integration
    IAM_BASE_URL = os.environ.get("IAM_BASE_URL", "https://iam.visionvolve.com")
    IAM_JWKS_URL = os.environ.get(
        "IAM_JWKS_URL",
        os.environ.get("IAM_BASE_URL", "https://iam.visionvolve.com")
        + "/.well-known/jwks.json",
    )
    IAM_AUDIENCE = os.environ.get("IAM_AUDIENCE", "leadgen")
    IAM_SERVICE_API_KEY = os.environ.get("IAM_SERVICE_API_KEY", "")

    # United Arts microsite
    UA_MICROSITE_URL = os.environ.get(
        "UA_MICROSITE_URL", "https://demo.visionvolve.com"
    )
    UA_INVITE_API_KEY = os.environ.get("UA_INVITE_API_KEY", "")

    # PostHog — campaign analytics microsite metrics (BL-1035)
    # Region = US (account was created US-side). Override POSTHOG_HOST if
    # pointing at an EU project. All keys are optional here: when unset the
    # integration raises a clear RuntimeError only at call time, so dev
    # without PostHog still boots cleanly.
    POSTHOG_HOST = os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com")
    POSTHOG_PROJECT_ID = os.environ.get("POSTHOG_PROJECT_ID", "")
    # Public key — ships to the browser via posthog-js in ua-microsite. Safe
    # exposure, but still belongs in env/1P, not in git.
    POSTHOG_PROJECT_API_KEY = os.environ.get("POSTHOG_PROJECT_API_KEY", "")
    # Secret key — backend Query API only. NEVER expose to frontend. NEVER log.
    POSTHOG_PERSONAL_API_KEY = os.environ.get("POSTHOG_PERSONAL_API_KEY", "")

    # SQLAlchemy connection pool — sized for parallel enrichment workers
    # Only set pool options for PostgreSQL; SQLite uses StaticPool (no pool_size)
    _db_url = os.environ.get("DATABASE_URL", "postgresql://localhost/leadgen")
    if _db_url.startswith("sqlite"):
        SQLALCHEMY_ENGINE_OPTIONS = {}
    else:
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_size": int(os.environ.get("SQLALCHEMY_POOL_SIZE", "20")),
            "max_overflow": int(os.environ.get("SQLALCHEMY_MAX_OVERFLOW", "30")),
            "pool_pre_ping": True,
        }
