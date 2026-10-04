import base64
import unittest
from email import message_from_bytes

from cicero_agent.gmail_service import GmailClient


def encoded(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def gmail_message(message_id, thread_id, sender, subject, body, internal_date="1720000000000"):
    return {
        "id": message_id, "threadId": thread_id, "internalDate": internal_date,
        "payload": {"mimeType": "text/plain", "headers": [
            {"name": "From", "value": sender}, {"name": "Subject", "value": subject},
            {"name": "Message-ID", "value": f"<{message_id}@example.com>"},
            {"name": "References", "value": "<old@example.com>"},
        ], "body": {"data": encoded(body)}},
    }


class Request:
    def __init__(self, value): self.value = value
    def execute(self): return self.value


class FakeMessages:
    def __init__(self, incoming):
        self.incoming, self.sent, self.modified, self.list_args = incoming, [], [], None
    def list(self, **kwargs): self.list_args = kwargs; return Request({"messages": [{"id": "new", "threadId": "thread-1"}]})
    def get(self, **kwargs): return Request(self.incoming)
    def send(self, **kwargs): self.sent.append(kwargs); return Request({"id": "sent-1"})
    def modify(self, **kwargs): self.modified.append(kwargs); return Request({"id": kwargs["id"]})


class FakeThreads:
    def __init__(self, thread): self.thread = thread; self.get_args = None
    def get(self, **kwargs): self.get_args = kwargs; return Request(self.thread)


class FakeUsers:
    def __init__(self, messages, threads): self._messages, self._threads = messages, threads
    def messages(self): return self._messages
    def threads(self): return self._threads


class GmailServiceTests(unittest.TestCase):
    def setUp(self):
        self.incoming = gmail_message("new", "thread-1", "Ava Founder <ava@example.com>", "Hello", "Could you send details?")
        self.thread = {"messages": [gmail_message("old", "thread-1", "Team <team@cicero.example>", "Hello", "Original outreach"), self.incoming]}
        self.messages = FakeMessages(self.incoming)
        self.threads = FakeThreads(self.thread)
        self.gmail = GmailClient(type("Service", (), {"users": lambda _self: FakeUsers(self.messages, self.threads)})())

    def test_fetches_unread_message_and_thread_history(self):
        email = self.gmail.fetch_unread()[0]
        self.assertEqual(self.messages.list_args["labelIds"], ["INBOX", "UNREAD"])
        self.assertEqual(email.sender_email, "ava@example.com")
        self.assertEqual(email.prior_messages, ["Original outreach"])
        self.assertEqual(self.threads.get_args["format"], "full")

    def test_send_reply_preserves_thread_headers_and_marks_read(self):
        email = self.gmail.fetch_unread()[0]
        result = self.gmail.send_reply(email, "Re: Hello", "Thanks, Ava.")
        raw = self.messages.sent[0]["body"]
        mime = message_from_bytes(base64.urlsafe_b64decode(raw["raw"] + "=" * (-len(raw["raw"]) % 4)))
        self.assertEqual(result["id"], "sent-1")
        self.assertEqual(raw["threadId"], "thread-1")
        self.assertEqual(mime["In-Reply-To"], "<new@example.com>")
        self.assertIn("<old@example.com>", mime["References"])
        self.gmail.mark_read(email.id)
        self.assertEqual(self.messages.modified[0]["body"], {"removeLabelIds": ["UNREAD"]})


if __name__ == "__main__":
    unittest.main()
