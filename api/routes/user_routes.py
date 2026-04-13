import logging

from flask import Blueprint, g, jsonify, request

from ..auth import require_role
from ..models import Tenant, User, UserTenantRole, db

logger = logging.getLogger(__name__)

users_bp = Blueprint("users", __name__, url_prefix="/api/users")


@users_bp.route("", methods=["GET"])
@require_role("admin")
def list_users():
    user = g.current_user
    tenant_id = request.args.get("tenant_id")

    if tenant_id:
        users = (
            User.query.join(UserTenantRole, UserTenantRole.user_id == User.id)
            .filter(UserTenantRole.tenant_id == tenant_id)
            .order_by(User.created_at.desc())
            .all()
        )
    elif user.is_super_admin:
        users = User.query.order_by(User.created_at.desc()).all()
    else:
        tenant_ids = [r.tenant_id for r in user.roles]
        users = (
            User.query.join(UserTenantRole, UserTenantRole.user_id == User.id)
            .filter(UserTenantRole.tenant_id.in_(tenant_ids))
            .order_by(User.created_at.desc())
            .all()
        )

    return jsonify([u.to_dict(include_roles=True) for u in users])


@users_bp.route("", methods=["POST"])
@require_role("admin")
def create_user():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body required"}), 400

    email = (data.get("email") or "").strip().lower()
    display_name = (data.get("display_name") or "").strip()
    tenant_id = data.get("tenant_id")
    role = data.get("role", "viewer")

    if not email:
        return jsonify({"error": "email is required"}), 400

    if role not in ("admin", "editor", "viewer"):
        return jsonify({"error": "Invalid role"}), 400

    existing_user = User.query.filter_by(email=email).first()

    if existing_user:
        # User exists — grant access to the target tenant instead of rejecting
        if not tenant_id:
            return jsonify({"error": "Email already registered"}), 409

        tenant = db.session.get(Tenant, tenant_id)
        if not tenant:
            return jsonify({"error": "Tenant not found"}), 404

        existing_role = UserTenantRole.query.filter_by(
            user_id=existing_user.id, tenant_id=tenant_id
        ).first()
        if existing_role:
            return jsonify({"error": "User already has access to this namespace"}), 409

        utr = UserTenantRole(
            user_id=existing_user.id,
            tenant_id=tenant_id,
            role=role,
            granted_by=g.current_user.id,
        )
        db.session.add(utr)
        db.session.commit()

        # Ensure user exists in IAM (fire-and-forget)
        _sync_user_to_iam(existing_user.email, existing_user.display_name, tenant, role)

        return jsonify(existing_user.to_dict(include_roles=True)), 201

    if not display_name:
        return jsonify({"error": "email and display_name required"}), 400

    user = User(
        email=email,
        password_hash=None,
        display_name=display_name,
        owner_id=data.get("owner_id"),
    )
    db.session.add(user)
    db.session.flush()

    tenant = None
    if tenant_id:
        tenant = db.session.get(Tenant, tenant_id)
        if not tenant:
            db.session.rollback()
            return jsonify({"error": "Tenant not found"}), 404

        utr = UserTenantRole(
            user_id=user.id,
            tenant_id=tenant_id,
            role=role,
            granted_by=g.current_user.id,
        )
        db.session.add(utr)

    db.session.commit()

    # Create user in IAM and grant basic leadgen access
    _sync_user_to_iam(email, display_name, tenant, role)

    return jsonify(user.to_dict(include_roles=True)), 201


def _sync_user_to_iam(email, display_name, tenant=None, role="viewer"):
    """Best-effort sync: create user in IAM and log result. Never raises."""
    try:
        from ..services.iam_client import ensure_iam_user, grant_iam_access

        result = ensure_iam_user(email, display_name)
        if result and result.get("user"):
            iam_user_id = result["user"]["id"]
            scope = tenant.slug if tenant else None
            grant_iam_access(iam_user_id, app="leadgen", role=role, scope=scope)
    except Exception:
        logger.warning("IAM sync failed for %s (non-fatal)", email, exc_info=True)


@users_bp.route("/<user_id>", methods=["PUT"])
@require_role("admin")
def update_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body required"}), 400

    if "display_name" in data:
        user.display_name = data["display_name"]

    if "is_active" in data:
        user.is_active = bool(data["is_active"])

    if "owner_id" in data:
        user.owner_id = data["owner_id"] or None

    if "tenant_id" in data and "role" in data:
        tenant_id = data["tenant_id"]
        role = data["role"]
        if role not in ("admin", "editor", "viewer"):
            return jsonify({"error": "Invalid role"}), 400

        current = g.current_user
        if not current.is_super_admin:
            is_admin_on_tenant = any(
                r.tenant_id == tenant_id and r.role == "admin" for r in current.roles
            )
            if not is_admin_on_tenant:
                return jsonify({"error": "Insufficient permissions"}), 403

        existing = UserTenantRole.query.filter_by(
            user_id=user_id, tenant_id=tenant_id
        ).first()
        if existing:
            existing.role = role
        else:
            utr = UserTenantRole(
                user_id=user_id,
                tenant_id=tenant_id,
                role=role,
                granted_by=g.current_user.id,
            )
            db.session.add(utr)

    db.session.commit()
    return jsonify(user.to_dict(include_roles=True))


@users_bp.route("/<user_id>", methods=["DELETE"])
@require_role("admin")
def delete_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    user.is_active = False
    db.session.commit()
    return jsonify({"ok": True, "message": "User deactivated"})


@users_bp.route("/<user_id>/roles/<tenant_id>", methods=["DELETE"])
@require_role("admin")
def remove_user_role(user_id, tenant_id):
    current = g.current_user
    if not current.is_super_admin:
        is_admin_on_tenant = any(
            r.tenant_id == tenant_id and r.role == "admin" for r in current.roles
        )
        if not is_admin_on_tenant:
            return jsonify({"error": "Insufficient permissions"}), 403

    role = UserTenantRole.query.filter_by(user_id=user_id, tenant_id=tenant_id).first()
    if not role:
        return jsonify({"error": "Role not found"}), 404

    db.session.delete(role)
    db.session.commit()
    return jsonify({"ok": True, "message": "Role removed"})
