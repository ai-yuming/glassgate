"""Story 5 · CLI integration smoke test.

Drives the real `cli/harness` end-to-end against a temp instance: ingest, then
doctor (healthy path), plus the bad-line loud-failure path returning a non-zero
exit code — governance tooling must exit non-zero when data is broken.
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HARNESS = REPO / "cli" / "harness"


def run(args, root):
    env = dict(os.environ, GLASSGATE_ROOT=str(root),
               GLASSGATE_EVENTS=str(root / "logs" / "events.jsonl"),
               GLASSGATE_DB=str(root / "logs" / "trace.db"))
    return subprocess.run(["bash", str(HARNESS), *args], env=env,
                          capture_output=True, text=True)


GOOD = ('{"v":2,"ts":"2026-07-04T10:00:00Z","kind":"tool_check","project":"glassgate",'
        '"actor":"gate-check","tool":"Edit","mode":"strict","action":"allow","gate2":"passed","extra":{}}')


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "logs").mkdir()
        self.events = self.root / "logs" / "events.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_version(self):
        res = run(["version"], self.root)
        self.assertEqual(res.returncode, 0)
        self.assertIn("Glassgate", res.stdout)

    def test_ingest_then_doctor_healthy(self):
        self.events.write_text(GOOD + "\n", encoding="utf-8")
        self.assertEqual(run(["trace", "ingest"], self.root).returncode, 0)
        res = run(["doctor"], self.root)
        self.assertEqual(res.returncode, 0)
        self.assertIn("healthy", res.stdout)

    def test_doctor_exits_nonzero_on_bad_data(self):
        self.events.write_text(GOOD + "\n{ broken\n", encoding="utf-8")
        res = run(["doctor"], self.root)
        self.assertEqual(res.returncode, 1)      # loud non-zero
        self.assertIn("unparseable", res.stdout)


if __name__ == "__main__":
    unittest.main()
