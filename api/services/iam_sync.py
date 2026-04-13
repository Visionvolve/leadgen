"""IAM sync service — find/create local users and sync roles from IAM permissions."""

import logging
import traceback

from ..models import Tenant, User, UserTenantRole, db

logger = logging.getLogger(__name__)


def find_or_create_local_user(iam_user, db_session=None):
    """
    Find local user by iam_user_id, then by email. Create if neither exists.

    Args:
        iam_user: dict with keys: id, email, name (from IAM response)
        db_session: optional SQLAlchemy session (defaults to db.session)

    Returns:
        Local User instance (committed to DB).
    """
    session = db_session or db.session

    # Try iam_user_id first
    user = User.query.filter_by(iam_user_id=iam_user["id"]).first()
    if user:
        # Update display name if changed
        if iam_user.get("name") and user.display_name != iam_user["name"]:
            user.display_name = iam_user["name"]
            session.commit()
        return user

    # Try email match (one-time migration link)
    user = User.query.filter_by(email=iam_user["email"]).first()
    if user:
        user.iam_user_id = iam_user["id"]
        user.auth_provider = "iam"
        if iam_user.get("name"):
            user.display_name = iam_user["name"]
        session.commit()
        logger.info(
            "Linked existing user %s to IAM user %s",
            user.email,
            iam_user["id"],
        )
        return user

    # Create new user (no local password needed)
    user = User(
        email=iam_user["email"],
        display_name=iam_user.get("name") or iam_user["email"],
        iam_user_id=iam_user["id"],
        auth_provider="iam",
        password_hash=None,
    )
    session.add(user)
    session.commit()
    logger.info(
        "Created new local user %s from IAM user %s",
        user.email,
        iam_user["id"],
    )
    return user


def _normalize_permissions(iam_permissions):
    """
    Normalize IAM permissions into a list of dicts with string keys.

    Handles unexpected formats gracefully:
    - None / non-iterable -> empty list
    - String entries -> skipped with warning
    - Missing keys -> defaults to None
    - Non-string scope/role/app values -> coerced to string

    Returns:
        List of dicts, each with string keys: app, role, scope (all strings or None).
    """
    if not iam_permissions:
        return []

    if not isinstance(iam_permissions, (list, tuple)):
        logger.warning(
            "IAM permissions is not a list (got %s), treating as empty",
            type(iam_permissions).__name__,
        )
        return []

    normalized = []
    for i, perm in enumerate(iam_permissions):
        if not isinstance(perm, dict):
            logger.warning(
                "IAM permission at index %d is not a dict (got %s: %r), skipping",
                i,
                type(perm).__name__,
                perm,
            )
            continue

        # Coerce values to string or None — handles int, list, bool, etc.
        app_val = perm.get("app")
        role_val = perm.get("role")
        scope_val = perm.get("scope")

        normalized.append(
            {
                "app": str(app_val) if app_val is not None else None,
                "role": str(role_val) if role_val is not None else None,
                "scope": str(scope_val) if scope_val is not None else None,
            }
        )

    return normalized


def sync_iam_roles(local_user, iam_permissions, db_session=None):
    """
    Sync IAM permissions to local user_tenant_roles.

    Strategy: IAM is authoritative for role grants. Local roles not in IAM
    are preserved (they may be app-specific grants by a local admin).
    IAM roles are upserted -- if IAM says admin, local gets admin.

    Also handles is_super_admin mapping: IAM admin role without a scope
    (or with wildcard scope '*') maps to is_super_admin = True.

    This function is resilient to unexpected IAM data formats — it will
    log warnings but never raise exceptions that would block login.

    Args:
        local_user: User model instance
        iam_permissions: list of dicts with keys: app, role, scope
        db_session: optional SQLAlchemy session
    """
    session = db_session or db.session

    # Normalize permissions — handles None, non-list, non-dict entries
    all_perms = _normalize_permissions(iam_permissions)
    leadgen_perms = [p for p in all_perms if p.get("app") == "leadgen"]

    if not leadgen_perms:
        logger.debug(
            "No leadgen permissions found for user %s, preserving existing roles",
            local_user.email,
        )
        return

    # Check for super admin (admin with no scope or wildcard scope)
    has_super_admin_grant = any(
        p.get("role") == "admin" and p.get("scope") in (None, "", "*")
        for p in leadgen_perms
    )
    if has_super_admin_grant:
        if not local_user.is_super_admin:
            local_user.is_super_admin = True
            logger.info("Promoted user %s to super_admin via IAM", local_user.email)
    # NOTE: We intentionally do NOT demote super_admin to False here.
    # If IAM sends scoped-only perms (e.g., scope: "visionvolve" without a
    # wildcard), the existing super_admin flag is preserved. Demotion should
    # be an explicit admin action, not a side-effect of permission format.

    # Super admins get assigned to all active tenants (for any not explicitly scoped)
    if local_user.is_super_admin:
        try:
            scoped_slugs = {
                p.get("scope")
                for p in leadgen_perms
                if p.get("scope") and p.get("scope") != "*"
            }
            all_tenants = Tenant.query.filter_by(is_active=True).all()
            for tenant in all_tenants:
                if tenant.slug in scoped_slugs:
                    continue  # will be handled by explicit perm below
                try:
                    existing = UserTenantRole.query.filter_by(
                        user_id=local_user.id, tenant_id=tenant.id
                    ).first()
                    if not existing:
                        session.add(
                            UserTenantRole(
                                user_id=local_user.id,
                                tenant_id=tenant.id,
                                role="admin",
                            )
                        )
                        logger.info(
                            "Auto-granted admin to super_admin %s on tenant %s",
                            local_user.email,
                            tenant.slug,
                        )
                except Exception:
                    logger.warning(
                        "Failed to auto-grant admin on tenant %s for user %s: %s",
                        tenant.slug,
                        local_user.email,
                        traceback.format_exc(),
                    )
        except Exception:
            logger.warning(
                "Failed to process super_admin tenant grants for user %s: %s",
                local_user.email,
                traceback.format_exc(),
            )

    # Sync explicit scoped permissions — each handled independently
    for perm in leadgen_perms:
        scope = perm.get("scope")
        role = perm.get("role")
        if not scope or scope == "*" or not role:
            continue

        try:
            tenant = Tenant.query.filter_by(slug=scope, is_active=True).first()
            if not tenant:
                logger.debug(
                    "IAM scope '%s' has no matching active tenant, skipping", scope
                )
                continue

            existing = UserTenantRole.query.filter_by(
                user_id=local_user.id, tenant_id=tenant.id
            ).first()

            if existing:
                if existing.role != role:
                    logger.info(
                        "Updated role for user %s on tenant %s: %s -> %s",
                        local_user.email,
                        scope,
                        existing.role,
                        role,
                    )
                    existing.role = role
            else:
                session.add(
                    UserTenantRole(
                        user_id=local_user.id,
                        tenant_id=tenant.id,
                        role=role,
                    )
                )
                logger.info(
                    "Granted role %s to user %s on tenant %s via IAM",
                    role,
                    local_user.email,
                    scope,
                )
        except Exception:
            logger.warning(
                "Failed to sync permission (scope=%s, role=%s) for user %s: %s",
                scope,
                role,
                local_user.email,
                traceback.format_exc(),
            )

    try:
        session.commit()
    except Exception:
        logger.error(
            "Failed to commit IAM role sync for user %s, rolling back: %s",
            local_user.email,
            traceback.format_exc(),
        )
        session.rollback()
