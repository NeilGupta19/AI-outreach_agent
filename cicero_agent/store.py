"""SQLite audit store for inbound emails and the actions taken on them."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from .models import Action, Classification, IncomingEmail


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS emails (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    sender_name TEXT NOT NULL,
    sender_email TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    received_at TEXT NOT NULL,
    crm_role TEXT,
    prior_messages_json TEXT NOT NULL,
    rfc_message_id TEXT,
    references_header TEXT,
    ingested_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id TEXT NOT NULL UNIQUE REFERENCES emails(id),
    kind TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    reason TEXT NOT NULL,
    reply_source TEXT,
    classification_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed',
    provider_message_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id INTEGER NOT NULL UNIQUE REFERENCES actions(id),
    provider_event_id TEXT,
    title TEXT NOT NULL,
    attendee TEXT NOT NULL,
    slot_text TEXT NOT NULL,
    duration_minutes INTEGER,
    meet_link TEXT,
    calendar_link TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id INTEGER NOT NULL UNIQUE REFERENCES actions(id),
    email_id TEXT NOT NULL REFERENCES emails(id),
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_emails_thread_id ON emails(thread_id);
CREATE INDEX IF NOT EXISTS idx_actions_status ON actions(status);
CREATE INDEX IF NOT EXISTS idx_reviews_status ON reviews(status);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteStore:
    """Durable, local audit log. The Gmail message ID is the idempotency key."""

    def __init__(self, path: str | Path = "cicero.db"):
        self.path = Path(path)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "SQLiteStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def record_email(self, email: IncomingEmail) -> None:
        self._insert_email(email)
        self.connection.commit()

    def _insert_email(self, email: IncomingEmail) -> None:
        self.connection.execute(
            """
            INSERT INTO emails (
                id, thread_id, sender_name, sender_email, subject, body, received_at,
                crm_role, prior_messages_json, rfc_message_id, references_header, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                email.id, email.thread_id, email.sender_name, email.sender_email, email.subject, email.body,
                email.received_at, email.crm_role, json.dumps(email.prior_messages), email.rfc_message_id,
                email.references, _now(),
            ),
        )

    def record_decision(self, email: IncomingEmail, classification: Classification, action: Action) -> int:
        """Persist a decision atomically; repeated delivery updates the existing action."""
        now = _now()
        with self.connection:
            self._insert_email(email)
            self.connection.execute(
                """
                INSERT INTO actions (
                    email_id, kind, subject, body, reason, reply_source, classification_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(email_id) DO UPDATE SET
                    kind = excluded.kind, subject = excluded.subject, body = excluded.body,
                    reason = excluded.reason, reply_source = excluded.reply_source,
                    classification_json = excluded.classification_json, updated_at = excluded.updated_at
                """,
                (
                    email.id, action.kind, action.subject, action.body, action.reason, action.reply_source,
                    json.dumps(asdict(classification)), now, now,
                ),
            )
            action_id = self.connection.execute("SELECT id FROM actions WHERE email_id = ?", (email.id,)).fetchone()["id"]
            if action.event:
                self._record_event(action_id, action.event, now)
            if action.kind == "review":
                self.connection.execute(
                    """
                    INSERT INTO reviews (action_id, email_id, reason, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(action_id) DO UPDATE SET reason = excluded.reason
                    """,
                    (action_id, email.id, action.reason, now),
                )
        return int(action_id)

    def _record_event(self, action_id: int, event: dict[str, Any], now: str) -> None:
        self.connection.execute(
            """
            INSERT INTO events (
                action_id, provider_event_id, title, attendee, slot_text, duration_minutes,
                meet_link, calendar_link, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(action_id) DO UPDATE SET
                provider_event_id = excluded.provider_event_id, title = excluded.title,
                attendee = excluded.attendee, slot_text = excluded.slot_text,
                duration_minutes = excluded.duration_minutes, meet_link = excluded.meet_link,
                calendar_link = excluded.calendar_link, payload_json = excluded.payload_json
            """,
            (
                action_id, event.get("id"), event.get("title", ""), event.get("attendee", ""),
                event.get("when", ""), event.get("duration_minutes"), event.get("hangoutLink"),
                event.get("htmlLink"), json.dumps(event), now,
            ),
        )

    def mark_action_complete(self, action_id: int, provider_message_id: str | None = None) -> None:
        self.connection.execute(
            "UPDATE actions SET status = 'completed', provider_message_id = ?, updated_at = ? WHERE id = ?",
            (provider_message_id, _now(), action_id),
        )
        self.connection.commit()

    def mark_action_failed(self, action_id: int) -> None:
        self.connection.execute(
            "UPDATE actions SET status = 'failed', updated_at = ? WHERE id = ?", (_now(), action_id)
        )
        self.connection.commit()
