"""Event schema v2 and the tolerant reader.

Every governance activity is recorded as one JSONL line. A v2 event shares a
common envelope::

    {v, ts, kind, project, actor, extra{}}

plus per-kind fields. Three kinds exist (see docs/specs/glassgate/02_design.md):

    tool_check       — one gate ruling on a tool call (gate-check.sh)
    gate_transition  — one gate state change (ledger-diff hook / reconcile)
    snapshot         — a full state baseline (captured at wall generation)

Legacy `v:1` lines (from the demo-kit gate hook) have no `kind` field; the
reader infers `tool_check` so historical logs stay renderable. The schema is
designed to evolve: unknown future fields ride along untouched.
"""
from __future__ import annotations

import json
from typing import Any

SCHEMA_VERSION = 2

# Event kinds.
KIND_TOOL_CHECK = "tool_check"
KIND_GATE_TRANSITION = "gate_transition"
KIND_SNAPSHOT = "snapshot"

# Actor labels — who produced the event.
ACTOR_GATE_CHECK = "gate-check"
ACTOR_CLAUDE_CODE = "claude_code"
ACTOR_RECONCILE = "reconcile"


def make_tool_check(
    *,
    ts: str,
    project: str,
    tool: str,
    mode: str,
    action: str,
    gate2: str,
    actor: str = ACTOR_GATE_CHECK,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a v2 `tool_check` event (a single gate ruling on a tool call)."""
    return {
        "v": SCHEMA_VERSION,
        "ts": ts,
        "kind": KIND_TOOL_CHECK,
        "project": project,
        "actor": actor,
        "tool": tool,
        "mode": mode,
        "action": action,
        "gate2": gate2,
        "extra": extra or {},
    }


def make_gate_transition(
    *,
    ts: str,
    project: str,
    stage: str,
    gate: str,
    from_state: str | None,
    to_state: str | None,
    actor: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a v2 `gate_transition` event (one gate changing state)."""
    return {
        "v": SCHEMA_VERSION,
        "ts": ts,
        "kind": KIND_GATE_TRANSITION,
        "project": project,
        "actor": actor,
        "stage": stage,
        "gate": gate,
        "from": from_state,
        "to": to_state,
        "extra": extra or {},
    }


def make_snapshot(
    *,
    ts: str,
    ledgers: dict[str, Any],
    actor: str = ACTOR_RECONCILE,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a v2 `snapshot` event: a full state baseline for reduction/replay.

    `ledgers` maps project -> {gate: state} (or richer per-stage detail).
    """
    return {
        "v": SCHEMA_VERSION,
        "ts": ts,
        "kind": KIND_SNAPSHOT,
        "project": None,
        "actor": actor,
        "ledgers": ledgers,
        "extra": extra or {},
    }


def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """Return an event with a guaranteed `v` and `kind`.

    A missing `kind` means a legacy v:1 line, which was always a tool_check.
    Other fields pass through untouched so the schema can evolve freely.
    """
    ev = dict(raw)
    ev.setdefault("v", 1)
    if not ev.get("kind"):
        ev["kind"] = KIND_TOOL_CHECK
    ev.setdefault("actor", ACTOR_GATE_CHECK if ev["kind"] == KIND_TOOL_CHECK else "")
    return ev


def parse_events(text: str) -> tuple[list[dict[str, Any]], list[int]]:
    """Parse JSONL text into (events, bad_line_numbers).

    Tolerant by contract: a malformed line is recorded by its 1-based line
    number and skipped, never raised — so one corrupt row cannot blank the
    wall (R12: fail loud, not silent). Blank lines are ignored, not flagged.
    """
    events: list[dict[str, Any]] = []
    bad: list[int] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            bad.append(lineno)
            continue
        if not isinstance(obj, dict):
            bad.append(lineno)
            continue
        events.append(normalize(obj))
    return events, bad
