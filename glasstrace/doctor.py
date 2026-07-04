"""Trace-layer health check.

Answers two questions loudly (R12) instead of letting bad data render a
silently-wrong wall:

  1. JSONL parse rate — how many lines fail to parse, and WHICH line numbers.
  2. DB/JSONL consistency — is the SQLite index in step with the source of
     truth, or does it need a re-ingest?

`check()` returns a structured report; `render()` turns it into human output.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import ingest as _ingest
from . import schema


def check(events_path: Path | str, db_path: Path | str) -> dict[str, Any]:
    events_path, db_path = Path(events_path), Path(db_path)
    messages: list[str] = []

    text = events_path.read_text(encoding="utf-8") if events_path.is_file() else ""
    events, bad_lines = schema.parse_events(text)
    valid = len(events)
    total = valid + len(bad_lines)

    if bad_lines:
        messages.append(f"{len(bad_lines)} line(s) unparseable in {events_path.name}: "
                        + ", ".join(str(n) for n in bad_lines))

    db_exists = db_path.is_file()
    db_count = 0
    consistent = True
    needs_ingest = False

    if db_exists:
        try:
            db_count = _ingest.count_events(db_path)
        except Exception as exc:  # corrupt db -> loud, actionable
            consistent = False
            messages.append(f"cannot read {db_path.name}: {exc} — delete it and re-run ingest")
        else:
            if db_count < valid:
                needs_ingest = True
                consistent = False
                messages.append(f"db has {db_count} event(s) but JSONL has {valid} valid line(s) "
                                f"— run: harness trace ingest")
            elif db_count > valid:
                consistent = False
                messages.append(f"db has MORE events ({db_count}) than JSONL ({valid}) "
                                f"— db may be stale (a log was removed); delete .db and re-ingest")
            else:
                messages.append(f"db consistent with JSONL ({valid} event(s))")
    elif valid > 0:
        needs_ingest = True
        messages.append(f"no trace.db yet, {valid} event(s) pending — run: harness trace ingest")

    if valid == 0 and not db_exists:
        messages.append("no events recorded yet — nothing to check")

    ok = (not bad_lines) and consistent and (not needs_ingest)
    if ok and valid > 0:
        messages.append("✅ trace layer healthy")

    return {
        "ok": ok,
        "total": total,
        "valid": valid,
        "bad_lines": bad_lines,
        "db_exists": db_exists,
        "db_count": db_count,
        "consistent": consistent,
        "needs_ingest": needs_ingest,
        "messages": messages,
    }


def render(report: dict[str, Any]) -> str:
    head = "✅ trace doctor: healthy" if report["ok"] else "❌ trace doctor: attention needed"
    lines = [head,
             f"  JSONL: {report['valid']} valid / {report['total']} line(s)",
             f"  DB:    {report['db_count']} event(s)"
             + ("" if report["db_exists"] else " (no trace.db)")]
    for msg in report["messages"]:
        lines.append(f"  · {msg}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="glasstrace.doctor",
                                 description="Trace-layer health check")
    ap.add_argument("--events", required=True)
    ap.add_argument("--db", required=True)
    args = ap.parse_args(argv)
    report = check(args.events, args.db)
    print(render(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
