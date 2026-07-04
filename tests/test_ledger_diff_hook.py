"""Story 2 · ledger-diff hook end-to-end (acceptance criterion ①).

Drives the real bash hook. Proves that editing a `_lifecycle.md` produces a
`gate_transition` event whose from/to match the actual diff, and that the hook
stays silent for non-ledger writes.
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "hooks" / "ledger-diff.sh"

LEDGER_PROGRESS = "# L\n| gate2 需求 | ✅ 已过 |\n| gate3 开发 | 进行中 |\n"
LEDGER_PASSED = "# L\n| gate2 需求 | ✅ 已过 |\n| gate3 开发 | ✅ 已过 |\n"


def run_hook(target, root):
    payload = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(target)}})
    env = dict(os.environ, GLASSGATE_ROOT=str(root),
               GLASSGATE_EVENTS=str(root / "logs" / "events.jsonl"),
               GLASSGATE_CACHE=str(root / "logs" / "ledger-cache.json"),
               PYTHONPATH=str(REPO))
    return subprocess.run(["bash", str(HOOK)], input=payload, env=env,
                          capture_output=True, text=True)


class LedgerDiffHookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ledger = self.root / "projects" / "glassgate" / "_lifecycle.md"
        self.ledger.parent.mkdir(parents=True)
        self.events = self.root / "logs" / "events.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _events(self):
        if not self.events.is_file():
            return []
        return [json.loads(l) for l in self.events.read_text(encoding="utf-8").splitlines() if l.strip()]

    def test_transition_recorded_with_matching_from_to(self):
        # First write seeds the baseline snapshot (no fabricated transitions).
        self.ledger.write_text(LEDGER_PROGRESS, encoding="utf-8")
        self.assertEqual(run_hook(self.ledger, self.root).returncode, 0)
        kinds = [e["kind"] for e in self._events()]
        self.assertIn("snapshot", kinds)

        # gate3 passes -> a gate_transition must appear with from/to matching diff.
        self.ledger.write_text(LEDGER_PASSED, encoding="utf-8")
        self.assertEqual(run_hook(self.ledger, self.root).returncode, 0)
        transitions = [e for e in self._events() if e["kind"] == "gate_transition"]
        self.assertEqual(len(transitions), 1)
        t = transitions[0]
        self.assertEqual(t["gate"], "gate3")
        self.assertEqual(t["from"], "progress")
        self.assertEqual(t["to"], "passed")
        self.assertEqual(t["actor"], "claude_code")
        self.assertEqual(t["stage"], "③")  # gate3 -> stage ③

    def test_non_ledger_write_is_ignored(self):
        src = self.root / "projects" / "glassgate" / "app.py"
        src.write_text("print()\n", encoding="utf-8")
        res = run_hook(src, self.root)
        self.assertEqual(res.returncode, 0)
        self.assertEqual(self._events(), [])  # nothing recorded


if __name__ == "__main__":
    unittest.main()
