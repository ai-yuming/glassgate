"""Story 3 · SQLite derived index.

Verifies WHY: SQLite is a *derived* index, JSONL is the only source of truth.
So ingest must be idempotent (re-running adds no duplicate rows) and a db
deleted and rebuilt from the same JSONL must produce byte-identical query
results — proving nothing lives only in the database.
"""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from glasstrace import ingest, schema


def write_jsonl(path, events):
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


BASELINE = [
    schema.make_snapshot(ts="2026-07-04T10:00:00Z",
                         ledgers={"glassgate": {"gate2": "progress", "gate3": "todo"}}),
    schema.make_tool_check(ts="2026-07-04T10:05:00Z", project="glassgate", tool="Edit",
                           mode="strict", action="allow", gate2="passed"),
    schema.make_gate_transition(ts="2026-07-04T11:00:00Z", project="glassgate", stage="②",
                                gate="gate2", from_state="progress", to_state="passed",
                                actor="claude_code"),
]


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.jsonl = self.dir / "events.jsonl"
        self.db = self.dir / "trace.db"
        write_jsonl(self.jsonl, BASELINE)

    def tearDown(self):
        self.tmp.cleanup()

    def _rows(self):
        conn = sqlite3.connect(self.db)
        events = conn.execute("SELECT ts,kind,project,gate,from_state,to_state FROM events ORDER BY id").fetchall()
        latest = conn.execute("SELECT project,gate,state,as_of FROM latest_state ORDER BY project,gate").fetchall()
        conn.close()
        return events, latest

    def test_ingest_is_idempotent(self):
        r1 = ingest.ingest([self.jsonl], self.db)
        self.assertEqual(r1["new"], 3)
        self.assertEqual(r1["skipped"], 0)
        events1, _ = self._rows()
        self.assertEqual(len(events1), 3)

        # Re-running must add zero rows and skip everything.
        r2 = ingest.ingest([self.jsonl], self.db)
        self.assertEqual(r2["new"], 0)
        self.assertEqual(r2["skipped"], 3)
        events2, _ = self._rows()
        self.assertEqual(len(events2), 3)  # no duplicates

    def test_delete_and_rebuild_is_identical(self):
        ingest.ingest([self.jsonl], self.db)
        before = self._rows()
        self.db.unlink()  # nuke the derived index
        ingest.ingest([self.jsonl], self.db)
        after = self._rows()
        self.assertEqual(before, after)  # JSONL is the single source of truth

    def test_latest_state_reflects_reduction(self):
        # Intentional ordering: the snapshot (10:00) sets gate2=progress, then the
        # transition (11:00) sets gate2=passed. The test proves reduction honors
        # chronological order — the later event must win.
        ingest.ingest([self.jsonl], self.db)
        _events, latest = self._rows()
        state = {(p, g): s for (p, g, s, _asof) in latest}
        self.assertEqual(state[("glassgate", "gate2")], "passed")  # transition won
        self.assertEqual(state[("glassgate", "gate3")], "todo")    # from snapshot

    def test_bad_line_is_counted_not_fatal(self):
        self.jsonl.write_text(
            json.dumps(BASELINE[0]) + "\n{ broken json\n" + json.dumps(BASELINE[2]) + "\n",
            encoding="utf-8")
        result = ingest.ingest([self.jsonl], self.db)
        self.assertEqual(result["bad"], 1)
        self.assertEqual(result["new"], 2)


if __name__ == "__main__":
    unittest.main()
