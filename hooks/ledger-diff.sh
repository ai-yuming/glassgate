#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# ledger-diff.sh — Glassgate gate-transition capture hook (trace layer v0.1)
#   Mount point : PostToolUse, matcher: Write|Edit|MultiEdit
#   Purpose     : when Claude Code writes a `_lifecycle.md`, record a
#                 `gate_transition` event per changed gate.
#
#   Design note (R7 resolution, see spec doc): parsing/diffing a markdown ledger
#   in pure bash is fragile, so this NON-BLOCKING hook delegates to
#   `python3 -m glasstrace.ledger` — python3 is already a required dependency.
#   It writes only JSONL + a JSON cache, NEVER SQLite. The blocking gate hook
#   (gate-check.sh) stays pure bash+jq. Failures here are non-fatal: the
#   wall-generation reconcile pass recovers anything this hook misses.
# ─────────────────────────────────────────────────────────────────────────────
set -u

INPUT="$(cat)"
if command -v jq >/dev/null 2>&1; then
  TARGET="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // ""' 2>/dev/null)"
else
  TARGET="$(printf '%s' "$INPUT" | sed -n 's/.*"file_path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
fi

# React only to lifecycle-ledger writes; do nothing (fast) for everything else.
case "$TARGET" in
  */_lifecycle.md) : ;;
  *) exit 0 ;;
esac
[ -f "$TARGET" ] || exit 0

HOOK_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"
ROOT="${GLASSGATE_ROOT:-$HOOK_DIR/..}"
EVENTS="${GLASSGATE_EVENTS:-$ROOT/logs/events.jsonl}"
CACHE="${GLASSGATE_CACHE:-$ROOT/logs/ledger-cache.json}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "ledger-diff: python3 not found — transition not recorded (reconcile will recover)" >&2
  exit 0
fi

PYTHONPATH="$ROOT:${PYTHONPATH:-}" python3 -m glasstrace.ledger hook \
  --ledger "$TARGET" --events "$EVENTS" --cache "$CACHE" --actor claude_code >/dev/null 2>&1 \
  || echo "ledger-diff: failed to record transition for $TARGET (reconcile will recover)" >&2

exit 0
