import sqlite3
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from cicero_agent.models import Action, Classification, IncomingEmail
from cicero_agent.store import SQLiteStore


def email() -> IncomingEmail:
    return IncomingEmail("gmail-1", "thread-1", "Ava Doe", "ava@example.com", "Intro", "Let's talk", "2026-09-01T00:00:00Z")


def classification() -> Classification:
    return Classification("founder", "scheduling", 0.95, ["explicit time"], True, "2026-09-02 14:00-14:30 ET")


class SQLiteStoreTests(unittest.TestCase):
    def test_persists_email_action_and_event(self):
        with TemporaryDirectory() as directory:
            database = Path(directory) / "cicero.db"
            with SQLiteStore(database) as store:
                action_id = store.record_decision(email(), classification(), Action(
                    "create_invite_and_reply", "Re: Intro", "Confirmed", "Approved scheduling.",
                    event={"id": "event-1", "title": "Cicero introduction", "attendee": "ava@example.com",
                           "when": "2026-09-02 14:00-14:30 ET", "duration_minutes": 30,
                           "hangoutLink": "https://meet.google.com/abc"},
                ))
                store.mark_action_complete(action_id, "sent-1")

            connection = sqlite3.connect(database)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM emails").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT status, provider_message_id FROM actions").fetchone(), ("completed", "sent-1"))
            self.assertEqual(connection.execute("SELECT provider_event_id, meet_link FROM events").fetchone(), ("event-1", "https://meet.google.com/abc"))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM reviews").fetchone()[0], 0)

    def test_review_is_idempotent_and_recorded(self):
        with TemporaryDirectory() as directory:
            with SQLiteStore(Path(directory) / "cicero.db") as store:
                action = Action("review", "", "", "Low confidence requires review.")
                first_id = store.record_decision(email(), classification(), action)
                second_id = store.record_decision(email(), classification(), action)
                self.assertEqual(first_id, second_id)
                self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM emails").fetchone()[0], 1)
                self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM actions").fetchone()[0], 1)
                row = store.connection.execute("SELECT reason, status FROM reviews").fetchone()
                self.assertEqual(tuple(row), ("Low confidence requires review.", "open"))


if __name__ == "__main__":
    unittest.main()
