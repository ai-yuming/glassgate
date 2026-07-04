"""Story 1 · Event schema v2.

Verifies WHY, not just shape: the hook must emit versioned, typed events
(`v:2`, `kind:"tool_check"`) while the reader must still parse legacy `v:1`
lines so a mixed log never breaks the glass wall. If backward compatibility
silently regressed, these tests must fail.
"""
import json
import unittest

from glasstrace import schema


class MakeToolCheckTests(unittest.TestCase):
    def test_emits_v2_and_tool_check_kind(self):
        # A freshly minted event must carry the new version and event type.
        ev = schema.make_tool_check(
            ts="2026-07-04T12:00:00Z", project="glassgate", tool="Edit",
            mode="strict", action="allow", gate2="passed",
        )
        self.assertEqual(ev["v"], 2)
        self.assertEqual(ev["kind"], schema.KIND_TOOL_CHECK)
        self.assertEqual(ev["gate2"], "passed")
        # Round-trips through JSON unchanged (this is what the hook appends).
        self.assertEqual(json.loads(json.dumps(ev)), ev)


class ParseToleranceTests(unittest.TestCase):
    def test_legacy_v1_line_normalizes_to_tool_check(self):
        # v:1 lines predate the `kind` field; the reader must infer tool_check
        # so historical audit rows still render.
        v1 = '{"v":1,"ts":"2026-06-18T09:03:12Z","project":"warehouse",' \
             '"gate2":"passed","tool":"Edit","mode":"strict","action":"allow","extra":{}}'
        events, bad = schema.parse_events(v1)
        self.assertEqual(bad, [])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], schema.KIND_TOOL_CHECK)
        self.assertEqual(events[0]["action"], "allow")  # original fields preserved

    def test_v2_line_keeps_its_kind(self):
        v2 = json.dumps(schema.make_tool_check(
            ts="2026-07-04T12:00:00Z", project="glassgate", tool="Write",
            mode="strict", action="blocked", gate2="blocked"))
        events, bad = schema.parse_events(v2)
        self.assertEqual(bad, [])
        self.assertEqual(events[0]["kind"], schema.KIND_TOOL_CHECK)

    def test_mixed_log_with_bad_line_is_loud_not_fatal(self):
        # A corrupt line must be reported by 1-based number (R12: loud), while
        # the surrounding good lines still parse — the mixed log renders.
        lines = [
            '{"v":1,"ts":"2026-06-18T09:03:12Z","project":"a","gate2":"passed","tool":"Edit","mode":"strict","action":"allow","extra":{}}',
            '{ this is not valid json',
            json.dumps(schema.make_tool_check(ts="2026-07-04T12:00:00Z", project="b",
                                              tool="Write", mode="soft", action="warned", gate2="blocked")),
            '',  # blank lines are skipped, not counted as bad
        ]
        events, bad = schema.parse_events("\n".join(lines))
        self.assertEqual(bad, [2])
        self.assertEqual(len(events), 2)

    def test_non_object_json_line_is_bad(self):
        events, bad = schema.parse_events('[1,2,3]')
        self.assertEqual(events, [])
        self.assertEqual(bad, [1])


if __name__ == "__main__":
    unittest.main()
