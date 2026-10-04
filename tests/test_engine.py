import unittest

from cicero_agent.classifier import classify
from cicero_agent.engine import InMemoryCalendar, decide
from cicero_agent.models import IncomingEmail
from cicero_agent.models import Classification


def email(body, role="founder"):
    return IncomingEmail("id", "thread", "Alex Lee", "alex@example.com", "Hello", body, "2026-08-30T00:00:00Z", role)


class EngineTests(unittest.TestCase):
    def test_explicit_time_creates_an_invite(self):
        c, action = decide(email("Can we schedule a call 2026-09-02 14:00-14:30 ET?"), InMemoryCalendar())
        self.assertEqual(c.intent, "scheduling")
        self.assertEqual(action.kind, "create_invite_and_reply")
        self.assertEqual(action.event["attendee"], "alex@example.com")

    def test_call_without_time_never_creates_invite(self):
        _, action = decide(email("Let's schedule a call."), InMemoryCalendar())
        self.assertEqual(action.kind, "send_reply")
        self.assertIn("cal.example", action.body)

    def test_question_is_reviewed(self):
        _, action = decide(email("What valuation range do you target?"), InMemoryCalendar())
        self.assertEqual(action.kind, "review")

    def test_opt_out_wins_over_positive_language(self):
        c, action = decide(email("Interesting, but not interested. Please remove me.", role=None), InMemoryCalendar())
        self.assertEqual(c.intent, "not_interested")
        self.assertEqual(action.kind, "suppress_contact")

    def test_unknown_role_lowers_confidence(self):
        c = classify(email("Interested, please send more info.", role=None))
        self.assertEqual(c.role, "unknown")
        self.assertLess(c.confidence, 0.8)

    def test_collision_routes_to_review(self):
        calendar = InMemoryCalendar({"2026-09-02 14:00-14:30 ET"})
        _, action = decide(email("Can we call 2026-09-02 14:00-14:30 ET?"), calendar)
        self.assertEqual(action.kind, "review")

    def test_meeting_mention_is_not_scheduling_consent(self):
        c, action = decide(email("I am in a call 2026-09-02 14:00-14:30 ET."), InMemoryCalendar())
        self.assertNotEqual(c.intent, "scheduling")
        self.assertNotEqual(action.kind, "create_invite_and_reply")

    def test_classifier_error_uses_rules_with_audit_reason(self):
        def unavailable(_):
            raise RuntimeError("network down")

        c, action = decide(email("Please send more information."), InMemoryCalendar(), llm_classifier=unavailable)
        self.assertEqual(c.source, "rules")
        self.assertIn("RuntimeError", c.fallback_reason)
        self.assertEqual(action.kind, "send_reply")

    def test_safe_llm_reply_is_used(self):
        def llm_classifier(_):
            return Classification("founder", "info_request", 0.95, ["direct request"], False, None)

        def reply_generator(*_):
            return "Re: Hello", "Hi Alex,\n\nThanks for reaching out. Happy to share more.\n\nBest,\nCicero"

        _, action = decide(email("Please send more information."), InMemoryCalendar(), llm_classifier, reply_generator)
        self.assertEqual(action.reply_source, "openai")
        self.assertEqual(action.body.splitlines()[0], "Hi Alex,")

    def test_llm_cannot_invent_a_scheduling_time(self):
        def llm_classifier(_):
            return Classification("founder", "scheduling", .99, ["invented"], True, "2026-09-02 14:00-14:30 ET")

        c, action = decide(email("Can we schedule a call?"), InMemoryCalendar(), llm_classifier)
        self.assertEqual(c.source, "rules")
        self.assertEqual(action.kind, "send_reply")


if __name__ == "__main__":
    unittest.main()
