"""Reduce an event stream to project/gate state.

A single fold serves both "current state" and "state at time T" (replay,
story 4): pass a `cutoff` timestamp to include only events up to that moment.

Only `snapshot` (baseline) and `gate_transition` (delta) events affect gate
state; `tool_check` events are audit rows and are ignored here. Events are
applied in timestamp order — ISO-8601 Zulu strings sort chronologically, and
the sort is stable so equal timestamps keep file order.
"""
from __future__ import annotations

from typing import Any

from . import schema


def _sorted(events: list[dict[str, Any]], cutoff: str | None) -> list[dict[str, Any]]:
    selected = [e for e in events if e.get("ts") and (cutoff is None or e["ts"] <= cutoff)]
    return sorted(selected, key=lambda e: e["ts"])


def reduce_at(events: list[dict[str, Any]], cutoff: str | None = None) -> dict[str, dict[str, str]]:
    """Fold events into ``{project: {gate: state}}`` as of ``cutoff`` (or latest).

    ``cutoff`` is an inclusive ISO timestamp; ``None`` means "apply everything".
    """
    state: dict[str, dict[str, str]] = {}
    for ev in _sorted(events, cutoff):
        kind = ev.get("kind")
        if kind == schema.KIND_SNAPSHOT:
            for proj, gates in (ev.get("ledgers") or {}).items():
                state.setdefault(proj, {}).update(gates)
        elif kind == schema.KIND_GATE_TRANSITION:
            proj, gate, to = ev.get("project"), ev.get("gate"), ev.get("to")
            # Ignore a malformed transition with no target state (don't corrupt).
            if proj and gate and to is not None:
                state.setdefault(proj, {})[gate] = to
    return state
