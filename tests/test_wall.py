"""Story 4 · glass wall (regular + replay) generation.

Structural verification of the generated single-file HTML. The reduction
ALGORITHM is proven in test_reduce.py; here we prove the page carries the right
data and controls, stays single-file / zero-network, and — closing story 1 —
that a mixed v1/v2 log renders without error.
"""
import json
import unittest

from glasstrace import schema, wall

LOCALE = wall.load_locale("zh")

LEDGERS = {"glassgate": {"gate2": "passed", "gate3": "progress"}}

MIXED_EVENTS, _bad = schema.parse_events("\n".join([
    '{"v":1,"ts":"2026-06-18T09:03:12Z","project":"warehouse","gate2":"passed","tool":"Edit","mode":"strict","action":"allow","extra":{}}',
    json.dumps(schema.make_tool_check(ts="2026-07-04T12:00:00Z", project="glassgate",
                                      tool="Write", mode="soft", action="warned", gate2="blocked")),
]))

REPLAY_EVENTS = [
    schema.make_snapshot(ts="2026-07-04T10:00:00Z",
                         ledgers={"glassgate": {"gate2": "passed", "gate3": "progress"}}),
    schema.make_gate_transition(ts="2026-07-04T14:00:00Z", project="glassgate", stage="③",
                                gate="gate3", from_state="progress", to_state="passed",
                                actor="claude_code"),
]


class RegularWallTests(unittest.TestCase):
    def test_mixed_v1_v2_log_renders_without_error(self):
        html = wall.build_regular(LEDGERS, MIXED_EVENTS, LOCALE,
                                  instance="glassgate", generated_at="2026-07-04 20:00:00 UTC")
        # Both a v1 (warehouse) and a v2 (glassgate) audit row must appear.
        self.assertIn("warehouse", html)
        self.assertIn("glassgate", html)
        self.assertTrue(html.strip().startswith("<!DOCTYPE html>"))

    def test_zero_network_references(self):
        html = wall.build_regular(LEDGERS, MIXED_EVENTS, LOCALE,
                                  instance="glassgate", generated_at="now")
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)


class ReplayWallTests(unittest.TestCase):
    def setUp(self):
        self.html = wall.build_replay(LEDGERS, REPLAY_EVENTS, LOCALE,
                                     instance="glassgate", generated_at="2026-07-04 20:00:00 UTC")

    def test_has_nonrealtime_banner(self):
        self.assertIn("🎬", self.html)
        self.assertIn("非实时", self.html)

    def test_embeds_event_stream_and_timeline_control(self):
        # The reducer needs the events client-side, and the user needs a slider.
        self.assertIn("2026-07-04T14:00:00Z", self.html)  # transition ts embedded
        self.assertIn('type="range"', self.html)          # draggable timeline
        self.assertIn("gate3", self.html)                 # cell to update

    def test_has_play_pause_control(self):
        self.assertIn("id=\"gg-play\"", self.html)

    def test_single_file_zero_network(self):
        self.assertNotIn("http://", self.html)
        self.assertNotIn("https://", self.html)
        self.assertNotIn("<script src", self.html)
        self.assertNotIn("<link ", self.html)

    def test_embedded_payload_is_valid_json(self):
        # Extract the embedded data island and confirm it parses + has our events.
        marker = 'id="gg-data" type="application/json">'
        start = self.html.index(marker) + len(marker)
        end = self.html.index("</script>", start)
        payload = json.loads(self.html[start:end])
        self.assertEqual(len(payload["events"]), 2)
        gates = {c["gate"] for c in payload["cells"]}
        self.assertIn("gate3", gates)


if __name__ == "__main__":
    unittest.main()
