"""Browser extension API routes for lead import, activity sync, LinkedIn queue, and status."""

from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request

from ..auth import require_auth, resolve_tenant
from ..models import (
    Activity,
    Company,
    Contact,
    ContactTagAssignment,
    LinkedInAccount,
    Tag,
    db,
)
from ..services.enum_mapper import map_enum_value

extension_bp = Blueprint("extension", __name__)


@extension_bp.route("/api/extension/leads", methods=["POST"])
@require_auth
def upload_leads():
    """Import leads from browser extension (Sales Navigator extraction)."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    data = request.get_json()
    if not data or "leads" not in data:
        return jsonify({"error": "Missing 'leads' in request body"}), 400

    leads = data["leads"]
    source = data.get("source", "sales_navigator")
    tag_name = data.get("tag")
    user = g.current_user
    owner_id = user.owner_id

    created_contacts = 0
    created_companies = 0
    skipped_duplicates = 0

    # Resolve or create tag
    tag = None
    if tag_name:
        tag = Tag.query.filter_by(tenant_id=str(tenant_id), name=tag_name).first()
        if not tag:
            tag = Tag(tenant_id=str(tenant_id), name=tag_name)
            db.session.add(tag)
            db.session.flush()

    contacts_to_tag = []

    for lead in leads:
        linkedin_url = (lead.get("linkedin_url") or "").strip()

        # Dedup by LinkedIn URL
        if linkedin_url:
            existing = Contact.query.filter_by(
                tenant_id=str(tenant_id), linkedin_url=linkedin_url
            ).first()
            if existing:
                skipped_duplicates += 1
                # Still tag duplicates so they appear under the import tag
                contacts_to_tag.append(existing.id)
                continue

        # Find or create company
        company = None
        company_name = (lead.get("company_name") or "").strip()
        if company_name:
            company = Company.query.filter(
                Company.tenant_id == str(tenant_id),
                db.func.lower(Company.name) == company_name.lower(),
            ).first()
            if not company:
                company = Company(
                    tenant_id=str(tenant_id),
                    name=company_name,
                    domain=lead.get("company_domain"),
                    industry=map_enum_value("industry", lead.get("industry")),
                    company_size=lead.get("company_size"),
                    revenue_range=lead.get("revenue_range"),
                    status="new",
                    owner_id=owner_id,
                )
                db.session.add(company)
                db.session.flush()
                created_companies += 1

        # Parse name
        full_name = (lead.get("name") or "").strip()
        parts = full_name.split(None, 1)
        first_name = parts[0] if parts else ""
        last_name = parts[1] if len(parts) > 1 else ""

        # Create contact
        contact = Contact(
            tenant_id=str(tenant_id),
            first_name=first_name,
            last_name=last_name,
            job_title=lead.get("job_title"),
            linkedin_url=linkedin_url or None,
            company_id=company.id if company else None,
            owner_id=owner_id,
            import_source=source,
            is_stub=False,
        )
        db.session.add(contact)
        db.session.flush()
        contacts_to_tag.append(contact.id)
        created_contacts += 1

    # Assign tag via junction table (used by contacts listing queries)
    if tag and contacts_to_tag:
        for contact_id in contacts_to_tag:
            exists = ContactTagAssignment.query.filter_by(
                contact_id=str(contact_id), tag_id=str(tag.id)
            ).first()
            if not exists:
                db.session.add(
                    ContactTagAssignment(
                        tenant_id=str(tenant_id),
                        contact_id=str(contact_id),
                        tag_id=str(tag.id),
                    )
                )

    db.session.commit()

    return jsonify(
        {
            "created_contacts": created_contacts,
            "created_companies": created_companies,
            "skipped_duplicates": skipped_duplicates,
            "tagged_total": len(contacts_to_tag),
        }
    )


@extension_bp.route("/api/extension/activities", methods=["POST"])
@require_auth
def upload_activities():
    """Sync activity events from browser extension."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    data = request.get_json()
    if not data or "events" not in data:
        return jsonify({"error": "Missing 'events' in request body"}), 400

    events = data["events"]
    user = g.current_user
    owner_id = user.owner_id

    created = 0
    skipped_duplicates = 0

    for event in events:
        external_id = event.get("external_id")

        # Dedup by external_id within tenant
        if external_id:
            existing = Activity.query.filter_by(
                tenant_id=str(tenant_id), external_id=external_id
            ).first()
            if existing:
                skipped_duplicates += 1
                continue

        # Resolve contact by LinkedIn URL
        contact_id = None
        linkedin_url = (event.get("contact_linkedin_url") or "").strip()
        if linkedin_url:
            contact = Contact.query.filter_by(
                tenant_id=str(tenant_id), linkedin_url=linkedin_url
            ).first()
            if not contact:
                # Create stub contact
                payload = event.get("payload", {})
                contact_name = (payload.get("contact_name") or "").strip()
                parts = contact_name.split(None, 1)
                contact = Contact(
                    tenant_id=str(tenant_id),
                    first_name=parts[0] if parts else "Unknown",
                    last_name=parts[1] if len(parts) > 1 else "",
                    linkedin_url=linkedin_url,
                    is_stub=True,
                    import_source="activity_stub",
                    owner_id=owner_id,
                )
                db.session.add(contact)
                db.session.flush()
            contact_id = contact.id

        # Parse timestamp
        ts = event.get("timestamp")
        timestamp = None
        if ts:
            try:
                timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                timestamp = datetime.now(timezone.utc)

        # Extract display fields from payload
        payload = event.get("payload", {})

        activity = Activity(
            tenant_id=str(tenant_id),
            contact_id=contact_id,
            owner_id=owner_id,
            event_type=event.get("event_type", "event"),
            activity_name=payload.get("contact_name", ""),
            activity_detail=payload.get("message", ""),
            source="linkedin_extension",
            external_id=external_id,
            occurred_at=timestamp or datetime.now(timezone.utc),
            timestamp=timestamp,
            payload=payload,
        )
        db.session.add(activity)
        created += 1

    db.session.commit()

    return jsonify({"created": created, "skipped_duplicates": skipped_duplicates})


@extension_bp.route("/api/extension/status", methods=["GET"])
@require_auth
def extension_status():
    """Get extension connection status and sync stats for current user."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    user = g.current_user
    owner_id = user.owner_id

    # Count leads imported via extension (have import_source, not stubs)
    lead_query = db.session.query(
        db.func.count(Contact.id),
        db.func.max(Contact.created_at),
    ).filter(
        Contact.tenant_id == str(tenant_id),
        Contact.import_source.isnot(None),
        Contact.is_stub.is_(False),
    )
    if owner_id:
        lead_query = lead_query.filter(Contact.owner_id == owner_id)
    lead_result = lead_query.first()
    lead_count = lead_result[0] or 0
    last_lead_sync = lead_result[1]

    # Count activities synced
    activity_query = db.session.query(
        db.func.count(Activity.id),
        db.func.max(Activity.created_at),
    ).filter(
        Activity.tenant_id == str(tenant_id),
        Activity.source == "linkedin_extension",
    )
    if owner_id:
        activity_query = activity_query.filter(Activity.owner_id == owner_id)
    activity_result = activity_query.first()
    activity_count = activity_result[0] or 0
    last_activity_sync = activity_result[1]

    connected = lead_count > 0 or activity_count > 0

    return jsonify(
        {
            "connected": connected,
            "last_lead_sync": last_lead_sync.isoformat() if last_lead_sync else None,
            "last_activity_sync": (
                last_activity_sync.isoformat() if last_activity_sync else None
            ),
            "total_leads_imported": lead_count,
            "total_activities_synced": activity_count,
        }
    )


# --- LinkedIn Send Queue (consumed by Chrome extension) ---


@extension_bp.route("/api/extension/linkedin-queue", methods=["GET"])
@require_auth
def get_linkedin_queue():
    """Pull next batch of queued LinkedIn actions for the authenticated user.

    The extension calls this to get items to process. Returned items are
    marked as 'claimed' with a claimed_at timestamp so they are not returned
    again on the next poll.

    Query params:
        limit: max items to return (default 5, max 20)

    Returns: list of queue items with contact/company context.
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    user = g.current_user
    owner_id = user.owner_id
    if not owner_id:
        return jsonify({"error": "User has no owner_id linked"}), 400

    limit = min(int(request.args.get("limit", 5)), 20)

    # Get oldest queued items for this owner
    rows = db.session.execute(
        db.text("""
            SELECT lsq.id, lsq.action_type, lsq.linkedin_url, lsq.body,
                   ct.first_name, ct.last_name, co.name AS company_name
            FROM linkedin_send_queue lsq
            JOIN contacts ct ON lsq.contact_id = ct.id
            LEFT JOIN companies co ON ct.company_id = co.id
            WHERE lsq.tenant_id = :t AND lsq.owner_id = :oid
                AND lsq.status = 'queued'
            ORDER BY lsq.created_at ASC
            LIMIT :lim
        """),
        {"t": tenant_id, "oid": owner_id, "lim": limit},
    ).fetchall()

    if not rows:
        return jsonify([])

    items = []
    claimed_ids = []
    for r in rows:
        queue_id = r[0]
        contact_name = ((r[4] or "") + " " + (r[5] or "")).strip()
        items.append(
            {
                "id": str(queue_id),
                "action_type": r[1],
                "linkedin_url": r[2],
                "body": r[3],
                "contact_name": contact_name,
                "company_name": r[6],
            }
        )
        claimed_ids.append(str(queue_id))

    # Mark as claimed
    cid_placeholders = ", ".join(f":cid_{i}" for i in range(len(claimed_ids)))
    cid_params = {f"cid_{i}": v for i, v in enumerate(claimed_ids)}
    cid_params["t"] = tenant_id
    db.session.execute(
        db.text(f"""
            UPDATE linkedin_send_queue
            SET status = 'claimed', claimed_at = CURRENT_TIMESTAMP
            WHERE tenant_id = :t AND id IN ({cid_placeholders})
        """),
        cid_params,
    )
    db.session.commit()

    return jsonify(items)


@extension_bp.route("/api/extension/linkedin-queue/<queue_id>", methods=["PATCH"])
@require_auth
def update_linkedin_queue_item(queue_id):
    """Report the result of a LinkedIn action.

    Body: { status: "sent"|"failed"|"skipped", error?: string }
    Response: { ok: true }

    On "sent": sets sent_at, also updates the source message's sent_at.
    On "failed": increments retry_count, stores error.
    On "skipped": marks as skipped (no retry).
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    user = g.current_user
    owner_id = user.owner_id
    if not owner_id:
        return jsonify({"error": "User has no owner_id linked"}), 400

    body = request.get_json(silent=True) or {}
    new_status = body.get("status")
    error_msg = body.get("error")

    if new_status not in ("sent", "failed", "skipped"):
        return jsonify({"error": "status must be 'sent', 'failed', or 'skipped'"}), 400

    # Verify ownership
    entry = db.session.execute(
        db.text("""
            SELECT id, message_id, owner_id, status
            FROM linkedin_send_queue
            WHERE id = :id AND tenant_id = :t
        """),
        {"id": queue_id, "t": tenant_id},
    ).fetchone()

    if not entry:
        return jsonify({"error": "Queue item not found"}), 404

    if str(entry[2]) != str(owner_id):
        return jsonify({"error": "Not authorized to update this queue item"}), 403

    message_id = entry[1]

    if new_status == "sent":
        db.session.execute(
            db.text("""
                UPDATE linkedin_send_queue
                SET status = 'sent', sent_at = CURRENT_TIMESTAMP, error = NULL
                WHERE id = :id AND tenant_id = :t
            """),
            {"id": queue_id, "t": tenant_id},
        )
        # Also update the source message's sent_at
        db.session.execute(
            db.text("""
                UPDATE messages
                SET sent_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = :mid AND tenant_id = :t
            """),
            {"mid": message_id, "t": tenant_id},
        )
    elif new_status == "failed":
        db.session.execute(
            db.text("""
                UPDATE linkedin_send_queue
                SET status = 'failed',
                    error = :error,
                    retry_count = retry_count + 1
                WHERE id = :id AND tenant_id = :t
            """),
            {"id": queue_id, "t": tenant_id, "error": error_msg or "Unknown error"},
        )
    elif new_status == "skipped":
        db.session.execute(
            db.text("""
                UPDATE linkedin_send_queue
                SET status = 'skipped', error = :error
                WHERE id = :id AND tenant_id = :t
            """),
            {"id": queue_id, "t": tenant_id, "error": error_msg},
        )

    db.session.commit()

    return jsonify({"ok": True})


@extension_bp.route("/api/extension/linkedin-queue/stats", methods=["GET"])
@require_auth
def linkedin_queue_stats():
    """Get daily LinkedIn usage stats for the authenticated user.

    Returns: {
        today: { sent, failed, remaining, skipped },
        limits: { connections_per_day, messages_per_day }
    }
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    user = g.current_user
    owner_id = user.owner_id
    if not owner_id:
        return jsonify({"error": "User has no owner_id linked"}), 400

    # Count items by status, scoped to today (sent_at for sent, created_at for others)
    today_stats = db.session.execute(
        db.text("""
            SELECT status, COUNT(*) AS cnt
            FROM linkedin_send_queue
            WHERE tenant_id = :t AND owner_id = :oid
                AND (
                    (status = 'sent' AND date(sent_at) = date('now'))
                    OR (status = 'failed' AND date(created_at) = date('now'))
                    OR (status = 'skipped' AND date(created_at) = date('now'))
                    OR status IN ('queued', 'claimed')
                )
            GROUP BY status
        """),
        {"t": tenant_id, "oid": owner_id},
    ).fetchall()

    counts = {r[0]: r[1] for r in today_stats}

    return jsonify(
        {
            "today": {
                "sent": counts.get("sent", 0),
                "failed": counts.get("failed", 0),
                "skipped": counts.get("skipped", 0),
                "remaining": counts.get("queued", 0) + counts.get("claimed", 0),
            },
            "limits": {
                "connections_per_day": 15,
                "messages_per_day": 40,
            },
        }
    )


@extension_bp.route("/api/extension/linkedin-identity", methods=["POST"])
@require_auth
def report_linkedin_identity():
    """Upsert the active LinkedIn account identity detected by the extension."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing request body"}), 400

    linkedin_name = (data.get("linkedin_name") or "").strip()
    linkedin_url = (data.get("linkedin_url") or "").strip()

    if not linkedin_name or not linkedin_url:
        return jsonify({"error": "linkedin_name and linkedin_url are required"}), 400

    user = g.current_user
    owner_id = user.owner_id

    # Upsert: find existing by tenant + URL, or create
    existing = LinkedInAccount.query.filter_by(
        tenant_id=str(tenant_id), linkedin_url=linkedin_url
    ).first()

    is_new = existing is None

    if existing:
        existing.linkedin_name = linkedin_name
        existing.last_seen_at = datetime.now(timezone.utc)
        existing.updated_at = datetime.now(timezone.utc)
        if owner_id:
            existing.owner_id = owner_id
        account = existing
    else:
        account = LinkedInAccount(
            tenant_id=str(tenant_id),
            owner_id=owner_id,
            linkedin_name=linkedin_name,
            linkedin_url=linkedin_url,
            last_seen_at=datetime.now(timezone.utc),
            is_active=True,
        )
        db.session.add(account)

    db.session.commit()

    return jsonify(
        {
            "id": str(account.id),
            "linkedin_name": account.linkedin_name,
            "linkedin_url": account.linkedin_url,
            "is_new": is_new,
        }
    )
