import unittest

from cicero_agent.calendar_service import GoogleCalendarClient


class Request:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class FakeFreebusy:
    def __init__(self, busy):
        self.busy = busy
        self.query_body = None

    def query(self, **kwargs):
        self.query_body = kwargs["body"]
        return Request({"calendars": {"primary": {"busy": self.busy}}})


class FakeEvents:
    def __init__(self):
        self.insert_args = None

    def insert(self, **kwargs):
        self.insert_args = kwargs
        return Request({"id": "evt-1", "summary": kwargs["body"]["summary"], "htmlLink": "https://calendar/event"})


class FakeCalendarService:
    def __init__(self, busy=None):
        self._freebusy = FakeFreebusy(busy or [])
        self._events = FakeEvents()

    def freebusy(self):
        return self._freebusy

    def events(self):
        return self._events


class CalendarServiceTests(unittest.TestCase):
    def test_clear_slot_creates_event_with_attendee_and_meet(self):
        service = FakeCalendarService()
        calendar = GoogleCalendarClient(service)

        event = calendar.create_if_free("ava@example.com", "2026-09-02 14:00-14:30 ET", "Cicero introduction")

        self.assertEqual(event["id"], "evt-1")
        self.assertEqual(event["attendee"], "ava@example.com")
        self.assertEqual(event["duration_minutes"], 30)
        self.assertEqual(service._events.insert_args["calendarId"], "primary")
        self.assertEqual(service._events.insert_args["sendUpdates"], "all")
        self.assertEqual(service._events.insert_args["conferenceDataVersion"], 1)
        body = service._events.insert_args["body"]
        self.assertEqual(body["attendees"], [{"email": "ava@example.com"}])
        self.assertEqual(body["start"]["timeZone"], "America/New_York")
        self.assertEqual(body["conferenceData"]["createRequest"]["conferenceSolutionKey"]["type"], "hangoutsMeet")

    def test_busy_slot_does_not_create_event(self):
        service = FakeCalendarService([{"start": "2026-09-02T18:00:00Z", "end": "2026-09-02T18:30:00Z"}])
        calendar = GoogleCalendarClient(service)

        event = calendar.create_if_free("ava@example.com", "2026-09-02 14:00-14:30 ET", "Cicero introduction")

        self.assertIsNone(event)
        self.assertIsNone(service._events.insert_args)


if __name__ == "__main__":
    unittest.main()
