import unittest
from datetime import datetime, timezone, timedelta
from app.external_monitor import evaluate


class ExternalMonitorTests(unittest.TestCase):
    def test_outage_recovery_and_duplicate_suppression(self):
        state = {}
        sent = []
        notify = lambda kind: sent.append(kind)
        for _ in range(5):
            state = evaluate(state, healthy=False, notify=notify)
        self.assertEqual(sent, ["outage"])
        for _ in range(3):
            state = evaluate(state, healthy=True, notify=notify)
        self.assertEqual(sent, ["outage", "recovered"])

    def test_planned_stop_suppresses_alerts_and_resets_failure_count(self):
        sent = []
        state = evaluate({"failures": 2}, healthy=False, planned_stop=True, notify=sent.append)
        self.assertEqual(sent, [])
        self.assertEqual(state["observed"], "planned-stop")
        self.assertEqual(state["failures"], 0)

    def test_failed_notification_is_retried_and_not_marked_delivered(self):
        def broken(kind):
            raise OSError("delivery unavailable")
        state = {}
        for _ in range(3):
            state = evaluate(state, healthy=False, notify=broken)
        self.assertEqual(state["delivery"], "failed")
        sent = []
        state = evaluate(state, healthy=False, notify=sent.append)
        self.assertEqual(sent, ["outage"])
