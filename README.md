# Leadgen Pipeline

Multi-tenant B2B lead enrichment and outreach platform. Ingests company/contact lists, runs AI-powered enrichment through a multi-stage pipeline, generates personalized outreach messages, and provides a dashboard for review and management.

## Architecture

```
Browser (Dashboard)  ──→  Caddy  ──→  Flask API  ──→  PostgreSQL (RDS)
                           │
Pipeline Control     ──→  n8n webhooks  ──→  Airtable (workflow data)
```

- **Dashboard**: Vanilla HTML/JS/CSS at `leadgen.visionvolve.com/{namespace}/`
- **API**: Flask + SQLAlchemy + Gunicorn (Docker container)
- **Orchestration**: n8n (self-hosted) for enrichment pipeline workflows
- **Database**: PostgreSQL on AWS RDS, multi-tenant with `tenant_id`

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full details.

## Quick Start

### Prerequisites
- Python 3.9+
- Access to VPS (52.58.119.191) for deployment

### Install dev dependencies
```bash
pip install -r requirements-dev.txt
```

### Run tests
```bash
pytest tests/ -v
```

### Deploy
```bash
# API (Flask container)
bash deploy/deploy-api.sh

# Dashboard (static files to Caddy)
bash deploy/deploy-dashboard.sh

# Caddy config (subdomain routing)
cd /path/to/visionvolve-vps && bash scripts/deploy-caddy.sh
```

## Project Structure

```
api/                    Flask API (auth, tenants, users, messages, batches)
dashboard/              Static frontend (HTML/JS/CSS)
deploy/                 Deployment scripts and Docker compose overlays
migrations/             SQL migration files (001-004)
scripts/                Utility scripts (Airtable migration)
tests/
  unit/                 Unit tests (pytest, 37 tests)
  e2e/                  End-to-end tests
docs/
  ARCHITECTURE.md       System architecture and data flow
  specs/                Feature specifications
  postgres-migration.md Migration design document
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) - System overview, components, data flow
- [Migration Plan](docs/postgres-migration.md) - Airtable to PostgreSQL migration design
- [Workflows](WORKFLOWS.md) - n8n pipeline workflow documentation
- [Chrome Extension Setup](docs/extension-setup.md) - Install and use the VisionVolve Leads browser extension
- [Changelog](CHANGELOG.md) - Release history
- [Project Rules](CLAUDE.md) - Development workflow and standards

## Development Workflow

This project follows **spec-driven development**:

1. Write a spec in `docs/specs/` before coding
2. Create a feature branch (`feature/{name}`)
3. Write tests against the spec
4. Implement until tests pass
5. Update docs and changelog
6. Merge to `main` when complete

See [CLAUDE.md](CLAUDE.md) for full rules.
