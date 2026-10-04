#!/usr/bin/env python3
"""Streamlit dashboard for Cicero inbound-reply decisions."""
from __future__ import annotations

import argparse
from pathlib import Path

from cicero_agent.dashboard import load_dashboard_data


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--database", default="cicero.db")
    args, _ = parser.parse_known_args()
    return args


def _preview(text: str, limit: int = 260) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."


def _confidence(value: object) -> str:
    if isinstance(value, (float, int)):
        return f"{value:.0%}"
    return ""


def main() -> None:
    import streamlit as st

    args = _parse_args()
    database = Path(args.database)
    data = load_dashboard_data(database)
    inbox = data["inbox"]
    reviews = data["reviews"]
    open_reviews = [row for row in reviews if row["status"] == "open"]

    st.set_page_config(page_title="Cicero Inbox", layout="wide")
    st.title("Cicero Inbox")
    st.caption(f"SQLite audit database: `{database}`")

    metric_cols = st.columns(4)
    metric_cols[0].metric("Inbox", len(inbox))
    metric_cols[1].metric("Open Reviews", len(open_reviews))
    metric_cols[2].metric("Replies", sum(1 for row in inbox if row["action"] == "send_reply"))
    metric_cols[3].metric("Invites", sum(1 for row in inbox if row["action"] == "create_invite_and_reply"))

    tab_inbox, tab_reviews = st.tabs(["Inbox", "Review Queue"])

    with tab_inbox:
        role_filter = st.multiselect("Role", sorted({row["role"] for row in inbox if row["role"]}))
        intent_filter = st.multiselect("Intent", sorted({row["intent"] for row in inbox if row["intent"]}))
        action_filter = st.multiselect("Action", sorted({row["action"] for row in inbox if row["action"]}))
        filtered = [
            row for row in inbox
            if (not role_filter or row["role"] in role_filter)
            and (not intent_filter or row["intent"] in intent_filter)
            and (not action_filter or row["action"] in action_filter)
        ]

        st.dataframe(
            [
                {
                    "Received": row["received_at"],
                    "From": row["from"],
                    "Subject": row["subject"],
                    "Role": row["role"],
                    "Intent": row["intent"],
                    "Confidence": _confidence(row["confidence"]),
                    "Action": row["action"],
                    "Status": row["action_status"],
                }
                for row in filtered
            ],
            use_container_width=True,
            hide_index=True,
        )

        for row in filtered:
            label = f"{row['subject']} - {row['from']} - {row['intent'] or 'unclassified'}"
            with st.expander(label):
                cols = st.columns([1, 1, 1])
                cols[0].write(f"Role: `{row['role'] or 'unknown'}`")
                cols[1].write(f"Confidence: `{_confidence(row['confidence']) or 'n/a'}`")
                cols[2].write(f"Action: `{row['action']}`")
                st.write("Classification rationale")
                st.write(row["rationale"] or [])
                st.write("Incoming reply")
                st.text_area("Email body", row["body"], height=140, key=f"email-{row['email_id']}", disabled=True)
                if row["action_body"]:
                    st.write("Proposed/sent reply")
                    st.text_area("Action body", row["action_body"], height=150, key=f"action-{row['email_id']}", disabled=True)
                if row["slot_text"] or row["meet_link"]:
                    st.write("Calendar")
                    st.write({"slot": row["slot_text"], "meet": row["meet_link"], "event": row["event_id"]})

    with tab_reviews:
        if not reviews:
            st.info("No review items yet.")
        else:
            st.dataframe(
                [
                    {
                        "Created": row["created_at"],
                        "Status": row["status"],
                        "From": row["from"],
                        "Subject": row["subject"],
                        "Intent": row["intent"],
                        "Confidence": _confidence(row["confidence"]),
                        "Reason": row["reason"],
                    }
                    for row in reviews
                ],
                use_container_width=True,
                hide_index=True,
            )
            for row in reviews:
                with st.expander(f"Review #{row['review_id']} - {row['subject']} - {row['status']}"):
                    st.write(f"From: `{row['from']}`")
                    st.write(f"Reason: {row['reason']}")
                    st.write(f"Classification: `{row['role']}` / `{row['intent']}` / `{_confidence(row['confidence']) or 'n/a'}`")
                    st.write(row["rationale"] or [])
                    st.text_area("Message", _preview(row["body"], 2000), height=180, key=f"review-{row['review_id']}", disabled=True)


if __name__ == "__main__":
    main()
