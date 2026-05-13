"""``flask sync-aitransformers`` CLI command (BL-1200).

Invokes :func:`api.jobs.aitransformers_contact_sync.sync_aitransformers_users`
inside a Flask app context.

Examples
--------
::

    # Default — uses env vars (AITRANSFORMERS_ADMIN_TOKEN required):
    flask sync-aitransformers

    # Sync a different tenant (e.g. a staging namespace):
    flask sync-aitransformers --tenant-slug staging-corp

    # Override page size for a probe run:
    flask sync-aitransformers --batch-size 25
"""

from __future__ import annotations

import click
from flask.cli import with_appcontext


@click.command("sync-aitransformers")
@click.option(
    "--tenant-slug",
    default=None,
    help="Override LEADGEN_AITRANSFORMERS_TENANT_SLUG for this invocation.",
)
@click.option(
    "--batch-size",
    default=None,
    type=int,
    help="Override LEADGEN_AITRANSFORMERS_BATCH_SIZE (page size).",
)
@click.option(
    "--tag-name",
    default=None,
    help="Override LEADGEN_AITRANSFORMERS_TAG_NAME (tag to apply).",
)
@with_appcontext
def sync_aitransformers_cmd(tenant_slug, batch_size, tag_name):
    """Sync AITransformers users into the Visionvolve namespace as tagged contacts."""
    # Import lazily so the CLI registration step does not pull the full
    # SQLAlchemy + requests stack before an app context is pushed.
    from api.jobs.aitransformers_contact_sync import (
        load_config,
        sync_aitransformers_users,
    )

    cfg = load_config()
    if tenant_slug:
        cfg.tenant_slug = tenant_slug
    if batch_size is not None and batch_size > 0:
        cfg.batch_size = batch_size
    if tag_name:
        cfg.tag_name = tag_name

    totals = sync_aitransformers_users(cfg)
    click.echo(f"AITransformers sync: {totals}")
