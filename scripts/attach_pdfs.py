#!/usr/bin/env python3
"""Attach PDF files to a campaign via the API.

Usage:
    python3 scripts/attach_pdfs.py --base-url https://leadgen-staging.visionvolve.com \
        --campaign-name "P1-A" --namespace united-arts \
        --email admin@example.com --password secret \
        uploads/campaigns/*.pdf

Environment variables (alternative to flags):
    LEADGEN_BASE_URL, LEADGEN_EMAIL, LEADGEN_PASSWORD, LEADGEN_NAMESPACE
"""

import argparse
import os
import sys

import requests


def get_token(base_url, email, password):
    """Authenticate and return JWT token."""
    resp = requests.post(
        f"{base_url}/api/auth/login",
        json={"email": email, "password": password},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def find_campaign(base_url, token, namespace, campaign_name):
    """Find campaign by name."""
    headers = {"Authorization": f"Bearer {token}", "X-Namespace": namespace}
    resp = requests.get(f"{base_url}/api/campaigns", headers=headers)
    resp.raise_for_status()
    for c in resp.json().get("campaigns", []):
        if c["name"] == campaign_name:
            return c["id"]
    return None


def upload_attachment(base_url, token, namespace, campaign_id, filepath):
    """Upload a PDF file as a campaign attachment."""
    headers = {"Authorization": f"Bearer {token}", "X-Namespace": namespace}
    filename = os.path.basename(filepath)
    with open(filepath, "rb") as f:
        resp = requests.post(
            f"{base_url}/api/campaigns/{campaign_id}/attachments",
            headers=headers,
            files={"file": (filename, f, "application/pdf")},
        )
    resp.raise_for_status()
    return resp.json()


def main():
    parser = argparse.ArgumentParser(description="Attach PDFs to a campaign")
    parser.add_argument("files", nargs="+", help="PDF files to upload")
    parser.add_argument(
        "--base-url", default=os.getenv("LEADGEN_BASE_URL", "http://localhost:5001")
    )
    parser.add_argument(
        "--email", default=os.getenv("LEADGEN_EMAIL", "test@staging.local")
    )
    parser.add_argument(
        "--password", default=os.getenv("LEADGEN_PASSWORD", "staging123")
    )
    parser.add_argument(
        "--namespace", default=os.getenv("LEADGEN_NAMESPACE", "united-arts")
    )
    parser.add_argument("--campaign-name", default="P1-A")
    args = parser.parse_args()

    print(f"Authenticating as {args.email}...")
    token = get_token(args.base_url, args.email, args.password)

    print(
        f"Looking for campaign '{args.campaign_name}' in namespace '{args.namespace}'..."
    )
    campaign_id = find_campaign(
        args.base_url, token, args.namespace, args.campaign_name
    )
    if not campaign_id:
        print(f"ERROR: Campaign '{args.campaign_name}' not found")
        sys.exit(1)
    print(f"Found campaign: {campaign_id}")

    for filepath in args.files:
        filename = os.path.basename(filepath)
        print(f"Uploading {filename}...")
        try:
            result = upload_attachment(
                args.base_url, token, args.namespace, campaign_id, filepath
            )
            print(f"  OK: id={result['id']}, size={result['size_bytes']} bytes")
        except Exception as e:
            print(f"  FAILED: {e}")

    print("Done.")


if __name__ == "__main__":
    main()
