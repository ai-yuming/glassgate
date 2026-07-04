"""Story 2 ② × Story 4 · reconcile fires at wall generation.

Acceptance ② requires that a manual ledger edit (bypassing the hook) is caught
"at the next wall generation". This proves the wiring: running the wall CLI over
an instance whose ledger drifted from the event stream appends an
`actor:"reconcile"` catch-up event — zero silent loss, end to end.
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HARNESS = REPO / "cli" / "harness"

LEDGER = "# L\n| gate2 需求 | ✅ 已过 |\n| gate3 开发 | ✅ 已过 |\n"


class ReconcileWiringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "logs").mkdir()
        self.events = self.root / "logs" / "events.jsonl"
        proj = self.root / "projects" / "glassgate"
        proj.mkdir(parents=True)
        (proj / "_lifecycle.md").write_text(LEDGER, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _events(self):
        if not self.events.is_file():
            return []
        return [json.loads(l) for l in self.events.read_text(encoding="utf-8").splitlines() if l.strip()]

    def test_wall_generation_reconciles_manual_edit(self):
        # Baseline the event stream so it already knows gate2=passed, gate3=progress
        # (a snapshot). Only gate3 will then be the manual-edit drift.
        self.events.write_text("\n".join([
            json.dumps({"v": 2, "ts": "2026-07-04T10:00:00Z", "kind": "snapshot",
                        "project": None, "actor": "reconcile",
                        "ledgers": {"glassgate": {"gate2": "passed", "gate3": "progress"}},
                        "extra": {}}),
            json.dumps({"v": 2, "ts": "2026-07-04T11:00:00Z", "kind": "gate_transition",
                        "project": "glassgate", "actor": "claude_code", "stage": "③",
                        "gate": "gate3", "from": "todo", "to": "progress", "extra": {}}),
        ]) + "\n", encoding="utf-8")
        # ...but the ledger on disk says gate3=passed (hand-edited, hook never ran).
        env = dict(os.environ, GLASSGATE_ROOT=str(self.root),
                   GLASSGATE_EVENTS=str(self.events),
                   GLASSGATE_DB=str(self.root / "logs" / "trace.db"))
        res = subprocess.run(["bash", str(HARNESS), "wall", "--out", str(self.root / "wall.html")],
                             env=env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)

        reconciled = [e for e in self._events()
                      if e.get("kind") == "gate_transition" and e.get("actor") == "reconcile"]
        self.assertEqual(len(reconciled), 1)
        self.assertEqual(reconciled[0]["gate"], "gate3")
        self.assertEqual(reconciled[0]["from"], "progress")
        self.assertEqual(reconciled[0]["to"], "passed")


if __name__ == "__main__":
    unittest.main()
