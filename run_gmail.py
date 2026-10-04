#!/usr/bin/env python3
"""Read unread Gmail messages. Use --send to actually transmit eligible replies."""
from __future__ import annotations

import argparse
import sys

from cicero_agent.engine import InMemoryCalendar, decide
from cicero_agent.calendar_service import GoogleCalendarClient
from cicero_agent.gmail_service import GmailClient
from cicero_agent.store import SQLiteStore

parser = argparse.ArgumentParser()
parser.add_argument("--send", action="store_true", help="Send only policy-approved reply actions; default is dry-run.")
parser.add_argument("--max-results", type=int, default=25)
parser.add_argument("--credentials", default="credentials.json")
parser.add_argument("--token", default="token.json")
parser.add_argument("--calendar-token", default="calendar_token.json")
parser.add_argument("--calendar-id", default="primary")
parser.add_argument("--database", default="cicero.db", help="SQLite audit database path")
parser.add_argument("--openai", action="store_true")
args = parser.parse_args()

try:
    gmail = GmailClient.from_oauth(args.credentials, args.token)
except FileNotFoundError as exc:
    print(str(exc), file=sys.stderr)
    print(
        "\nTo use Gmail mode, create a Google Cloud OAuth Desktop app client with the Gmail API enabled, "
        f"download it, and save it as {args.credentials!r} in this directory.\n"
        f"You can also pass a different path with: python3 run_gmail.py --credentials /path/to/client_secret.json\n"
        "Until then, run the mock prototype with: python3 run_demo.py",
        file=sys.stderr,
    )
    sys.exit(2)

calendar = InMemoryCalendar()
if args.send:
    try:
        calendar = GoogleCalendarClient.from_oauth(args.credentials, args.calendar_token, args.calendar_id)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        print(
            "\nCalendar integration uses the same Google Cloud OAuth Desktop app client as Gmail. "
            f"Save it as {args.credentials!r}, or pass it with --credentials.",
            file=sys.stderr,
        )
        sys.exit(2)

llm = None
if args.openai:
    from cicero_agent.openai_service import OpenAIOutreach
    llm = OpenAIOutreach()

with SQLiteStore(args.database) as store:
    for email in gmail.fetch_unread(args.max_results):
        classification, action = decide(email, calendar, llm.classify if llm else None, llm.generate_reply if llm else None)
        action_id = store.record_decision(email, classification, action)
        print(f"{email.id}: {classification.intent} → {action.kind}")
        # Suppression and review have their own integrations; don't mark them read here.
        if args.send and action.kind in {"send_reply", "create_invite_and_reply"}:
            try:
                sent = gmail.send_reply(email, action.subject, action.body)
                gmail.mark_read(email.id)
                store.mark_action_complete(action_id, sent["id"])
                print(f"  sent Gmail message {sent['id']} and marked source read")
                if action.event:
                    print(f"  created Calendar event {action.event['id']}")
            except Exception:
                store.mark_action_failed(action_id)
                raise
        elif action.kind == "send_reply":
            print("  dry-run: no email sent")
        elif action.kind == "create_invite_and_reply":
            print("  dry-run: no calendar event or email sent")
