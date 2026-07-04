"""Story 5 · trace-layer self-check.

Verifies WHY: bad data must fail LOUD (R12), not render a silently-wrong wall.
doctor reports the JSONL parse rate with offending line numbers, flags when the
db has fallen behind the JSONL (prompting ingest), and passes cleanly only when
everything is consistent.
"""
import json
import tempfile
import unittest
from pathlib import Path

from glasstrace import doctor, ingest, schema


def write_jsonl(path, events):
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


EVENTS = [
    schema.make_tool_check(ts="2026-07-04T10:00:00Z", project="glassgate", tool="Edit",
                           mode="strict", action="allow", gate2="passed"),
    schema.make_gate_transition(ts="2026-07-04T11:00:00Z", project="glassgate", stage="③",
                                gate="gate3", from_state="progress", to_state="passed",
                                actor="claude_code"),
]


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.jsonl = self.dir / "events.jsonl"
        self.db = self.dir / "trace.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_healthy_when_consistent(self):
        write_jsonl(self.jsonl, EVENTS)
        ingest.ingest([self.jsonl], self.db)
        report = doctor.check(self.jsonl, self.db)
        self.assertTrue(report["ok"])
        self.assertEqual(report["bad_lines"], [])
        self.assertTrue(report["consistent"])

    def test_bad_line_reported_with_line_number(self):
        self.jsonl.write_text(
            json.dumps(EVENTS[0]) + "\n{ not json here\n" + json.dumps(EVENTS[1]) + "\n",
            encoding="utf-8")
        ingest.ingest([self.jsonl], self.db)
        report = doctor.check(self.jsonl, self.db)
        self.assertFalse(report["ok"])
        self.assertEqual(report["bad_lines"], [2])  # the offending line number
        text = doctor.render(report)
        self.assertIn("2", text)  # line number surfaced to the human

    def test_db_behind_jsonl_prompts_ingest(self):
        write_jsonl(self.jsonl, EVENTS[:1])
        ingest.ingest([self.jsonl], self.db)   # db now has 1 event
        write_jsonl(self.jsonl, EVENTS)         # JSONL grows to 2, db not re-ingested
        report = doctor.check(self.jsonl, self.db)
        self.assertTrue(report["needs_ingest"])
        self.assertFalse(report["ok"])
        self.assertIn("ingest", doctor.render(report).lower())

    def test_db_missing_prompts_ingest(self):
        write_jsonl(self.jsonl, EVENTS)
        report = doctor.check(self.jsonl, self.db)  # never ingested
        self.assertTrue(report["needs_ingest"])
        self.assertFalse(report["ok"])

    def test_no_events_is_clean(self):
        report = doctor.check(self.jsonl, self.db)  # nothing exists
        self.assertTrue(report["ok"])
        self.assertEqual(report["valid"], 0)


if __name__ == "__main__":
    unittest.main()
