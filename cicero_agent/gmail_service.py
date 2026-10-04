"""Optional Gmail OAuth adapter for safely ingesting and replying to messages."""
from __future__ import annotations

import base64
import html
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
import re
from typing import Any

from .models import IncomingEmail

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]


def _headers(message: dict[str, Any]) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in message.get("payload", {}).get("headers", [])}


def _decode(data: str) -> str:
    raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    return raw.decode("utf-8", errors="replace")


def _body(payload: dict[str, Any]) -> str:
    """Prefer a text/plain MIME part; fall back to a stripped HTML part."""
    plain: list[str] = []
    html_parts: list[str] = []

    def walk(part: dict[str, Any]) -> None:
        data = part.get("body", {}).get("data")
        if data:
            if part.get("mimeType") == "text/plain":
                plain.append(_decode(data))
            elif part.get("mimeType") == "text/html":
                html_parts.append(_decode(data))
        for child in part.get("parts", []):
            walk(child)

    walk(payload)
    if plain:
        return "\n".join(plain).strip()
    if html_parts:
        text = re.sub(r"<[^>]+>", " ", "\n".join(html_parts))
        return html.unescape(re.sub(r"\s+", " ", text)).strip()
    return ""


class GmailClient:
    def __init__(self, service: Any):
        self.service = service

    @classmethod
    def from_oauth(
        cls,
        credentials_path: str | Path = "credentials.json",
        token_path: str | Path = "token.json",
    ) -> "GmailClient":
        """Run local-browser OAuth on first use and persist a refreshable token."""
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        credentials_path, token_path = Path(credentials_path), Path(token_path)
        creds = Credentials.from_authorized_user_file(token_path, SCOPES) if token_path.exists() else None
        if not creds or not creds.valid or not creds.has_scopes(SCOPES):
            if creds and creds.expired and creds.refresh_token and creds.has_scopes(SCOPES):
                creds.refresh(Request())
            else:
                if not credentials_path.exists():
                    raise FileNotFoundError(f"OAuth client file not found: {credentials_path}")
                creds = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES).run_local_server(port=0)
            token_path.write_text(creds.to_json())
        return cls(build("gmail", "v1", credentials=creds))

    def fetch_unread(self, max_results: int = 25) -> list[IncomingEmail]:
        """Fetch unread primary-inbox messages and include their complete thread context."""
        listed = self.service.users().messages().list(
            userId="me", labelIds=["INBOX", "UNREAD"], q="-from:me", maxResults=max_results
        ).execute().get("messages", [])
        emails = []
        for item in listed:
            message = self.service.users().messages().get(userId="me", id=item["id"], format="full").execute()
            thread = self.service.users().threads().get(userId="me", id=message["threadId"], format="full").execute()
            emails.append(self._to_incoming(message, thread))
        return emails

    def _to_incoming(self, message: dict[str, Any], thread: dict[str, Any]) -> IncomingEmail:
        headers = _headers(message)
        name, address = parseaddr(headers.get("from", ""))
        history = [
            _body(part.get("payload", {})) for part in thread.get("messages", []) if part.get("id") != message.get("id")
        ]
        timestamp = datetime.fromtimestamp(int(message.get("internalDate", "0")) / 1000, timezone.utc).isoformat()
        return IncomingEmail(
            id=message["id"], thread_id=message["threadId"], sender_name=name, sender_email=address,
            subject=headers.get("subject", ""), body=_body(message.get("payload", {})), received_at=timestamp,
            prior_messages=[item for item in history if item], rfc_message_id=headers.get("message-id"),
            references=headers.get("references"),
        )

    def send_reply(self, email: IncomingEmail, subject: str, body: str) -> dict[str, Any]:
        """Send a RFC 2822 reply, explicitly preserving Gmail's thread association."""
        if not email.sender_email or not email.rfc_message_id:
            raise ValueError("Cannot safely thread a reply without sender and Message-ID")
        message = EmailMessage()
        message.set_content(body)
        message["To"] = email.sender_email
        message["Subject"] = subject
        message["In-Reply-To"] = email.rfc_message_id
        message["References"] = " ".join(filter(None, [email.references, email.rfc_message_id]))
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        return self.service.users().messages().send(
            userId="me", body={"raw": raw, "threadId": email.thread_id}
        ).execute()

    def mark_read(self, message_id: str) -> dict[str, Any]:
        return self.service.users().messages().modify(
            userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}
        ).execute()
