"""Story 2 · gate_transition events (ledger parsing, diff, reduce, reconcile).

Verifies WHY: every gate state change must become a durable event so any
historical moment can be rebuilt (story 4), and NO change may be lost — a
manual edit that bypasses the hook must still be captured by reconciliation
at wall-generation time (R12: zero silent loss).
"""
import unittest

from glasstrace import ledger, reduce, schema

# Glassgate-style ledger table (gate labels, glyph OR text states).
LEDGER_A = """# Glassgate — lifecycle
| Gate | State | Basis |
|---|---|---|
| gate1 立项 | ✅ 已过 | brief |
| gate2 需求设计 | ✅ 已过 | approved |
| gate3 开发实现 | 进行中 | v0.1 |
| gate4 测试验证 | ⏳ 占位 | — |
"""

# Same ledger after gate3 passes.
LEDGER_B = LEDGER_A.replace("| gate3 开发实现 | 进行中 |", "| gate3 开发实现 | ✅ 已过 |")


class ParseTests(unittest.TestCase):
    def test_maps_gates_to_canonical_states_from_glyph_and_text(self):
        states = ledger.parse_ledger(LEDGER_A)
        self.assertEqual(states["gate1"], "passed")   # ✅
        self.assertEqual(states["gate2"], "passed")   # ✅ 已过
        self.assertEqual(states["gate3"], "progress")  # text "进行中", no glyph
        self.assertEqual(states["gate4"], "todo")     # ⏳ 占位

    def test_blocked_and_hold_states(self):
        text = "| gate5 部署 | ⛔ 未过 |\n| gate6 运维 | ⏸ 挂起 |"
        states = ledger.parse_ledger(text)
        self.assertEqual(states["gate5"], "blocked")
        self.assertEqual(states["gate6"], "hold")


class DiffTests(unittest.TestCase):
    def test_diff_reports_only_changed_gates_with_from_and_to(self):
        old = ledger.parse_ledger(LEDGER_A)
        new = ledger.parse_ledger(LEDGER_B)
        changes = ledger.diff_states(old, new)
        self.assertEqual(changes, [("gate3", "progress", "passed")])

    def test_new_gate_appears_with_from_none(self):
        changes = ledger.diff_states({"gate1": "passed"},
                                     {"gate1": "passed", "gate2": "progress"})
        self.assertEqual(changes, [("gate2", None, "progress")])


class ReduceTests(unittest.TestCase):
    def test_latest_state_reduced_from_snapshot_plus_transitions(self):
        events = [
            schema.make_snapshot(ts="2026-07-04T10:00:00Z",
                                 ledgers={"glassgate": {"gate2": "progress", "gate3": "todo"}}),
            schema.make_gate_transition(ts="2026-07-04T11:00:00Z", project="glassgate",
                                        stage="②", gate="gate2", from_state="progress",
                                        to_state="passed", actor="claude_code"),
        ]
        latest = reduce.reduce_at(events)
        self.assertEqual(latest["glassgate"]["gate2"], "passed")
        self.assertEqual(latest["glassgate"]["gate3"], "todo")


class ReconcileTests(unittest.TestCase):
    def test_manual_edit_is_caught_and_emitted_as_reconcile(self):
        # The event stream believes gate3 is still progress...
        events = [
            schema.make_gate_transition(ts="2026-07-04T11:00:00Z", project="glassgate",
                                        stage="③", gate="gate3", from_state="todo",
                                        to_state="progress", actor="claude_code"),
        ]
        events_text = "\n".join(__import__("json").dumps(e) for e in events)
        # ...but the ledger on disk was hand-edited to gate3=passed, bypassing the hook.
        ledgers = {"glassgate": {"gate3": "passed"}}
        new_events, _cache = ledger.reconcile(
            ledgers, events_text, cache={}, ts="2026-07-04T20:00:00Z")
        self.assertEqual(len(new_events), 1)
        ev = new_events[0]
        self.assertEqual(ev["kind"], schema.KIND_GATE_TRANSITION)
        self.assertEqual(ev["actor"], schema.ACTOR_RECONCILE)
        self.assertEqual(ev["gate"], "gate3")
        self.assertEqual(ev["from"], "progress")  # what the stream knew
        self.assertEqual(ev["to"], "passed")      # ground truth on disk

    def test_no_drift_emits_nothing(self):
        events = [
            schema.make_gate_transition(ts="2026-07-04T11:00:00Z", project="glassgate",
                                        stage="③", gate="gate3", from_state="todo",
                                        to_state="passed", actor="claude_code"),
        ]
        events_text = "\n".join(__import__("json").dumps(e) for e in events)
        ledgers = {"glassgate": {"gate3": "passed"}}
        new_events, _cache = ledger.reconcile(ledgers, events_text, cache={},
                                             ts="2026-07-04T20:00:00Z")
        self.assertEqual(new_events, [])


if __name__ == "__main__":
    unittest.main()
