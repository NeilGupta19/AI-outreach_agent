"""Conservative, inspectable classifier used by the prototype.

The same interface can be backed by an LLM in production.  Rules provide a
deterministic safety layer and make the demo runnable without credentials.
"""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Callable
from .models import Classification, IncomingEmail

TIME_RE = re.compile(
    r"\b20\d\d-\d\d-\d\d\s+(?:[01]?\d|2[0-3]):[0-5]\d\s*(?:-|to)\s*(?:[01]?\d|2[0-3]):[0-5]\d\s*(?:UTC|IST|ET|PT)\b",
    re.I,
)


def _has(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def classify_rules(email: IncomingEmail) -> Classification:
    text = email.body.strip()
    rationale: list[str] = []

    # CRM is authoritative; text signals are deliberately secondary.
    if email.crm_role in {"founder", "broker"}:
        role, role_confidence = email.crm_role, 0.98
        rationale.append(f"CRM marks sender as {role}")
    elif _has(text, [r"\bI represent\b", r"\bmy client\b", r"\bbroker(?:age)?\b"]):
        role, role_confidence = "broker", 0.72
        rationale.append("broker language in reply")
    elif _has(text, [r"\bwe (?:built|run|founded)\b", r"\bour company\b"]):
        role, role_confidence = "founder", 0.65
        rationale.append("operator/founder language in reply")
    else:
        role, role_confidence = "unknown", 0.50
        rationale.append("no reliable role signal")

    time_match = TIME_RE.search(text)
    explicit_time = time_match.group(0) if time_match else None
    call_words = _has(text, [r"\b(?:call|chat|meet|meeting|schedule|calendar|book time)\b"])
    # Mentioning a meeting is not consent to create one ("I am in a meeting").
    # Require an imperative/request or availability statement before scheduling.
    asks_for_call = _has(text, [
        r"\b(?:can|could|would) (?:we|i|you)\s+(?:schedule|call|chat|meet|book)",
        r"\b(?:let'?s|please)\s+(?:schedule|call|chat|meet|book|set up)",
        r"\b(?:schedule|book|set up|send)\b.{0,40}\b(?:call|chat|meeting|invite|calendar)\b",
        r"\b(?:i'?m|i am|we'?re|we are)\s+(?:free|available)\b.{0,60}\b(?:call|chat|meet)\b",
    ])

    # Ordering matters: a negative beats a vague positive word in the same note.
    if _has(text, [r"\bnot interested\b", r"\bno thanks\b", r"\bplease remove\b", r"\bunsubscribe\b", r"\bdon't contact\b"]):
        intent, intent_confidence = "not_interested", 0.98
        rationale.append("explicit opt-out / rejection")
    elif _has(text, [r"\bnot now\b", r"\btoo early\b", r"\b(?:circle|check) back\b", r"\b(?:next|in) (?:quarter|month|year)\b"]):
        intent, intent_confidence = "not_now", 0.90
        rationale.append("deferral language")
    elif asks_for_call:
        intent, intent_confidence = "scheduling", 0.92 if explicit_time else 0.84
        rationale.append("call/scheduling language" + (" with a machine-readable time" if explicit_time else " without a confirmed time"))
    elif _has(text, [r"\bcan you (?:share|send|tell|explain)\b", r"\bwhat (?:is|are|does|would)\b", r"\?$" ]):
        intent, intent_confidence = "question", 0.75
        rationale.append("question or request for a factual answer")
    elif _has(text, [r"\binterested\b", r"\bwould like to learn\b", r"\bsend (?:me )?(?:more )?(?:info|information|details)\b"]):
        intent, intent_confidence = "info_request", 0.88
        rationale.append("positive interest / information request")
    elif _has(text, [r"\bthanks\b", r"\bsounds good\b", r"\blet'?s do it\b"]):
        intent, intent_confidence = "ambiguous", 0.55
        rationale.append("positive but lacks a clear request")
    else:
        intent, intent_confidence = "ambiguous", 0.45
        rationale.append("no supported intent pattern")

    confidence = round(min(intent_confidence, role_confidence) if role == "unknown" else intent_confidence, 2)
    return Classification(role, intent, confidence, rationale, asks_for_call, explicit_time)


def _valid_llm_result(result: Classification) -> bool:
    return (
        result.role in {"founder", "broker", "unknown"}
        and result.intent in {"not_interested", "not_now", "question", "scheduling", "info_request", "ambiguous"}
        and isinstance(result.confidence, (int, float)) and 0 <= result.confidence <= 1
        and isinstance(result.rationale, list) and 1 <= len(result.rationale) <= 3
        and isinstance(result.asks_for_call, bool)
        and (result.explicit_time is None or isinstance(result.explicit_time, str))
    )


def classify(
    email: IncomingEmail,
    llm_classifier: Callable[[IncomingEmail], Classification] | None = None,
) -> Classification:
    """Use the LLM when available; safely retain deterministic rules on any failure."""
    rules = classify_rules(email)
    if llm_classifier is None:
        return rules
    try:
        result = llm_classifier(email)
        if not _valid_llm_result(result):
            return replace(rules, fallback_reason="LLM classification failed local schema validation")
        # Never let a probabilistic result defeat hard safety signals or CRM identity.
        if rules.intent == "not_interested":
            return replace(rules, fallback_reason="Rules overrode LLM for explicit opt-out")
        if result.intent == "not_interested":
            return replace(rules, fallback_reason="LLM opt-out requires deterministic confirmation")
        if email.crm_role in {"founder", "broker"}:
            result = replace(result, role=email.crm_role)
        if result.intent == "scheduling" and (
            not rules.asks_for_call or result.explicit_time != rules.explicit_time
        ):
            return replace(rules, fallback_reason="Rules rejected unconfirmed scheduling consent or time")
        return replace(result, source="openai")
    except Exception as exc:
        return replace(rules, fallback_reason=f"OpenAI unavailable: {type(exc).__name__}")
