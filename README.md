# Cicero inbound-reply agent — prototype submission

This is a deliberately conservative, runnable prototype for turning inbound outreach replies into either a safe reply, a calendar invite, or a human-review task. It runs against a mock inbox and calendar so it can be evaluated without OAuth credentials or sending an email.

```bash
python3 -m unittest discover -v
python3 run_demo.py
# optional, after: pip install -r requirements.txt and export OPENAI_API_KEY=...
python3 run_demo.py --openai
```

The second command reads [`sample_data/inbox.json`](sample_data/inbox.json), prints each decision, and writes a complete audit record to `sample_data/decisions.json`. The sample demonstrates: information request → reply, explicit time → invite plus reply, not-now → reply, question/ambiguous → review, and opt-out → suppression. It uses only Python’s standard library.

### OpenAI mode

[`openai_service.py`](cicero_agent/openai_service.py) adds an optional OpenAI Responses API adapter. It sends both classification and reply generation through strict `json_schema` structured outputs, requests `store=False`, and treats the inbound email as untrusted data. Run with `--openai` to enable it; without the flag the original deterministic path remains the default. If the API is unavailable, the classification output fails local validation, or a draft has an unapproved claim/link/prohibited commitment, the agent uses the rule classifier and bounded template instead. This implementation follows the OpenAI Responses API’s `text.format` JSON-schema structured-output mechanism. [Official API reference](https://platform.openai.com/docs/api-reference/responses-streaming/response/refusal?lang=python)

### Gmail + Calendar mode

[`gmail_service.py`](cicero_agent/gmail_service.py) uses OAuth with only `gmail.modify` and `gmail.send`. [`calendar_service.py`](cicero_agent/calendar_service.py) uses a separate Calendar OAuth token with `calendar` scope, queries `freeBusy`, and inserts events only for policy-approved scheduling actions. Create a **Desktop app** OAuth client in a Google Cloud project with the Gmail and Calendar APIs enabled, then save its download as `credentials.json` in this directory. These credentials and the refresh tokens (`token.json`, `calendar_token.json`) are ignored by Git. The first send run may open consent flows; later runs refresh the saved tokens.

```bash
pip install -r requirements.txt
python3 run_gmail.py                 # reads and evaluates unread inbox messages; does not send
python3 run_gmail.py --send           # sends bounded replies; for scheduling, creates the invite first
python3 run_gmail.py --send --openai  # additionally enables the structured-output LLM path
streamlit run streamlit_app.py -- --database cicero.db
```

The Gmail runner lists unread inbox messages, fetches each complete thread with `format="full"`, and passes prior bodies to the classifier. It sends RFC 2822 MIME mail encoded as Gmail `raw`, setting `threadId`, `In-Reply-To`, and `References` so the response remains in its conversation. On `--send`, if the policy action is `create_invite_and_reply`, the runner first checks Calendar availability, creates a 30-minute event with the external attendee and Google Meet request, then sends the threaded Gmail confirmation and marks the source message read. Suppression/review actions are deliberately left unread until their own adapters complete. Google documents the Gmail OAuth desktop flow and token refresh pattern in its [Python quickstart](https://developers.google.com/workspace/gmail/api/quickstart/python), documents Gmail `raw` MIME encoding and reply-thread headers in its [sending guide](https://developers.google.com/workspace/gmail/api/guides/sending), and documents Calendar event insertion with attendees, `sendUpdates`, and `conferenceDataVersion` in the [events.insert reference](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert).

### SQLite audit database

[`store.py`](cicero_agent/store.py) persists the operational audit trail to `cicero.db` (or `--database /path/to/file.db`) using only Python's built-in `sqlite3`. `emails` stores the inbound source message; `actions` stores its classification and proposed/executed action, keyed by Gmail message ID; `events` stores created Calendar/Meet metadata; and `reviews` stores open human-review work. The source-message key makes repeated Gmail delivery idempotent at the decision-record level. `cicero.db` is Git-ignored because it can contain sensitive email content.

### Streamlit dashboard

[`streamlit_app.py`](streamlit_app.py) provides a lightweight operator dashboard over the SQLite audit database. It shows the inbox, sender role, intent classification, confidence, proposed/executed action, action status, calendar metadata, and a dedicated review queue. The dashboard is read-only in this prototype so reviewing operators can inspect decisions without accidentally sending or resolving anything from the UI.

## Design and flow

```text
Gmail watch / poll → thread + CRM enrichment → classify → policy gate ─→ review queue
                                                       │
                                  ┌────────────────────┼───────────────────┐
                                  ↓                    ↓                   ↓
                              suppression         bounded reply    availability + invite
                                  │                    │                   │
                               CRM DNC            Gmail send        Calendar then Gmail
```

`run_demo.py` supplies `IncomingEmail` objects; [`classifier.py`](cicero_agent/classifier.py) produces an explicit, auditable classification; [`engine.py`](cicero_agent/engine.py) applies the send/schedule policy. The in-memory calendar intentionally supports a collision path so it is testable, while the Gmail runner can swap in Google Calendar `freeBusy` plus `events.insert` when `--send` is used.

## 1. Intent classification

The classifier yields `{role, intent, confidence, rationale, asks_for_call, explicit_time}`. CRM role is preferred (0.98 confidence); only when it is absent does it use textual signals such as “I represent a client” (broker) or “we built/run” (founder). Intent is an ordered rule set: explicit opt-out/rejection takes priority, then deferral (“not now”, “next quarter”), scheduling language, questions, and positive information requests. A structured LLM extraction call would sit behind the same schema in production, with the deterministic rules used as a validator/override for opt-outs.

This can misread sarcasm, unusual phrasing, quoted text, assistants writing on someone’s behalf, or a broker who does not identify as one. It can also confuse “I’m interested, but not now” without the priority ordering. The prototype does not auto-send on `ambiguous`, questions, or confidence below 0.80. Confidence is not treated as truth: its rationale is retained for a reviewer, and a labeled production set should be evaluated by intent/role, especially false sends and false opt-outs.

## 2. Reply quality and tone control

For the demo, replies are constrained templates with recipient-name personalization and a small approved fact set. That makes the “what can be said” boundary visible and prevents invented deal terms. The natural-language production version would pass the thread summary, sender role, classified intent, approved CRM fields, and an approved Cicero voice guide to an LLM, requesting a JSON `{subject, body, claims_used}` result. The system prompt would require: concise, warm, specific writing; no valuation, mandate, exclusivity, legal, pricing, or timing commitments; no claims outside supplied facts; one clear next step; and ask/review rather than guess.

Before send, validate the schema, require every named claim to map to an approved field, scan for forbidden commitments, preserve Gmail thread headers, and reject links/domains outside an allow-list. Question answers are review-only in this prototype because a fluent ungrounded response is worse than a slower one.

## 3. Scheduling trigger and logic

An invite is created only when both conditions are met: the reply explicitly asks to call/schedule **and** contains an unambiguous ISO-like time window with a time zone (for example, `2026-09-02 14:00-14:30 ET`). A request without a time gets a scheduler link / request for windows; a vague “sounds good” goes to review. This prevents the common mistake of turning general interest into a meeting.

The real adapter would: normalize candidate windows to UTC; query Google Calendar `freeBusy`; respect business hours, host assignment, minimum notice and event duration; use an idempotency key `(thread_id, normalized slot)`; insert one event with attendee and conference link; then send the confirmation only after Calendar returns an event ID. If the slot becomes unavailable, it offers approved alternatives rather than double-booking. The prototype’s calendar models the same ordering and routes an occupied exact slot to review.

## 4. Guardrails and failure handling

The policy is intentionally asymmetric. Explicit unsubscribe/rejection becomes a deterministic suppression-list action with no reply. Low-confidence, unclear role, factual questions, no time-zone, unavailable times, LLM schema failures, Gmail/Calendar errors, or duplicate delivery all enter a review/retry queue; they do not fall back to an auto-send. Every decision stores source message ID, classification, rationale, proposed action, timestamps, provider IDs, and prompt/model version. Gmail and Calendar writes use idempotency keys and retry only safe, transient failures.

Human review is where external facts or material commercial judgment are involved: questions about terms, sensitive deal details, uncertainty, and exceptions. Clear acknowledgements, scheduling-link replies, and explicit opted-out contacts are automated because their blast radius is bounded. In an initial rollout I would use draft-only mode, sample automated sends daily, and promote each intent separately after measuring false-send rate.

## 5. Architecture and reasoning

The design separates ingestion, enrichment, classification, policy, composition, execution, and audit so that an LLM cannot directly call Gmail or Calendar. Gmail and Calendar are natural choices because they own the thread and availability; a small worker/queue is sufficient for the prototype. At hundreds of replies/day, use Gmail Pub/Sub push notifications, a durable queue, per-thread locking/idempotency storage, rate limits, encrypted audit storage, dead-letter queues, observability, and a reviewer console. CRM enrichment and a knowledge retrieval service would provide role and approved facts.

Deliberately left out: a hosted worker, real natural-language date resolution, CRM persistence, a reviewer UI, durable idempotency storage, and richer Calendar host/round-robin assignment. The mocked input is intentional: it makes the decision policy repeatable and safe to evaluate in a short build rather than hiding it behind live credentials.

## 6. Data handling

Email and deal context are sensitive. Minimize what leaves the controlled environment: redact attachments, signatures, phone numbers, and unrelated thread content; send only the last relevant messages plus approved facts; use an enterprise LLM agreement with no training/retention, regional controls, encryption in transit/at rest, strict service accounts and least-privilege Gmail/Calendar scopes. Store provider IDs and redacted audit fields where possible, segment tenant data, set short retention/deletion policies, and log access without logging raw prompts. Do not put raw email bodies into metrics, error trackers, or reviewer exports. A DPA/security review and explicit authorization for each mailbox are prerequisites to production.
