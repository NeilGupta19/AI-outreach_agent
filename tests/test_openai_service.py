import json
import unittest

from cicero_agent.openai_service import OpenAIOutreach
from cicero_agent.models import Classification, IncomingEmail


class FakeResponses:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return type("Response", (), {"output_text": json.dumps(self.payload)})()


class OpenAIServiceTests(unittest.TestCase):
    def test_classification_requests_strict_json_schema(self):
        responses = FakeResponses({
            "role": "founder", "intent": "info_request", "confidence": 0.94,
            "rationale": ["asks for details"], "asks_for_call": False, "explicit_time": None,
        })
        service = OpenAIOutreach(client=type("Client", (), {"responses": responses})(), model="test-model")
        email = IncomingEmail("1", "t", "Ava", "ava@example.com", "Hi", "Please send details", "now", "founder")
        result = service.classify(email)
        request = responses.requests[0]
        self.assertEqual(result.intent, "info_request")
        self.assertFalse(request["store"])
        self.assertEqual(request["text"]["format"]["type"], "json_schema")
        self.assertTrue(request["text"]["format"]["strict"])

    def test_reply_rejects_unapproved_claim(self):
        responses = FakeResponses({
            "subject": "Re: Hi", "body": "Hi Ava, pricing is $10.", "claims_used": ["invented_fact"],
        })
        service = OpenAIOutreach(client=type("Client", (), {"responses": responses})())
        email = IncomingEmail("1", "t", "Ava", "ava@example.com", "Hi", "Please send details", "now", "founder")
        with self.assertRaises(ValueError):
            service.generate_reply(email, Classification("founder", "info_request", .9, ["test"], False, None), {"company": "Cicero"})


if __name__ == "__main__":
    unittest.main()
