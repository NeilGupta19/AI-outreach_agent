"""Optional Google Calendar adapter for scheduling approved calls."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo

SCOPES = ["https://www.googleapis.com/auth/calendar"]

_SLOT_RE = re.compile(
    r"(?P<date>\d{4}-\d{2}-\d{2})\s+"
    r"(?P<start>\d{1,2}:\d{2})-(?P<end>\d{1,2}:\d{2})\s+"
    r"(?P<tz>[A-Za-z_/+-]+)"
)

_TZ_ALIASES = {
    "ET": "America/New_York",
    "EST": "America/New_York",
    "EDT": "America/New_York",
    "PT": "America/Los_Angeles",
    "PST": "America/Los_Angeles",
    "PDT": "America/Los_Angeles",
    "CT": "America/Chicago",
    "CST": "America/Chicago",
    "CDT": "America/Chicago",
    "MT": "America/Denver",
    "MST": "America/Denver",
    "MDT": "America/Denver",
    "UTC": "UTC",
    "IST": "Asia/Kolkata",
}


def _parse_slot(slot_text: str) -> tuple[datetime, datetime, str]:
    match = _SLOT_RE.fullmatch(slot_text.strip())
    if not match:
        raise ValueError(f"Unsupported calendar slot format: {slot_text}")
    tz_name = _TZ_ALIASES.get(match.group("tz").upper(), match.group("tz"))
    tz = ZoneInfo(tz_name)
    start = datetime.fromisoformat(f"{match.group('date')}T{match.group('start')}").replace(tzinfo=tz)
    end = datetime.fromisoformat(f"{match.group('date')}T{match.group('end')}").replace(tzinfo=tz)
    if end <= start:
        raise ValueError(f"Calendar slot must end after it starts: {slot_text}")
    return start, end, tz_name


class GoogleCalendarClient:
    def __init__(self, service: Any, calendar_id: str = "primary"):
        self.service = service
        self.calendar_id = calendar_id

    @classmethod
    def from_oauth(
        cls,
        credentials_path: str | Path = "credentials.json",
        token_path: str | Path = "calendar_token.json",
        calendar_id: str = "primary",
    ) -> "GoogleCalendarClient":
        """Run local-browser OAuth on first use and persist a Calendar token."""
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
        return cls(build("calendar", "v3", credentials=creds), calendar_id)

    def create_if_free(self, attendee: str, slot_text: str, title: str) -> dict[str, Any] | None:
        start, end, tz_name = _parse_slot(slot_text)
        busy = self.service.freebusy().query(
            body={
                "timeMin": start.astimezone(timezone.utc).isoformat(),
                "timeMax": end.astimezone(timezone.utc).isoformat(),
                "items": [{"id": self.calendar_id}],
            }
        ).execute().get("calendars", {}).get(self.calendar_id, {}).get("busy", [])
        if busy:
            return None

        request_key = f"{self.calendar_id}|{attendee}|{slot_text}|{title}".encode("utf-8")
        request_id = hashlib.sha256(request_key).hexdigest()[:32]
        event = {
            "summary": title,
            "description": "Introductory Cicero call scheduled from an inbound outreach reply.",
            "start": {"dateTime": start.isoformat(), "timeZone": tz_name},
            "end": {"dateTime": end.isoformat(), "timeZone": tz_name},
            "attendees": [{"email": attendee}],
            "conferenceData": {
                "createRequest": {
                    "requestId": f"cicero-{request_id}",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
        }
        created = self.service.events().insert(
            calendarId=self.calendar_id,
            body=event,
            conferenceDataVersion=1,
            sendUpdates="all",
        ).execute()
        return {
            "id": created.get("id"),
            "htmlLink": created.get("htmlLink"),
            "hangoutLink": created.get("hangoutLink"),
            "title": created.get("summary", title),
            "attendee": attendee,
            "when": slot_text,
            "duration_minutes": int((end - start).total_seconds() // 60),
        }
