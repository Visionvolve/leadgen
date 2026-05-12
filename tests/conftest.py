"""Shared test fixtures for the leadgen pipeline test suite."""
import json
import os
import time
import uuid

import jwt as pyjwt
import pytest
from sqlalchemy import String, Text, event
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.schema import ColumnDefault

# Use SQLite for tests (no PG dependency needed for unit tests)
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-do-not-use-in-prod")
os.environ.setdefault("CORS_ORIGINS", "*")

from api import create_app
from api.models import db as _db
from api.services.tool_registry import clear_registry

# Test-only HS256 secret for generating test tokens (not used in production)
_TEST_JWT_SECRET = "test-secret-key-do-not-use-in-prod"


def _uuid_default():
    return str(uuid.uuid4())


def _patch_pg_types_for_sqlite(app):
    """Replace PostgreSQL-specific column types with SQLite-compatible ones."""
    from sqlalchemy import text as sa_text
    with app.app_context():
        for table in _db.metadata.tables.values():
            for column in table.columns:
                if isinstance(column.type, UUID):
                    column.type = String(36)
                    if column.server_default is not None and "uuid_generate" in str(column.server_default.arg):
                        column.server_default = None
                        column.default = ColumnDefault(_uuid_default)
                elif isinstance(column.type, ARRAY):
                    column.type = Text()
                    if column.server_default is not None:
                        column.server_default = None
                elif isinstance(column.type, JSONB):
                    column.type = Text()
                    if column.server_default is not None:
                        column.server_default = None
                # Replace now() with CURRENT_TIMESTAMP for SQLite
                if column.server_default is not None:
                    default_text = str(column.server_default.arg)
                    if "now()" in default_text:
                        column.server_default = _db.DefaultClause(sa_text("CURRENT_TIMESTAMP"))

    # Register SQLite adapter for dicts (JSONB → TEXT)
    import sqlite3
    sqlite3.register_adapter(dict, lambda d: json.dumps(d))
    sqlite3.register_adapter(list, lambda l: json.dumps(l))


@pytest.fixture(scope="session")
def app():
    """Create Flask application for testing."""
    app = create_app()
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    _patch_pg_types_for_sqlite(app)
    return app


@pytest.fixture(scope="function")
def db(app):
    """Create fresh database tables for each test."""
    with app.app_context():
        _db.create_all()
        yield _db
        _db.session.rollback()
        _db.drop_all()


@pytest.fixture(scope="function")
def client(app, db):
    """Flask test client with clean DB."""
    with app.test_client() as client:
        with app.app_context():
            yield client


@pytest.fixture(autouse=True)
def clean_tool_registry():
    """Clear tool registry between tests to prevent agent-mode routing
    in tests that mock the simple stream_query path."""
    clear_registry()
    yield
    clear_registry()


@pytest.fixture(autouse=True)
def _patch_decode_token_for_tests(app, monkeypatch):
    """Patch decode_token to accept HS256 test tokens (no JWKS needed)."""
    def _test_decode_token(token):
        return pyjwt.decode(
            token,
            _TEST_JWT_SECRET,
            algorithms=["HS256"],
            audience=app.config.get("IAM_AUDIENCE", "leadgen"),
        )
    monkeypatch.setattr("api.auth.decode_token", _test_decode_token)


@pytest.fixture
def seed_tenant(db):
    """Create a test tenant."""
    from api.models import Tenant
    tenant = Tenant(name="Test Corp", slug="test-corp", is_active=True)
    db.session.add(tenant)
    db.session.commit()
    return tenant


@pytest.fixture
def seed_super_admin(db):
    """Create a super admin user (IAM-only, no password)."""
    from api.models import User
    iam_id = str(uuid.uuid4())
    user = User(
        email="admin@test.com",
        password_hash=None,
        display_name="Admin User",
        is_super_admin=True,
        is_active=True,
        iam_user_id=iam_id,
    )
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def seed_user_with_role(db, seed_tenant, seed_super_admin):
    """Create a regular user with a tenant role (IAM-only, no password)."""
    from api.models import User, UserTenantRole
    iam_id = str(uuid.uuid4())
    user = User(
        email="user@test.com",
        password_hash=None,
        display_name="Regular User",
        is_super_admin=False,
        is_active=True,
        iam_user_id=iam_id,
    )
    db.session.add(user)
    db.session.flush()

    role = UserTenantRole(
        user_id=user.id,
        tenant_id=seed_tenant.id,
        role="viewer",
        granted_by=seed_super_admin.id,
    )
    db.session.add(role)
    db.session.commit()
    return user


def _make_test_token(user):
    """Generate an HS256 test token for the given user.

    Tests monkeypatch decode_token to accept HS256, so this works
    without a real JWKS endpoint.
    """
    payload = {
        "sub": user.iam_user_id,
        "email": user.email,
        "name": user.display_name,
        "aud": "leadgen",
        "exp": int(time.time()) + 3600,
    }
    return pyjwt.encode(payload, _TEST_JWT_SECRET, algorithm="HS256")


def auth_header(client, email="admin@test.com", password=None):
    """Helper: generate a test token and return Authorization header dict.

    The password parameter is accepted but ignored (kept for backwards
    compatibility with existing test call sites).
    """
    from api.models import User
    user = User.query.filter_by(email=email).first()
    if not user:
        raise ValueError(f"No user with email {email} found — seed a user first")
    token = _make_test_token(user)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def seed_companies_contacts(db, seed_tenant, seed_super_admin):
    """Seed owners, tags, companies (mixed statuses/tiers), and contacts for testing."""
    from api.models import (
        Tag, Company, CompanyEnrichmentL2, CompanyTag, CompanyTagAssignment,
        Contact, ContactEnrichment, ContactTagAssignment, Message, Owner, UserTenantRole,
    )

    # Give super_admin editor role on tenant
    role = UserTenantRole(
        user_id=seed_super_admin.id,
        tenant_id=seed_tenant.id,
        role="admin",
        granted_by=seed_super_admin.id,
    )
    db.session.add(role)

    # Owners
    owner1 = Owner(tenant_id=seed_tenant.id, name="Alice", is_active=True)
    owner2 = Owner(tenant_id=seed_tenant.id, name="Bob", is_active=True)
    db.session.add_all([owner1, owner2])
    db.session.flush()

    # Tags
    tag1 = Tag(tenant_id=seed_tenant.id, name="batch-1", is_active=True)
    tag2 = Tag(tenant_id=seed_tenant.id, name="batch-2", is_active=True)
    db.session.add_all([tag1, tag2])
    db.session.flush()

    # Companies
    companies = []
    company_data = [
        ("Acme Corp", "acme.com", "new", None, owner1.id, tag1.id, "software_saas", "Germany", 8.5),
        ("Beta Inc", "beta.io", "triage_passed", "tier_1_platinum", owner1.id, tag1.id, "it", "UK", 9.0),
        ("Gamma LLC", "gamma.co", "triage_passed", "tier_2_gold", owner2.id, tag1.id, "healthcare", "US", 7.5),
        ("Delta GmbH", "delta.de", "enriched_l2", "tier_1_platinum", owner1.id, tag2.id, "manufacturing", "Austria", 9.5),
        ("Epsilon SA", "epsilon.fr", "triage_disqualified", "tier_5_copper", owner2.id, tag2.id, "retail", "France", 3.0),
    ]
    for name, domain, status, tier, oid, bid, industry, country, score in company_data:
        c = Company(
            tenant_id=seed_tenant.id, name=name, domain=domain,
            status=status, tier=tier, owner_id=oid, tag_id=bid,
            industry=industry, hq_country=country, triage_score=score,
            summary=f"Summary for {name}", notes=f"Notes for {name}",
        )
        db.session.add(c)
        companies.append(c)
    db.session.flush()

    # Populate company_tag_assignments junction table (mirrors tag_id FK)
    for c in companies:
        if c.tag_id:
            db.session.add(CompanyTagAssignment(
                tenant_id=seed_tenant.id, company_id=c.id, tag_id=c.tag_id,
            ))
    db.session.flush()

    # L2 enrichment for Delta GmbH (module tables)
    from api.models import CompanyEnrichmentProfile, CompanyEnrichmentMarket, CompanyEnrichmentOpportunity
    l2_profile = CompanyEnrichmentProfile(
        company_id=companies[3].id,
        company_intel="Leading manufacturer in DACH region",
    )
    l2_market = CompanyEnrichmentMarket(
        company_id=companies[3].id,
        recent_news="Expanded to new markets",
    )
    l2_opportunity = CompanyEnrichmentOpportunity(
        company_id=companies[3].id,
        ai_opportunities="Process automation in supply chain",
    )
    db.session.add_all([l2_profile, l2_market, l2_opportunity])

    # Tags for Beta Inc
    tags = [
        CompanyTag(company_id=companies[1].id, category="ai_use_case", value="chatbot"),
        CompanyTag(company_id=companies[1].id, category="trigger_event", value="new_cto"),
    ]
    db.session.add_all(tags)

    # Contacts
    contacts = []
    contact_data = [
        ("John", "Doe", "CEO", companies[0].id, owner1.id, tag1.id, 85, "strong_fit", "not_started", "john@acme.com", "https://www.linkedin.com/in/johndoe"),
        ("Jane", "Smith", "CTO", companies[0].id, owner1.id, tag1.id, 90, "strong_fit", "approved", "jane@acme.com", "https://www.linkedin.com/in/janesmith"),
        ("Bob", "Wilson", "VP Engineering", companies[1].id, owner1.id, tag1.id, 75, "moderate_fit", "not_started", "bob@beta.io", "https://www.linkedin.com/in/bobwilson"),
        ("Carol", "Lee", "Director of AI", companies[1].id, owner1.id, tag1.id, 80, "strong_fit", "pending_review", "carol@beta.io", "https://www.linkedin.com/in/carollee"),
        ("Dave", "Brown", "Manager", companies[2].id, owner2.id, tag1.id, 60, "weak_fit", "not_started", None, "https://www.linkedin.com/in/davebrown"),
        ("Eve", "Green", "CFO", companies[3].id, owner1.id, tag2.id, 70, "moderate_fit", "approved", "eve@delta.de", "https://www.linkedin.com/in/evegreen"),
        ("Frank", "Black", "CIO", companies[3].id, owner1.id, tag2.id, 88, "strong_fit", "sent", "frank@delta.de", None),
        ("Grace", "White", "Sales Director", companies[4].id, owner2.id, tag2.id, 45, "weak_fit", "not_started", None, None),
        ("Hank", "Grey", "Intern", companies[4].id, owner2.id, tag2.id, 20, "unknown", "not_started", None, None),
        ("Ivy", "Blue", "Product Manager", companies[2].id, owner2.id, tag1.id, 65, "moderate_fit", "generating", "ivy@gamma.co", "https://www.linkedin.com/in/ivyblue"),
    ]
    for first, last, title, coid, oid, bid, score, icp, mstatus, email, linkedin in contact_data:
        ct = Contact(
            tenant_id=seed_tenant.id, first_name=first, last_name=last, job_title=title,
            company_id=coid, owner_id=oid, tag_id=bid,
            contact_score=score, icp_fit=icp, message_status=mstatus,
            email_address=email, linkedin_url=linkedin,
            seniority_level="c_level" if "C" in title else "director",
            department="executive" if "C" in title else "engineering",
        )
        db.session.add(ct)
        contacts.append(ct)
    db.session.flush()

    # Populate contact_tag_assignments junction table (mirrors tag_id FK)
    for ct in contacts:
        if ct.tag_id:
            db.session.add(ContactTagAssignment(
                tenant_id=seed_tenant.id, contact_id=ct.id, tag_id=ct.tag_id,
            ))
    db.session.flush()

    # Contact enrichment for John Doe
    ce = ContactEnrichment(
        contact_id=contacts[0].id,
        person_summary="Experienced CEO with AI background",
        linkedin_profile_summary="20+ years in tech leadership",
        relationship_synthesis="Warm lead via referral",
    )
    db.session.add(ce)

    # Messages for Jane Smith
    m = Message(
        tenant_id=seed_tenant.id, contact_id=contacts[1].id,
        owner_id=owner1.id, channel="linkedin_connect",
        sequence_step=1, variant="a", subject="Connect",
        body="Hi Jane, let's connect!", status="draft",
        tag_id=tag1.id,
    )
    db.session.add(m)

    db.session.commit()

    return {
        "tenant": seed_tenant,
        "owners": [owner1, owner2],
        "tags": [tag1, tag2],
        "companies": companies,
        "contacts": contacts,
    }
