"""Task 3 · boundary / edge-case verification.

Empty ledgers, v1-only logs, corrupt lines mixed in, and 10k-scale performance —
the conditions a real instance will actually hit. Each must degrade gracefully
and loudly (R12), never crash or silently drop.
"""
import json
import time
import tempfile
import unittest
from pathlib import Path

from glasstrace import doctor, ingest, ledger, reduce, schema, wall

LOCALE = wall.load_locale("zh")


class EmptyLedgerTests(unittest.TestCase):
    def test_ledger_with_no_gate_rows_is_empty_not_error(self):
        self.assertEqual(ledger.parse_ledger("# Title\nsome prose, no gates\n"), {})

    def test_wall_renders_with_no_ledgers_and_no_events(self):
        html = wall.build_regular({}, [], LOCALE, instance="empty", generated_at="now")
        self.assertIn(LOCALE["empty_lanes"], html)
        self.assertTrue(html.strip().startswith("<!DOCTYPE html>"))

    def test_doctor_on_nothing_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            report = doctor.check(d / "events.jsonl", d / "trace.db")
            self.assertTrue(report["ok"])
            self.assertEqual(report["valid"], 0)


class V1OnlyLogTests(unittest.TestCase):
    V1 = "\n".join([
        '{"v":1,"ts":"2026-06-18T09:03:12Z","project":"warehouse","gate2":"passed","tool":"Edit","mode":"strict","action":"allow","extra":{}}',
        '{"v":1,"ts":"2026-06-18T09:08:44Z","project":"points","gate2":"blocked","tool":"Write","mode":"strict","action":"blocked","extra":{}}',
    ])

    def test_v1_lines_normalize_to_tool_check(self):
        events, bad = schema.parse_events(self.V1)
        self.assertEqual(bad, [])
        self.assertTrue(all(e["kind"] == "tool_check" for e in events))

    def test_v1_only_log_renders_audit(self):
        events, _ = schema.parse_events(self.V1)
        html = wall.build_regular({}, events, LOCALE, instance="legacy", generated_at="now")
        self.assertIn("warehouse", html)
        self.assertIn("points", html)

    def test_v1_only_log_ingests_and_is_consistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            jl, db = d / "events.jsonl", d / "trace.db"
            jl.write_text(self.V1 + "\n", encoding="utf-8")
            self.assertEqual(ingest.ingest([jl], db)["new"], 2)
            self.assertTrue(doctor.check(jl, db)["ok"])


class BadLineTests(unittest.TestCase):
    def test_multiple_bad_lines_reported_by_number(self):
        text = "\n".join([
            json.dumps(schema.make_tool_check(ts="2026-07-04T10:00:00Z", project="p",
                                              tool="Edit", mode="strict", action="allow", gate2="passed")),
            "{ broken 1",
            "not json at all",
            json.dumps(schema.make_tool_check(ts="2026-07-04T10:01:00Z", project="p",
                                              tool="Edit", mode="strict", action="allow", gate2="passed")),
            "[1,2,3]",  # valid json but not an object
        ])
        events, bad = schema.parse_events(text)
        self.assertEqual(bad, [2, 3, 5])
        self.assertEqual(len(events), 2)

    def test_doctor_surfaces_bad_line_numbers_and_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            jl, db = d / "events.jsonl", d / "trace.db"
            jl.write_text('{"broken\n{"v":2,"ts":"2026-07-04T10:00:00Z","kind":"tool_check","project":"p","tool":"E","mode":"strict","action":"allow","gate2":"passed","extra":{}}\n', encoding="utf-8")
            ingest.ingest([jl], db)
            report = doctor.check(jl, db)
            self.assertFalse(report["ok"])
            self.assertEqual(report["bad_lines"], [1])
            self.assertIn("1", doctor.render(report))

    def test_bad_line_does_not_break_wall(self):
        text = '{ broken\n' + json.dumps(schema.make_tool_check(
            ts="2026-07-04T10:00:00Z", project="survivor", tool="Edit",
            mode="strict", action="allow", gate2="passed"))
        events, _ = schema.parse_events(text)
        html = wall.build_regular({}, events, LOCALE, instance="x", generated_at="now")
        self.assertIn("survivor", html)  # good row survives the corrupt neighbor


class PerformanceTests(unittest.TestCase):
    def test_10k_events_ingest_and_replay_under_2s(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            jl, db = d / "events.jsonl", d / "trace.db"
            lines = [json.dumps(schema.make_tool_check(
                ts=f"2026-07-04T{(i//3600)%24:02d}:{(i//60)%60:02d}:{i%60:02d}Z",
                project="glassgate", tool="Edit", mode="strict", action="allow", gate2="passed"))
                for i in range(10000)]
            jl.write_text("\n".join(lines) + "\n", encoding="utf-8")

            t0 = time.perf_counter()
            result = ingest.ingest([jl], db)
            ingest_s = time.perf_counter() - t0
            self.assertEqual(result["new"], 10000)

            events, _ = schema.parse_events(jl.read_text(encoding="utf-8"))
            t0 = time.perf_counter()
            html = wall.build_replay({"glassgate": {"gate3": "progress"}}, events, LOCALE,
                                    instance="glassgate", generated_at="now")
            replay_s = time.perf_counter() - t0

            # NFR: ingest < 2s and replay-gen < 2s at 10k events (Mac Mini baseline).
            self.assertLess(ingest_s, 2.0, f"ingest took {ingest_s:.3f}s")
            self.assertLess(replay_s, 2.0, f"replay-gen took {replay_s:.3f}s")
            self.assertTrue(html)


if __name__ == "__main__":
    unittest.main()
