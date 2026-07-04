# Glassgate

**Governance + observability for your AI factory.**

You let an agent write code across a dozen projects. Which ones jumped the gate?
Which are blocked waiting on *you*? What did the factory actually do at 2am?
Glassgate turns your agent's governance activity into a single glass wall an
approver can read at a glance — and a structured event stream you can replay,
query, and trust.

No daemon. No server. No database you have to babysit. One `bash` command
regenerates a single static HTML file. The event log is plain JSONL you can
`grep`, `git`, and read with your own eyes.

---

## 30-second quickstart

Glassgate is pure `bash` + `python3` standard library. Nothing to install.

```bash
git clone <your-fork> glassgate && cd glassgate

# 1. Point it at your projects: each managed project keeps a lifecycle ledger at
#    projects/<name>/_lifecycle.md  (or docs/specs/<name>/_lifecycle.md)

# 2. Generate the glass wall from your ledgers + event log
./cli/harness wall              # -> glasswall/wall.html

# 3. Fold the JSONL event stream into a queryable SQLite index
./cli/harness trace ingest

# 4. Health-check the trace layer (parse rate, DB/JSONL consistency)
./cli/harness doctor

# 5. Time-travel: replay how the factory reached today
./cli/harness wall --replay     # -> glasswall/replay.html
```

To make the gate *enforce* itself, wire the hooks into your project's
`.claude/settings.json` (see `.claude/settings.json` in this repo for a working,
username-free template): `gate-check.sh` on `PreToolUse` blocks code writes when
a project's requirements gate hasn't passed; `ledger-diff.sh` on `PostToolUse`
records every gate transition.

---

## The wall

Three panels, one screen, meant for the person who approves — not the person who
codes:

| ② Pending | ① Project lanes | ③ Audit stream |
|---|---|---|
| _(screenshot placeholder)_ | _(screenshot placeholder)_ | _(screenshot placeholder)_ |
| What's blocked on you, with a one-click approval command to relay. | Every project's seven-stage progress, gate by gate. | Recent tool-gate rulings, in plain language. |

Replay mode reconstructs the **state at any past moment** — drag the timeline and
watch each lane become what it was, gate by gate. It is clearly banner-marked
`🎬 replay · not live`.

---

## Design philosophy

- **Static snapshot, not a live dashboard.** The wall is a file. Refresh = re-run
  one command. Nothing polls, nothing sockets, nothing runs while you sleep.
- **Zero daemon.** All computation happens at hook-trigger time or wall-generation
  time. There is no background process to crash, leak, or become a new failure
  point.
- **The human relays the gate.** The wall never approves anything for you. A
  blocked item shows a copy-ready command you hand to your agent. You hold the
  gate; the software just makes the decision legible.
- **JSONL is the source of truth.** Events are append-only text. The SQLite index
  is a derived accelerator you can delete and rebuild at any time with identical
  results. The gate hook only ever *appends a line* — it never touches the
  database, so a locked or corrupt index can never break or slow a gate decision.

---

## Technical depth: why the gate runs in strict mode

Building this taught us something non-obvious about agent hooks, verified across
two backends (Claude and GLM, CC 2.1.175):

> **A hook's warning only reaches the agent if the hook fails loudly.**
> In *soft* mode (`exit 0` + `stdout`), the gate hook genuinely fires and its
> ruling is written to the audit log — but the warning text is **not** surfaced
> to the model. Both backends reported `HOOK_NONE`: the agent never saw it.
> Only *strict* mode (`exit 2` + `stderr`) reliably reaches the agent, because the
> harness relays a blocking hook's stderr back as the reason the tool call was
> denied.

So Glassgate ships **strict by default**: a warning you can't see is not a gate.
The audit trail is written identically in both modes (observability is never
affected) — but if you want the agent to actually *hear* the gate, it must be
able to *stop* the agent. You can flip to soft mode per instance, knowing the
tradeoff.

---

## v0.1 scope — honest boundaries

This is the **trace layer** (structured events + state replay). What's here:

- Versioned event schema (v2), backward-compatible with legacy v1 logs.
- Gate-transition capture: real-time via hook + reconciliation at wall-generation
  (so a manual ledger edit is never silently lost).
- Idempotent SQLite index; deleting and rebuilding it is a no-op on your data.
- State replay with a client-side time-travel reducer.
- Trace-layer self-check (`harness doctor`).

What's **not** here yet (by design):

- The gate hook guards the requirements gate only, on `Write|Edit|MultiEdit`.
  Full multi-gate coverage is backlog.
- The wall's approval-relay panel is minimal in v0.1.
- No OpenTelemetry exporter yet — the schema aligns with OTel span semantics, but
  wiring an exporter waits for a real backend (see roadmap).

## Roadmap

- **v0.2 — resilience.** Hardening for messy real-world logs and instances at
  scale; richer doctor; approval-relay panel.
- **v0.3 — Claude Code plugin.** First-class packaging so any Claude Code project
  can adopt the gate + wall in one step; OTel export.

---

## License

Glassgate is **open-core**.

- **Core** (this repository — trace layer, hooks, CLI, glass wall) is licensed
  under **Apache-2.0**. See [LICENSE](LICENSE).
- A future **Pro trace panel** (advanced analytics / hosted views) will be
  closed-source and lives under a `pro/` boundary that is **not part of this
  repository**. The core stands on its own; Pro is additive.

Copyright © 2026 Martin Yu.
