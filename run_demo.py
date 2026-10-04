#!/usr/bin/env python3
"""Run safely with rules, or --openai with OPENAI_API_KEY set."""
from __future__ import annotations
import json
import sys
from dataclasses import asdict
from pathlib import Path
from cicero_agent.engine import InMemoryCalendar, decide
from cicero_agent.models import IncomingEmail

args = [arg for arg in sys.argv[1:] if arg != "--openai"]
use_openai = "--openai" in sys.argv[1:]
source = Path(args[0]) if args else Path("sample_data/inbox.json")
target = Path(args[1]) if len(args) > 1 else Path("sample_data/decisions.json")
llm = None
if use_openai:
    from cicero_agent.openai_service import OpenAIOutreach
    llm = OpenAIOutreach()
calendar = InMemoryCalendar()
decisions = []
for raw in json.loads(source.read_text()):
    email = IncomingEmail(**raw)
    classification, action = decide(
        email, calendar,
        llm_classifier=llm.classify if llm else None,
        reply_generator=llm.generate_reply if llm else None,
    )
    decisions.append({"email_id": email.id, "classification": asdict(classification), "action": action.to_dict()})
target.write_text(json.dumps(decisions, indent=2) + "\n")
print(f"Processed {len(decisions)} emails → {target}")
for result in decisions:
    print(f"{result['email_id']}: {result['classification']['intent']} → {result['action']['kind']}")
