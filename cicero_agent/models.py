from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class IncomingEmail:
    id: str
    thread_id: str
    sender_name: str
    sender_email: str
    subject: str
    body: str
    received_at: str
    # In production these come from CRM enrichment / Gmail thread history.
    crm_role: str | None = None
    prior_messages: list[str] = field(default_factory=list)
    rfc_message_id: str | None = None
    references: str | None = None


@dataclass
class Classification:
    role: str                 # founder | broker | unknown
    intent: str               # interested | not_interested | not_now | question | scheduling | info_request | ambiguous
    confidence: float
    rationale: list[str]
    asks_for_call: bool
    explicit_time: str | None
    source: str = "rules"
    fallback_reason: str | None = None


@dataclass
class Action:
    kind: str                 # send_reply | create_invite_and_reply | review
    subject: str
    body: str
    reason: str
    event: dict[str, Any] | None = None
    reply_source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
