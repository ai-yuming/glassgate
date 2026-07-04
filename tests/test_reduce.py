"""Story 4 · time-travel state reduction (the heart of replay).

The replay page reconstructs each lane's state AS OF a slider moment T. This
suite is the authoritative spec for that reduction; the client-side JS mirrors
it. Encodes the acceptance example verbatim: gate3 passes at 14:00, so any T
before 14:00 must still show it un-passed.
"""
import unittest

from glasstrace import reduce, schema

EVENTS = [
    schema.make_snapshot(ts="2026-07-04T10:00:00Z",
                         ledgers={"glassgate": {"gate2": "passed", "gate3": "progress"}}),
    schema.make_gate_transition(ts="2026-07-04T14:00:00Z", project="glassgate", stage="③",
                                gate="gate3", from_state="progress", to_state="passed",
                                actor="claude_code"),
]


class TimeTravelTests(unittest.TestCase):
    def test_before_transition_state_is_still_progress(self):
        s = reduce.reduce_at(EVENTS, "2026-07-04T13:00:00Z")
        self.assertEqual(s["glassgate"]["gate3"], "progress")  # not yet passed

    def test_exactly_at_transition_is_inclusive(self):
        s = reduce.reduce_at(EVENTS, "2026-07-04T14:00:00Z")
        self.assertEqual(s["glassgate"]["gate3"], "passed")

    def test_after_transition_state_is_passed(self):
        s = reduce.reduce_at(EVENTS, "2026-07-04T15:00:00Z")
        self.assertEqual(s["glassgate"]["gate3"], "passed")

    def test_latest_with_no_cutoff(self):
        s = reduce.reduce_at(EVENTS)
        self.assertEqual(s["glassgate"]["gate3"], "passed")
        self.assertEqual(s["glassgate"]["gate2"], "passed")

    def test_before_any_event_is_empty(self):
        s = reduce.reduce_at(EVENTS, "2026-07-04T09:00:00Z")
        self.assertEqual(s, {})

    def test_tool_check_events_do_not_affect_state(self):
        events = EVENTS + [schema.make_tool_check(
            ts="2026-07-04T16:00:00Z", project="glassgate", tool="Edit",
            mode="strict", action="allow", gate2="passed")]
        s = reduce.reduce_at(events)
        self.assertEqual(s["glassgate"], {"gate2": "passed", "gate3": "passed"})


if __name__ == "__main__":
    unittest.main()
