#!/usr/bin/env python3
"""dogfood.py — Glassgate watching its own lifecycle, from real git history.

Reconstructs this project's true gate history by replaying every committed
version of docs/specs/glassgate/_lifecycle.md through the REAL ledger.hook_diff
code path, stamped with each commit's real timestamp. Then reconciles against
the current working-tree ledger, ingests, and reports — producing the first
glass wall built from genuine data.

This is not synthetic: every event traces to a real commit of the real ledger.

Usage:  python3 tools/dogfood.py        (run from repo root)
Zero third-party deps. Reads git history of THIS repo only (A-line untouched).
"""
from __future__ import annotations

import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from glasstrace import doctor, ingest, ledger, schema

REPO = Path(__file__).resolve().parent.parent
LEDGER_REL = "docs/specs/glassgate/_lifecycle.md"
EVENTS = REPO / "logs" / "events.jsonl"
CACHE = REPO / "logs" / "ledger-cache.json"
DB = REPO / "logs" / "trace.db"


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args],
                          capture_output=True, text=True, check=True).stdout


def to_utc_z(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ledger_commits() -> list[tuple[str, str]]:
    out = git("log", "--reverse", "--format=%h|%cI", "--", LEDGER_REL).strip().splitlines()
    return [(line.split("|")[0], to_utc_z(line.split("|")[1])) for line in out]


def main() -> int:
    # Clean slate for a reproducible dogfood run (runtime artifacts, gitignored).
    for f in (EVENTS, CACHE, DB):
        f.unlink(missing_ok=True)
    EVENTS.parent.mkdir(parents=True, exist_ok=True)

    print("== Replaying real ledger history through hook_diff ==")
    with tempfile.TemporaryDirectory() as tmp:
        proj = Path(tmp) / "glassgate"
        proj.mkdir()
        hist_ledger = proj / "_lifecycle.md"
        for sha, ts in ledger_commits():
            content = git("show", f"{sha}:{LEDGER_REL}")
            hist_ledger.write_text(content, encoding="utf-8")
            evs = ledger.hook_diff(hist_ledger, EVENTS, CACHE, actor=schema.ACTOR_CLAUDE_CODE, ts=ts)
            kinds = ", ".join(f"{e['kind']}:{e.get('gate','') or ''}={e.get('to','')}" for e in evs) or "no change"
            print(f"  {sha} @ {ts}  ->  {kinds}")

    print("\n== Reconcile against current working-tree ledger ==")
    ledgers = {"glassgate": ledger.parse_ledger((REPO / LEDGER_REL).read_text(encoding="utf-8"))}
    reconciled = ledger.reconcile_instance(ledgers, EVENTS, CACHE)
    print(f"  reconcile recorded {len(reconciled)} catch-up transition(s): "
          + (", ".join(f"{e['gate']}->{e['to']}" for e in reconciled) or "none"))

    print("\n== Ingest into SQLite index ==")
    print("  " + str(ingest.ingest([EVENTS], DB)))

    print("\n== Doctor ==")
    report = doctor.check(EVENTS, DB)
    print(doctor.render(report))

    print("\n== Final reduced state (what the wall shows) ==")
    events, _bad = schema.parse_events(EVENTS.read_text(encoding="utf-8"))
    from glasstrace import reduce
    latest = reduce.reduce_at(events)
    for gate in sorted(latest.get("glassgate", {}), key=lambda g: (len(g), g)):
        print(f"  {gate}: {latest['glassgate'][gate]}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
