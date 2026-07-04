#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# gate-check.sh — Glassgate lifecycle gate hook (trace layer v0.1)
#   Mount point : PreToolUse, matcher: Write|Edit|MultiEdit
#   Purpose     : when the edited file belongs to a managed project whose gate2
#                 (requirements & design) has not passed, warn on / block the
#                 write, and append a structured v2 `tool_check` event.
#
#   Contract (design §3, non-functional requirements):
#     - Pure bash + jq. Zero new dependencies.
#     - Append-only: writes ONE JSONL line per invocation to logs/events.jsonl.
#       It NEVER touches the SQLite index — a gate ruling can never fail because
#       of a locked or corrupt database.
#     - soft / strict dual mode. strict = block (exit 2 + stderr, so the harness
#       relays the warning to the agent); soft = warn only (exit 0 + stdout).
# ─────────────────────────────────────────────────────────────────────────────
set -u

# ── Configuration (override via env for tests / per-instance policy) ──
MODE="${GLASSGATE_MODE:-strict}"       # strict = block | soft = warn only
EVENTS_LOG="${GLASSGATE_EVENTS:-}"     # empty = auto-locate <instance>/logs/events.jsonl

INPUT="$(cat)"

# jq is the required primary parser. If it is missing (misconfigured host), fall
# back to a minimal extractor rather than silently allowing every write.
if command -v jq >/dev/null 2>&1; then
  TOOL="$(printf '%s' "$INPUT" | jq -r '.tool_name // ""' 2>/dev/null)"
  TARGET="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // ""' 2>/dev/null)"
else
  echo "gate-check: jq not found — using degraded field extractor" >&2
  TOOL="$(printf '%s' "$INPUT" | sed -n 's/.*"tool_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
  TARGET="$(printf '%s' "$INPUT" | sed -n 's/.*"file_path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
  [ -z "$TARGET" ] && TARGET="$(printf '%s' "$INPUT" | sed -n 's/.*"path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
fi

# Resolve the events log: hook lives in <instance>/hooks/, log in <instance>/logs/.
if [ -z "$EVENTS_LOG" ]; then
  HOOK_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"
  EVENTS_LOG="$HOOK_DIR/../logs/events.jsonl"
fi

# Append one v2 tool_check line. Best-effort: never break the tool call on a
# logging failure.  Args: $1=project $2=gate2_state $3=action
audit() {
  local proj="$1" g2="$2" action="$3"
  local ts; ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)"
  local dir; dir="$(dirname "$EVENTS_LOG")"
  # Best-effort by design: a logging failure must never break or slow the tool
  # call (design §3). But it must be LOUD, not silent (R12) — warn on stderr so
  # the miss is visible, and let the wall-generation reconcile pass (story 2)
  # recover any event the stream dropped.
  mkdir -p "$dir" 2>/dev/null || { echo "gate-check: cannot create log dir $dir — event NOT recorded" >&2; return 0; }
  if command -v jq >/dev/null 2>&1; then
    jq -cn --arg ts "$ts" --arg p "$proj" --arg g2 "$g2" --arg t "${TOOL:-}" \
          --arg m "$MODE" --arg a "$action" \
      '{v:2, ts:$ts, kind:"tool_check", project:$p, actor:"gate-check",
        tool:$t, mode:$m, action:$a, gate2:$g2, extra:{}}' \
      >> "$EVENTS_LOG" 2>/dev/null || echo "gate-check: failed to append event to $EVENTS_LOG" >&2
  else
    printf '{"v":2,"ts":"%s","kind":"tool_check","project":"%s","actor":"gate-check","tool":"%s","mode":"%s","action":"%s","gate2":"%s","extra":{}}\n' \
      "$ts" "$proj" "${TOOL:-}" "$MODE" "$action" "$g2" >> "$EVENTS_LOG" 2>/dev/null || echo "gate-check: failed to append event to $EVENTS_LOG" >&2
  fi
}

# No target path -> record a skip and allow.
if [ -z "$TARGET" ]; then audit "" "na" "skip"; exit 0; fi

# Walk upward from the target to the nearest project ledger.
DIR="$(dirname "$TARGET")"
LIFECYCLE=""
while [ "$DIR" != "/" ] && [ -n "$DIR" ]; do
  if [ -f "$DIR/_lifecycle.md" ]; then LIFECYCLE="$DIR/_lifecycle.md"; break; fi
  if [ -d "$DIR/docs/specs" ]; then
    for cand in "$DIR/docs/specs"/*/"_lifecycle.md"; do
      [ -f "$cand" ] || continue
      proj="$(basename "$(dirname "$cand")")"
      case "$TARGET" in *"$proj"*) LIFECYCLE="$cand"; break ;; esac
    done
    [ -n "$LIFECYCLE" ] && break
  fi
  DIR="$(dirname "$DIR")"
done

# Not a managed project (no ledger) -> record allow and pass.
if [ -z "$LIFECYCLE" ]; then audit "" "na" "allow"; exit 0; fi

PROJECT="$(basename "$(dirname "$LIFECYCLE")")"

# Has gate2 passed? (line mentions gate2 and carries ✅ or 已过)
GATE2_LINE="$(grep -E 'gate2' "$LIFECYCLE" 2>/dev/null | head -1)"
GATE2_PASSED="$(printf '%s' "$GATE2_LINE" | grep -E 'gate2.*✅|gate2.*已过')"

if [ -n "$GATE2_PASSED" ]; then audit "$PROJECT" "passed" "allow"; exit 0; fi

# ── gate2 not passed -> warn ──
WARN_1="⚠️  [lifecycle gate] project \"${PROJECT}\": gate2 (requirements & design) has not passed."
WARN_2="    ledger: $LIFECYCLE"
WARN_3="    Per the seven-stage lifecycle, code should not be written before gate2 passes."

if [ "$MODE" = "strict" ]; then
  { echo "$WARN_1"; echo "$WARN_2"; echo "$WARN_3"; echo "    [strict] this write was blocked."; } >&2
  audit "$PROJECT" "blocked" "blocked"
  exit 2
else
  echo "$WARN_1"; echo "$WARN_2"; echo "$WARN_3"
  echo "    (soft mode: warn only. Set GLASSGATE_MODE=strict to block.)"
  audit "$PROJECT" "blocked" "warned"
  exit 0
fi
