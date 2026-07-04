"""Story 1 · gate-check hook emits v2 events.

Drives the real bash hook via subprocess with synthetic stdin. Verifies WHY:
every gate ruling must land as a v2 `tool_check` line, and a blocked ruling
under strict mode must actually block (exit 2) — governance must never be
silently downgraded.
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "hooks" / "gate-check.sh"

LEDGER_GATE2_PASSED = """# Lifecycle
| Gate | State |
|---|---|
| gate2 requirements | ✅ 已过 | approved |
| gate3 build | 进行中 | — |
"""

# NOTE: this ledger DOES carry an explicit `gate2` line — the hook must find it,
# see neither ✅ nor 已过, and therefore treat gate2 as not-passed. The block is
# driven by an explicit unpassed gate, not by an absent line.
LEDGER_GATE2_BLOCKED = """# Lifecycle
| Gate | State |
|---|---|
| gate2 requirements | ⛔ 未过 | not yet |
"""


def run_hook(tool_name, file_path, events_path, mode="strict"):
    payload = json.dumps({"tool_name": tool_name, "tool_input": {"file_path": file_path}})
    env = dict(os.environ, GLASSGATE_EVENTS=str(events_path), GLASSGATE_MODE=mode)
    return subprocess.run(
        ["bash", str(HOOK)], input=payload, env=env,
        capture_output=True, text=True,
    )


class GateCheckHookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.events = self.root / "logs" / "events.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _project(self, name, ledger_text):
        proj = self.root / "projects" / name
        proj.mkdir(parents=True)
        (proj / "_lifecycle.md").write_text(ledger_text, encoding="utf-8")
        return proj

    def _last_event(self):
        lines = [l for l in self.events.read_text(encoding="utf-8").splitlines() if l.strip()]
        return json.loads(lines[-1])

    def test_allow_appends_v2_tool_check(self):
        proj = self._project("demo", LEDGER_GATE2_PASSED)
        target = proj / "src.py"
        res = run_hook("Edit", str(target), self.events)
        self.assertEqual(res.returncode, 0)
        ev = self._last_event()
        self.assertEqual(ev["v"], 2)
        self.assertEqual(ev["kind"], "tool_check")
        self.assertEqual(ev["action"], "allow")
        self.assertEqual(ev["gate2"], "passed")
        self.assertEqual(ev["tool"], "Edit")

    def test_strict_block_exits_2_and_records_blocked(self):
        proj = self._project("demo", LEDGER_GATE2_BLOCKED)
        target = proj / "src.py"
        res = run_hook("Write", str(target), self.events, mode="strict")
        self.assertEqual(res.returncode, 2)  # governance actually blocks
        ev = self._last_event()
        self.assertEqual(ev["v"], 2)
        self.assertEqual(ev["kind"], "tool_check")
        self.assertEqual(ev["action"], "blocked")
        self.assertEqual(ev["mode"], "strict")

    def test_soft_block_warns_but_exits_0(self):
        proj = self._project("demo", LEDGER_GATE2_BLOCKED)
        target = proj / "src.py"
        res = run_hook("Write", str(target), self.events, mode="soft")
        self.assertEqual(res.returncode, 0)
        ev = self._last_event()
        self.assertEqual(ev["action"], "warned")
        self.assertEqual(ev["mode"], "soft")

    def test_no_target_path_records_skip_and_allows(self):
        payload = json.dumps({"tool_name": "Write", "tool_input": {}})
        env = dict(os.environ, GLASSGATE_EVENTS=str(self.events), GLASSGATE_MODE="strict")
        res = subprocess.run(["bash", str(HOOK)], input=payload, env=env,
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        ev = self._last_event()
        self.assertEqual(ev["action"], "skip")


if __name__ == "__main__":
    unittest.main()
