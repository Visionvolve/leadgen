"""Flask CLI command registration.

Commands are wired into the app factory via :func:`register_commands`.
"""

from __future__ import annotations

from .aitransformers_sync import sync_aitransformers_cmd
from .reconcile import reconcile_resend_cmd


def register_commands(app) -> None:
    """Attach all CLI commands to the Flask app."""
    app.cli.add_command(reconcile_resend_cmd)
    app.cli.add_command(sync_aitransformers_cmd)


__all__ = ["register_commands"]
