"""``flask reconcile-resend`` CLI command (BL-1045).

Invokes the Resend reconciler either for a single tenant or for every
active tenant that has a Resend API key configured.

Examples
--------
::

    # All tenants, default 30-day window, 100 rows/tenant:
    flask reconcile-resend

    # One tenant, wider window:
    flask reconcile-resend --tenant-id 8f7d2027-... --window-days 60

    # Tight batch to probe a staging run:
    flask reconcile-resend --batch-limit 10
"""

from __future__ import annotations

import click
from flask.cli import with_appcontext


@click.command("reconcile-resend")
@click.option(
    "--tenant-id",
    default=None,
    help="Restrict the run to a single tenant UUID. When omitted, every "
    "active tenant with a resend_api_key is processed.",
)
@click.option(
    "--window-days",
    default=30,
    show_default=True,
    type=int,
    help="Lookback horizon in days for email_send_log.created_at.",
)
@click.option(
    "--batch-limit",
    default=100,
    show_default=True,
    type=int,
    help="Maximum rows to reconcile per tenant per invocation.",
)
@with_appcontext
def reconcile_resend_cmd(tenant_id, window_days, batch_limit):
    """Backfill Resend engagement timestamps on ``email_send_log``."""
    # Import lazily so the CLI registration path does not pull the full
    # SQLAlchemy stack before the app context is pushed.
    from api.jobs.resend_reconciler import (
        _load_resend_key,
        reconcile_all_tenants,
        reconcile_send_logs,
    )
    from api.models import Tenant

    if tenant_id:
        tenant = Tenant.query.get(tenant_id)
        if tenant is None:
            raise click.ClickException(f"Tenant {tenant_id} not found")
        api_key = _load_resend_key(tenant)
        if not api_key:
            raise click.ClickException(
                f"Tenant {tenant_id} has no resend_api_key configured"
            )
        stats = reconcile_send_logs(
            tenant_id=tenant.id,
            api_key=api_key,
            window_days=window_days,
            batch_limit=batch_limit,
        )
        click.echo(f"Resend reconcile (tenant {tenant_id}): {stats}")
    else:
        summary = reconcile_all_tenants(
            window_days=window_days, batch_limit=batch_limit
        )
        click.echo(f"Resend reconcile (all tenants): {summary}")
