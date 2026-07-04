"""Lifecycle ledger parsing, diffing, and gate-transition capture.

Two-layer capture guarantees zero silent loss (design §3 "双保险", R12):

  1. ledger-diff hook (real time): when Claude Code writes a `_lifecycle.md`,
     diff the new states against `logs/ledger-cache.json` and append a
     `gate_transition` per changed gate. First sighting of a project emits a
     `snapshot` baseline instead.
  2. reconcile (wall-generation time): re-parse every ledger and compare to the
     state REDUCED FROM THE EVENT STREAM. Any drift the hook missed — a manual
     edit, or a dropped event — is emitted as an `actor:"reconcile"` catch-up.

Gate labels (`gateN`) map 1:1 to the seven lifecycle stages, so the stage glyph
is derived from the gate number.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import reduce, schema

# Canonical state <- glyph OR Chinese text (a ledger row may use either).
# Order matters only for the pathological case of a line carrying two tokens.
STATE_TOKENS: list[tuple[str, tuple[str, ...]]] = [
    ("passed", ("✅", "已过")),
    ("progress", ("🟡", "进行中")),
    ("blocked", ("⛔", "未过")),
    ("todo", ("⏳", "占位")),
    ("hold", ("⏸", "挂起")),
]
STAGE_ORDER = "①②③④⑤⑥⑦"
GATE_RE = re.compile(r"gate([1-7])")


def detect_state(text: str) -> str | None:
    for state, tokens in STATE_TOKENS:
        if any(tok in text for tok in tokens):
            return state
    return None


def stage_for(gate: str) -> str:
    m = GATE_RE.search(gate)
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(STAGE_ORDER):
            return STAGE_ORDER[idx]
    return ""


def parse_ledger(text: str) -> dict[str, str]:
    """Return ``{gate: canonical_state}`` for every recognizable gate row.

    A line counts as a gate row only if it names a ``gateN`` AND carries a
    detectable state — prose mentions of a gate (no state) are skipped so they
    do not create phantom entries.
    """
    states: dict[str, str] = {}
    for line in text.splitlines():
        gm = GATE_RE.search(line)
        if not gm:
            continue
        state = detect_state(line)
        if state is None:
            continue
        states[f"gate{gm.group(1)}"] = state
    return states


def diff_states(old: dict[str, str], new: dict[str, str]) -> list[tuple[str, str | None, str]]:
    """Return ``[(gate, from_state, to_state)]`` for gates whose state changed."""
    changes: list[tuple[str, str | None, str]] = []
    for gate in sorted(new, key=lambda g: (len(g), g)):
        before = old.get(gate)
        after = new[gate]
        if before != after:
            changes.append((gate, before, after))
    return changes


def project_of(ledger_path: Path) -> str:
    """Project name = the ledger's parent directory name."""
    return ledger_path.parent.name


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_cache(cache_path: Path) -> dict[str, dict[str, str]]:
    if not cache_path.is_file():
        return {}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _append_events(events_path: Path, events: list[dict[str, Any]]) -> None:
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("a", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")


def hook_diff(ledger_path: Path, events_path: Path, cache_path: Path,
              actor: str = schema.ACTOR_CLAUDE_CODE, ts: str | None = None) -> list[dict[str, Any]]:
    """Real-time capture for a single ledger write. Appends events, updates cache."""
    ts = ts or _now()
    project = project_of(ledger_path)
    new_states = parse_ledger(ledger_path.read_text(encoding="utf-8"))
    cache = _load_cache(cache_path)
    old_states = cache.get(project)

    if old_states is None:
        # First sighting of this project: lay a baseline, do not fabricate deltas.
        events = [schema.make_snapshot(ts=ts, ledgers={project: new_states}, actor=actor)]
    else:
        events = [
            schema.make_gate_transition(
                ts=ts, project=project, stage=stage_for(gate), gate=gate,
                from_state=before, to_state=after, actor=actor)
            for gate, before, after in diff_states(old_states, new_states)
        ]

    if events:
        _append_events(events_path, events)
    cache[project] = new_states
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    return events


def reconcile(ledgers: dict[str, dict[str, str]], events_text: str,
              cache: dict[str, dict[str, str]] | None = None,
              ts: str | None = None) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    """Catch drift between ground-truth ledgers and the event-reduced state.

    Returns ``(new_events, updated_cache)``. Any gate whose on-disk state differs
    from what the event stream believes is emitted as an ``actor:"reconcile"``
    transition — this is the safety net that makes loss impossible.
    """
    ts = ts or _now()
    events, _bad = schema.parse_events(events_text)
    derived = reduce.reduce_at(events)
    cache = dict(cache or {})
    new_events: list[dict[str, Any]] = []
    for project, current in ledgers.items():
        known = derived.get(project, {})
        for gate, state in current.items():
            if known.get(gate) != state:
                new_events.append(schema.make_gate_transition(
                    ts=ts, project=project, stage=stage_for(gate), gate=gate,
                    from_state=known.get(gate), to_state=state,
                    actor=schema.ACTOR_RECONCILE))
        cache[project] = dict(current)
    return new_events, cache


# ── CLI (used by hooks/ledger-diff.sh) ──────────────────────────────────────
def _cmd_hook(args: argparse.Namespace) -> int:
    events = hook_diff(Path(args.ledger), Path(args.events), Path(args.cache),
                       actor=args.actor, ts=args.ts)
    print(f"ledger-diff: {len(events)} event(s) recorded for {project_of(Path(args.ledger))}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="glasstrace.ledger",
                                 description="Lifecycle ledger transition capture")
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("hook", help="record transitions for one ledger write")
    h.add_argument("--ledger", required=True)
    h.add_argument("--events", required=True)
    h.add_argument("--cache", required=True)
    h.add_argument("--actor", default=schema.ACTOR_CLAUDE_CODE)
    h.add_argument("--ts", default=None)
    h.set_defaults(func=_cmd_hook)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
