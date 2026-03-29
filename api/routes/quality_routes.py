"""API routes for enrichment quality scoring.

Provides per-block quality scores for companies and contacts.
"""

import json

from flask import Blueprint, jsonify

from ..auth import require_auth, resolve_tenant
from ..models import db

from sqlalchemy import text

quality_bp = Blueprint("quality", __name__)


def _parse_qc_flags(val):
    """Parse qc_flags from DB (handles TEXT for SQLite, JSONB for PG)."""
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            return []
    return []


def _block_dict(score, confidence, flags, enriched_at):
    """Format a single block quality dict for API response."""
    if score is None:
        return None
    return {
        "quality_score": int(score) if score is not None else None,
        "confidence": float(confidence) if confidence is not None else None,
        "qc_flags": _parse_qc_flags(flags),
        "enriched_at": enriched_at.isoformat() if enriched_at else None,
    }


@quality_bp.route("/api/companies/<company_id>/quality", methods=["GET"])
@require_auth
def get_company_quality(company_id):
    """Return per-block enrichment quality scores for a company."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    row = db.session.execute(
        text("""
            SELECT
                l1.quality_score, l1.confidence, l1.qc_flags, l1.enriched_at,
                ep.quality_score, ep.confidence, ep.qc_flags, ep.enriched_at,
                eo.quality_score, eo.confidence, eo.qc_flags, eo.enriched_at,
                es.quality_score, es.confidence, es.qc_flags, es.enriched_at,
                cn.quality_score, cn.confidence, cn.qc_flags, cn.enriched_at,
                cl.quality_score, cl.match_confidence, cl.qc_flags, cl.enriched_at
            FROM companies c
            LEFT JOIN company_enrichment_l1 l1 ON l1.company_id = c.id
            LEFT JOIN company_enrichment_profile ep ON ep.company_id = c.id
            LEFT JOIN company_enrichment_opportunity eo ON eo.company_id = c.id
            LEFT JOIN company_enrichment_signals es ON es.company_id = c.id
            LEFT JOIN company_news cn ON cn.company_id = c.id
            LEFT JOIN company_legal_profile cl ON cl.company_id = c.id
            WHERE c.id = :company_id AND c.tenant_id = :tenant_id
        """),
        {"company_id": company_id, "tenant_id": tenant_id},
    ).fetchone()

    if not row:
        return jsonify({"error": "Company not found"}), 404

    blocks = {
        "l1": _block_dict(row[0], row[1], row[2], row[3]),
        "l2_profile": _block_dict(row[4], row[5], row[6], row[7]),
        "l2_opportunity": _block_dict(row[8], row[9], row[10], row[11]),
        "signals": _block_dict(row[12], row[13], row[14], row[15]),
        "news": _block_dict(row[16], row[17], row[18], row[19]),
        "registry": _block_dict(row[20], row[21], row[22], row[23]),
    }

    # Compute aggregate
    scored_blocks = {k: v for k, v in blocks.items() if v is not None}
    total_blocks = len(blocks)
    enriched_count = len(scored_blocks)

    if enriched_count > 0:
        avg_score = round(
            sum(b["quality_score"] for b in scored_blocks.values()) / enriched_count
        )
        lowest_block = min(
            scored_blocks, key=lambda k: scored_blocks[k]["quality_score"]
        )
        all_flags = []
        for b in scored_blocks.values():
            all_flags.extend(b["qc_flags"])
        flags_total = len(all_flags)
    else:
        avg_score = None
        lowest_block = None
        flags_total = 0

    return jsonify(
        {
            "company_id": company_id,
            "blocks": blocks,
            "aggregate": {
                "quality_score": avg_score,
                "blocks_enriched": enriched_count,
                "blocks_total": total_blocks,
                "lowest_block": lowest_block,
                "flags_total": flags_total,
            },
        }
    )


@quality_bp.route("/api/contacts/<contact_id>/quality", methods=["GET"])
@require_auth
def get_contact_quality(contact_id):
    """Return per-block enrichment quality scores for a contact."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    row = db.session.execute(
        text("""
            SELECT ce.block_quality, ce.quality_score, ce.confidence, ce.qc_flags
            FROM contacts ct
            LEFT JOIN contact_enrichment ce ON ce.contact_id = ct.id
            WHERE ct.id = :contact_id AND ct.tenant_id = :tenant_id
        """),
        {"contact_id": contact_id, "tenant_id": tenant_id},
    ).fetchone()

    if not row:
        return jsonify({"error": "Contact not found"}), 404

    # Parse block_quality JSONB
    block_quality_raw = row[0]
    block_quality = {}
    if block_quality_raw:
        if isinstance(block_quality_raw, str):
            try:
                block_quality = json.loads(block_quality_raw)
            except (json.JSONDecodeError, ValueError):
                block_quality = {}
        elif isinstance(block_quality_raw, dict):
            block_quality = block_quality_raw

    # Build blocks from block_quality JSONB
    block_names = ["person", "social", "career", "contact_details"]
    blocks = {}
    for name in block_names:
        bq = block_quality.get(name)
        if bq and isinstance(bq, dict):
            blocks[name] = {
                "quality_score": bq.get("score"),
                "confidence": bq.get("confidence"),
                "qc_flags": bq.get("flags", []),
                "field_coverage": bq.get("field_coverage"),
            }
        else:
            blocks[name] = None

    # Compute aggregate
    scored_blocks = {k: v for k, v in blocks.items() if v is not None}
    enriched_count = len(scored_blocks)
    total_blocks = len(block_names)

    if enriched_count > 0:
        avg_score = round(
            sum(
                b["quality_score"]
                for b in scored_blocks.values()
                if b["quality_score"] is not None
            )
            / enriched_count
        )
        lowest_block = min(
            (k for k, v in scored_blocks.items() if v["quality_score"] is not None),
            key=lambda k: scored_blocks[k]["quality_score"],
            default=None,
        )
        all_flags = []
        for b in scored_blocks.values():
            all_flags.extend(b.get("qc_flags", []))
        flags_total = len(all_flags)
    else:
        avg_score = None
        lowest_block = None
        flags_total = 0

    return jsonify(
        {
            "contact_id": contact_id,
            "blocks": blocks,
            "aggregate": {
                "quality_score": avg_score,
                "blocks_enriched": enriched_count,
                "blocks_total": total_blocks,
                "lowest_block": lowest_block,
                "flags_total": flags_total,
            },
        }
    )
