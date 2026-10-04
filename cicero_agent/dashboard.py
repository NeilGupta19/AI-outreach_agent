"""Read models for the Streamlit operator dashboard."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

from .store import SCHEMA


def _connect(database: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    return connection


def ensure_database(database: str | Path) -> None:
    """Create an empty audit database so the dashboard can open before ingestion."""
    with _connect(database) as connection:
        connection.executescript(SCHEMA)


def load_dashboard_data(database: str | Path = "cicero.db") -> dict[str, list[dict[str, Any]]]:
    ensure_database(database)
    with _connect(database) as connection:
        inbox_rows = connection.execute(
            """
            SELECT
                emails.id AS email_id,
                emails.thread_id,
                emails.sender_name,
                emails.sender_email,
                emails.subject AS email_subject,
                emails.body AS email_body,
                emails.received_at,
                emails.crm_role,
                actions.id AS action_id,
                actions.kind AS action_kind,
                actions.subject AS action_subject,
                actions.body AS action_body,
                actions.reason AS action_reason,
                actions.status AS action_status,
                actions.reply_source,
                actions.classification_json,
                actions.created_at AS action_created_at,
                events.provider_event_id,
                events.meet_link,
                events.calendar_link,
                events.slot_text
            FROM emails
            LEFT JOIN actions ON actions.email_id = emails.id
            LEFT JOIN events ON events.action_id = actions.id
            ORDER BY emails.received_at DESC, emails.ingested_at DESC
            """
        ).fetchall()
        review_rows = connection.execute(
            """
            SELECT
                reviews.id AS review_id,
                reviews.status AS review_status,
                reviews.reason AS review_reason,
                reviews.created_at AS review_created_at,
                emails.sender_name,
                emails.sender_email,
                emails.subject AS email_subject,
                emails.body AS email_body,
                actions.id AS action_id,
                actions.kind AS action_kind,
                actions.classification_json
            FROM reviews
            JOIN emails ON emails.id = reviews.email_id
            JOIN actions ON actions.id = reviews.action_id
            ORDER BY
                CASE reviews.status WHEN 'open' THEN 0 ELSE 1 END,
                reviews.created_at DESC
            """
        ).fetchall()

    inbox = [_flatten_inbox_row(row) for row in inbox_rows]
    reviews = [_flatten_review_row(row) for row in review_rows]
    return {"inbox": inbox, "reviews": reviews}


def _classification(row: sqlite3.Row) -> dict[str, Any]:
    raw = row["classification_json"]
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _flatten_inbox_row(row: sqlite3.Row) -> dict[str, Any]:
    classification = _classification(row)
    return {
        "email_id": row["email_id"],
        "thread_id": row["thread_id"],
        "from": f"{row['sender_name']} <{row['sender_email']}>",
        "sender_name": row["sender_name"],
        "sender_email": row["sender_email"],
        "subject": row["email_subject"],
        "body": row["email_body"],
        "received_at": row["received_at"],
        "crm_role": row["crm_role"],
        "role": classification.get("role", ""),
        "intent": classification.get("intent", ""),
        "confidence": classification.get("confidence"),
        "rationale": classification.get("rationale", []),
        "asks_for_call": classification.get("asks_for_call"),
        "explicit_time": classification.get("explicit_time"),
        "classification_source": classification.get("source", ""),
        "fallback_reason": classification.get("fallback_reason"),
        "action_id": row["action_id"],
        "action": row["action_kind"] or "unprocessed",
        "action_status": row["action_status"] or "",
        "action_subject": row["action_subject"] or "",
        "action_body": row["action_body"] or "",
        "action_reason": row["action_reason"] or "",
        "reply_source": row["reply_source"] or "",
        "event_id": row["provider_event_id"] or "",
        "slot_text": row["slot_text"] or "",
        "meet_link": row["meet_link"] or "",
        "calendar_link": row["calendar_link"] or "",
    }


def _flatten_review_row(row: sqlite3.Row) -> dict[str, Any]:
    classification = _classification(row)
    return {
        "review_id": row["review_id"],
        "status": row["review_status"],
        "reason": row["review_reason"],
        "created_at": row["review_created_at"],
        "from": f"{row['sender_name']} <{row['sender_email']}>",
        "subject": row["email_subject"],
        "body": row["email_body"],
        "action_id": row["action_id"],
        "action": row["action_kind"],
        "role": classification.get("role", ""),
        "intent": classification.get("intent", ""),
        "confidence": classification.get("confidence"),
        "rationale": classification.get("rationale", []),
    }
