from __future__ import annotations

from typing import Callable

from .classifier import classify
from .models import Action, Classification, IncomingEmail

COMPANY_FACTS = {
    "company": "Cicero",
    "offer": "a focused conversation about the opportunity and whether a partnership could be useful",
    "scheduler_url": "https://cal.example/cicero-intro",
    "sender": "The Cicero team",
}


class InMemoryCalendar:
    """A stand-in for Google Calendar. Records busy slots so collisions are testable."""
    def __init__(self, busy: set[str] | None = None):
        self.busy = busy or set()

    def create_if_free(self, attendee: str, slot_text: str, title: str) -> dict | None:
        # The classifier only passes ISO-like slots. Time-zone conversion is intentionally
        # deferred to the real Calendar adapter; this mock retains the agreed wording.
        if slot_text in self.busy:
            return None
        event = {"title": title, "attendee": attendee, "when": slot_text, "duration_minutes": 30, "id": f"evt-{len(self.busy)+1}"}
        self.busy.add(slot_text)
        return event


def _greeting(email: IncomingEmail) -> str:
    first = email.sender_name.split()[0] if email.sender_name else "there"
    return f"Hi {first},"


def _reply(email: IncomingEmail, c: Classification) -> tuple[str, str]:
    greeting = _greeting(email)
    if c.intent == "not_interested":
        return "Re: " + email.subject, f"{greeting}\n\nUnderstood — we won’t follow up further. Thanks for letting us know.\n\nBest,\n{COMPANY_FACTS['sender']}"
    if c.intent == "not_now":
        return "Re: " + email.subject, f"{greeting}\n\nThanks for the candid note. We’ll hold off for now and can reconnect when timing is better.\n\nBest,\n{COMPANY_FACTS['sender']}"
    if c.intent in {"interested", "info_request"}:
        noun = "your company" if c.role == "founder" else "the opportunity"
        return "Re: " + email.subject, f"{greeting}\n\nThanks for the interest. We’d be glad to share more about {COMPANY_FACTS['offer']} for {noun}. If helpful, you can pick a time here: {COMPANY_FACTS['scheduler_url']}\n\nBest,\n{COMPANY_FACTS['sender']}"
    if c.intent == "scheduling" and not c.explicit_time:
        return "Re: " + email.subject, f"{greeting}\n\nHappy to set up a 30-minute call. Please choose a convenient time here: {COMPANY_FACTS['scheduler_url']}, or send two or three time windows with your time zone.\n\nBest,\n{COMPANY_FACTS['sender']}"
    return "Re: " + email.subject, ""


def _generated_or_rule_reply(
    email: IncomingEmail,
    classification: Classification,
    reply_generator: Callable[[IncomingEmail, Classification, dict[str, str]], tuple[str, str]] | None,
) -> tuple[str, str, str]:
    if reply_generator is not None:
        try:
            subject, body = reply_generator(email, classification, COMPANY_FACTS)
            if subject.strip() and body.strip():
                return subject, body, "openai"
        except Exception:
            pass
    subject, body = _reply(email, classification)
    return subject, body, "rules"


def decide(
    email: IncomingEmail,
    calendar: InMemoryCalendar,
    llm_classifier: Callable[[IncomingEmail], Classification] | None = None,
    reply_generator: Callable[[IncomingEmail, Classification, dict[str, str]], tuple[str, str]] | None = None,
) -> tuple[Classification, Action]:
    c = classify(email, llm_classifier)
    # Suppression is a deterministic compliance action, never contingent on role inference.
    # We do not send an acknowledgement: replying to an unsubscribe can itself be unwanted.
    if c.intent == "not_interested":
        return c, Action("suppress_contact", "", "", "Explicit rejection or opt-out; add sender to suppression list.")
    # A low-confidence reading, role ambiguity for commercial discussion, or any question
    # is not safe enough to answer autonomously without a knowledge-grounded answer.
    if c.intent in {"ambiguous", "question"} or c.confidence < 0.80:
        return c, Action("review", "", "", "Low confidence or factual question requires human review.")
    if c.intent == "scheduling" and c.explicit_time:
        event = calendar.create_if_free(email.sender_email, c.explicit_time, "Cicero introduction")
        if not event:
            return c, Action("review", "", "", "Requested time is unavailable; needs a proposed alternative.")
        subject = "Re: " + email.subject
        body = f"{_greeting(email)}\n\nGreat — I’ve sent a 30-minute calendar invite for {c.explicit_time}. Looking forward to speaking.\n\nBest,\n{COMPANY_FACTS['sender']}"
        return c, Action("create_invite_and_reply", subject, body, "Explicit call request and explicit time window.", event)
    subject, body, source = _generated_or_rule_reply(email, c, reply_generator)
    return c, Action("send_reply", subject, body, "Clear, bounded response; no unsupported claims.", reply_source=source)
