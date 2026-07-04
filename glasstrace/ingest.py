"""Ingest the JSONL event stream into the SQLite derived index.

SQLite is only a query accelerator: it can be deleted and rebuilt from JSONL at
any time with identical results. Idempotency comes from ``UNIQUE(src_line)`` —
each source line maps to one row, so re-ingesting the same file is a no-op.

`latest_state` is a materialized view of the reduced current state, rebuilt
wholesale on every ingest (cheap, and keeps it exactly consistent with the
event rows).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from . import ledger as _ledger
from . import schema

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT,
    kind       TEXT,
    project    TEXT,
    tool       TEXT,
    action     TEXT,
    gate       TEXT,
    from_state TEXT,
    to_state   TEXT,
    extra      TEXT,
    src_line   TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS latest_state (
    project TEXT,
    stage   TEXT,
    gate    TEXT,
    state   TEXT,
    as_of   TEXT,
    PRIMARY KEY (project, gate)
);
"""


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)


# Fields promoted to their own columns; everything else is preserved verbatim
# in the `extra` JSON blob so the event round-trips losslessly (snapshots keep
# their `ledgers`, transitions keep `stage`/`actor`, etc.).
_CORE_COLUMNS = {"ts", "kind", "project", "tool", "action", "gate", "from", "to"}


def _extra_blob(ev: dict[str, Any]) -> str:
    return json.dumps({k: v for k, v in ev.items() if k not in _CORE_COLUMNS},
                      ensure_ascii=False)


def _row_from_event(ev: dict[str, Any], src_line: str) -> tuple:
    return (
        ev.get("ts"),
        ev.get("kind"),
        ev.get("project"),
        ev.get("tool"),
        ev.get("action"),
        ev.get("gate"),
        ev.get("from"),
        ev.get("to"),
        _extra_blob(ev),
        src_line,
    )


def _rebuild_latest(conn: sqlite3.Connection, events: list[dict[str, Any]]) -> None:
    """Fold events into latest_state rows, tracking the timestamp that set each."""
    # (project, gate) -> (state, as_of, stage)
    state: dict[tuple[str, str], tuple[str, str, str]] = {}
    for ev in sorted((e for e in events if e.get("ts")), key=lambda e: e["ts"]):
        ts, kind = ev["ts"], ev.get("kind")
        if kind == schema.KIND_SNAPSHOT:
            for proj, gates in (ev.get("ledgers") or {}).items():
                for gate, st in gates.items():
                    state[(proj, gate)] = (st, ts, _ledger.stage_for(gate))
        elif kind == schema.KIND_GATE_TRANSITION:
            proj, gate, to = ev.get("project"), ev.get("gate"), ev.get("to")
            # A malformed transition with no target state must not null out a
            # real materialized state — skip it rather than corrupt latest_state.
            if proj and gate and to is not None:
                stage = ev.get("stage") or _ledger.stage_for(gate)
                state[(proj, gate)] = (to, ts, stage)
    conn.execute("DELETE FROM latest_state")
    conn.executemany(
        "INSERT INTO latest_state(project, stage, gate, state, as_of) VALUES (?,?,?,?,?)",
        [(proj, stage, gate, st, as_of) for (proj, gate), (st, as_of, stage) in state.items()],
    )


def ingest(jsonl_paths: Iterable[Path | str], db_path: Path | str) -> dict[str, int]:
    """Ingest JSONL files into ``db_path``. Returns ``{new, skipped, bad}``."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        try:
            _ensure_schema(conn)
        except sqlite3.DatabaseError as exc:
            # The index is a rebuildable derivative — a corrupt/non-SQLite file
            # is recoverable by deleting it. Fail loud with that instruction
            # rather than crashing opaquely (R12; design: "DB 坏了删掉重建即可").
            raise RuntimeError(
                f"{db_path} is not a valid SQLite index ({exc}). "
                f"Delete it and re-run ingest — JSONL is the source of truth."
            ) from exc
        new = skipped = bad = 0
        all_events: list[dict[str, Any]] = []
        for path in jsonl_paths:
            path = Path(path)
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            for lineno, raw in enumerate(text.splitlines(), start=1):
                stripped = raw.strip()
                if not stripped:
                    continue
                try:
                    obj = json.loads(stripped)
                except json.JSONDecodeError:
                    bad += 1
                    continue
                if not isinstance(obj, dict):
                    bad += 1
                    continue
                ev = schema.normalize(obj)
                all_events.append(ev)
                src_line = f"{path}:{lineno}"
                cur = conn.execute(
                    "INSERT OR IGNORE INTO events"
                    "(ts,kind,project,tool,action,gate,from_state,to_state,extra,src_line)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    _row_from_event(ev, src_line),
                )
                if cur.rowcount == 1:
                    new += 1
                else:
                    skipped += 1
        # Rebuild the materialized view from ALL events currently in the db, so
        # it stays consistent even across multiple ingest calls / files.
        db_events = _read_all_events(conn)
        _rebuild_latest(conn, db_events)
        conn.commit()
        return {"new": new, "skipped": skipped, "bad": bad}
    finally:
        conn.close()


def _read_all_events(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Reconstruct fully normalized events from db rows (core columns + blob)."""
    rows = conn.execute(
        "SELECT ts,kind,project,tool,action,gate,from_state,to_state,extra"
        " FROM events ORDER BY ts, id"
    ).fetchall()
    events: list[dict[str, Any]] = []
    for ts, kind, project, tool, action, gate, from_state, to_state, extra in rows:
        try:
            blob = json.loads(extra) if extra else {}
        except (json.JSONDecodeError, TypeError):
            blob = {}
        ev: dict[str, Any] = {"ts": ts, "kind": kind, "project": project,
                              "tool": tool, "action": action, "gate": gate,
                              "from": from_state, "to": to_state}
        ev.update(blob)  # restores ledgers / stage / actor / mode / gate2 / extra
        events.append(ev)
    return events


def count_events(db_path: Path | str) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="glasstrace.ingest",
                                 description="Ingest JSONL events into the SQLite index")
    ap.add_argument("--db", required=True, help="path to trace.db")
    ap.add_argument("jsonl", nargs="+", help="one or more JSONL event files")
    args = ap.parse_args(argv)
    try:
        result = ingest(args.jsonl, args.db)
    except RuntimeError as exc:
        print(f"✗ ingest failed: {exc}")
        return 1
    print(f"ingest: {result['new']} new, {result['skipped']} skipped, {result['bad']} bad line(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
