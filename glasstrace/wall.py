"""Glass wall generator — a single static HTML file, zero network, zero service.

Two modes:
  build_regular  — lanes + pending + audit from the current ledgers and the
                   (mixed v1/v2) event log.
  build_replay   — embeds the event stream + a draggable timeline; a small
                   client-side reducer (mirroring glasstrace.reduce.reduce_at)
                   reconstructs each lane's state AS OF the slider moment T.

All user-facing strings come from a locale pack (locales/<name>.json); the code
itself is English. Independent implementation — shares no factory-internal wall
code path (contract D3).
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from . import ledger as _ledger

_PKG_ROOT = Path(__file__).resolve().parent.parent


def load_locale(name_or_path: str) -> dict[str, Any]:
    path = Path(name_or_path)
    if not path.suffix:
        path = _PKG_ROOT / "locales" / f"{name_or_path}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _esc(s: Any) -> str:
    return html.escape(str(s), quote=True)


def _state_meta(locale: dict, state: str | None) -> tuple[str, str, str]:
    meta = locale.get("states", {}).get(state or "", {})
    # English fallbacks when a state has no locale entry — code stays English;
    # all localized labels come from the locale pack.
    return meta.get("label", "unknown"), meta.get("css", "unknown"), meta.get("glyph", "?")


# ── shared page shell ───────────────────────────────────────────────────────
_STYLE = """
:root{--bg:#0b0e13;--panel:#141a22;--panel2:#1b232d;--line:#26303c;--ink:#e6edf3;
--dim:#8b98a5;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
--passed:#3fb950;--progress:#58a6ff;--blocked:#f85149;--todo:#8b949e;--hold:#a371f7;--amber:#e3a008}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(1200px 600px at 80% -10%,#16202b 0%,transparent 60%),var(--bg);
color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif;line-height:1.5}
.replay-banner{background:linear-gradient(90deg,#3a2708,#2a1d06);border-bottom:1px solid #5a4318;
color:var(--amber);font-family:var(--mono);font-size:13px;padding:10px 32px;display:flex;
align-items:center;gap:10px;flex-wrap:wrap}
.replay-banner .tag{background:var(--amber);color:#1a1205;font-weight:800;border-radius:5px;padding:1px 8px}
header.top{padding:24px 32px 16px;border-bottom:1px solid var(--line)}
header.top h1{margin:0;font-size:22px}header.top h1 .glass{color:var(--amber)}
.meta{margin-top:8px;color:var(--dim);font-size:13px;font-family:var(--mono)}.meta b{color:var(--ink)}
main{padding:24px 32px 60px;max-width:1200px;margin:0 auto}
section{margin:0 0 30px}section>h2{font-size:14px;letter-spacing:2px;color:var(--dim);
border-left:3px solid var(--amber);padding-left:10px;margin:0 0 14px}
.empty{color:var(--dim);background:var(--panel);border:1px dashed var(--line);border-radius:10px;padding:16px}
#lanes{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px}
.lane{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.lane h3{margin:0 0 10px;font-size:15px}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{display:flex;flex-direction:column;align-items:center;gap:1px;min-width:56px;
background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:6px 8px}
.chip .st{font-size:13px}.chip .gt{font-size:10px;color:var(--dim);font-family:var(--mono)}
.chip .nm{font-size:10px;color:var(--dim)}
.chip.passed{border-color:#1c4a2b}.chip.passed .st{color:var(--passed)}
.chip.progress{border-color:#1d3a5f}.chip.progress .st{color:var(--progress)}
.chip.blocked{border-color:#5a2626}.chip.blocked .st{color:var(--blocked)}
.chip.hold{border-color:#3a2b52}.chip.hold .st{color:var(--hold)}
.chip.todo .st{color:var(--todo)}.chip.unknown .st{color:var(--dim)}
.pend{background:linear-gradient(180deg,#241318,#1a1013);border:1px solid #47262a;
border-left:3px solid var(--blocked);border-radius:12px;padding:14px 16px;margin-bottom:10px}
.pend header{display:flex;justify-content:space-between;align-items:center;gap:12px}
.pend h3{margin:0;font-size:15px}
.pend .what{color:var(--dim);font-size:13px;margin:8px 0 10px}
.pend .cmd{display:flex;gap:10px;flex-wrap:wrap;align-items:stretch}
.pend code{flex:1 1 300px;background:#0d1117;border:1px solid var(--line);border-radius:8px;
padding:10px 12px;font-family:var(--mono);font-size:12.5px;color:#c9d5e0;word-break:break-all}
.pend button.copy{background:var(--amber);color:#1a1205;border:0;border-radius:8px;
padding:0 16px;font-weight:700;cursor:pointer;white-space:nowrap}
.pend .hint{color:var(--dim);font-size:12px;margin:10px 0 0}
.badge{font-size:11px;padding:2px 8px;border-radius:999px;font-family:var(--mono)}
.badge.blocked{background:#3a1b1b;color:var(--blocked);border:1px solid #5a2626}
table.audit{width:100%;border-collapse:collapse;font-size:12.5px}
table.audit th{text-align:left;color:var(--dim);padding:8px 10px;border-bottom:1px solid var(--line);
font-size:11px;letter-spacing:1px}
table.audit td{padding:8px 10px;border-bottom:1px solid #1a222c}
table.audit td.ts{font-family:var(--mono);color:var(--dim);white-space:nowrap}
table.audit tr.blocked td.act{color:var(--blocked)}table.audit tr.warn td.act{color:var(--amber)}
table.audit tr.ok td.act{color:var(--passed)}table.audit tr.todo td.act{color:var(--todo)}
.timeline{display:flex;align-items:center;gap:12px;background:var(--panel);border:1px solid var(--line);
border-radius:10px;padding:12px 16px;margin-bottom:18px;flex-wrap:wrap}
.timeline input[type=range]{flex:1 1 320px}
.timeline button{background:var(--amber);color:#1a1205;border:0;border-radius:6px;padding:6px 14px;
font-weight:700;cursor:pointer}
.timeline .clock{font-family:var(--mono);color:var(--ink);font-size:13px;min-width:180px}
footer.bot{border-top:1px solid var(--line);padding:16px 32px;color:var(--dim);
font-size:12px;font-family:var(--mono);text-align:center}
"""


def _page(lang: str, title: str, banner: str, body: str, extra_script: str = "") -> str:
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="{_esc(lang)}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_esc(title)}</title><style>{_STYLE}</style></head><body>"
        f"{banner}{body}{extra_script}</body></html>\n"
    )


# ── lanes / audit fragments (shared) ────────────────────────────────────────
def _chip(locale: dict, project: str, gate: str, state: str | None, cell_id: str = "") -> str:
    label, css, glyph = _state_meta(locale, state)
    stage = _ledger.stage_for(gate)
    stage_name = locale.get("stages", {}).get(stage, "")
    idattr = f' id="{_esc(cell_id)}"' if cell_id else ""
    return (f'<div class="chip {css}"{idattr} data-project="{_esc(project)}" data-gate="{_esc(gate)}">'
            f'<span class="st">{_esc(stage)} {_esc(glyph)}</span>'
            f'<span class="gt">{_esc(gate)}</span>'
            f'<span class="nm">{_esc(stage_name or label)}</span></div>')


def _gates_sorted(gates) -> list[str]:
    return sorted(gates, key=lambda g: (len(g), g))


def _lane_card(locale: dict, project: str, gates: dict[str, str]) -> str:
    chips = "".join(_chip(locale, project, g, gates[g]) for g in _gates_sorted(gates))
    return (f'<article class="lane"><h3>{_esc(project)}</h3>'
            f'<div class="chips">{chips}</div></article>')


def _audit_table(locale: dict, events: list[dict]) -> str:
    cols = locale.get("audit_cols", {})
    actions = locale.get("actions", {})
    modes = locale.get("modes", {})
    checks = [e for e in events if e.get("kind") == "tool_check"]
    if not checks:
        return f'<p class="empty">{_esc(locale.get("empty_audit", ""))}</p>'
    css_by_action = {"blocked": "blocked", "warned": "warn", "allow": "ok", "skip": "todo"}
    rows = []
    for e in reversed(checks):  # newest first
        css = css_by_action.get(e.get("action"), "")
        rows.append(
            f'<tr class="{css}"><td class="ts">{_esc(e.get("ts","?"))}</td>'
            f'<td>{_esc(e.get("project") or "—")}</td><td>{_esc(e.get("tool") or "—")}</td>'
            f'<td>{_esc(modes.get(e.get("mode",""), e.get("mode","")))}</td>'
            f'<td class="act">{_esc(actions.get(e.get("action",""), e.get("action","")))}</td>'
            f'<td>v{_esc(e.get("v",1))}</td></tr>')
    head = (f'<tr><th>{_esc(cols.get("ts",""))}</th><th>{_esc(cols.get("project",""))}</th>'
            f'<th>{_esc(cols.get("tool",""))}</th><th>{_esc(cols.get("mode",""))}</th>'
            f'<th>{_esc(cols.get("action",""))}</th><th>v</th></tr>')
    return f'<table class="audit"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table>'


def _pending_projects(ledgers: dict[str, dict[str, str]]) -> list[tuple[str, str]]:
    """Projects whose first non-passed (frontier) gate is blocked — i.e. stuck
    waiting on the approver. Returns [(project, gate)]."""
    out: list[tuple[str, str]] = []
    for proj, gates in sorted(ledgers.items()):
        frontier = next((g for g in _gates_sorted(gates) if gates[g] != "passed"), None)
        if frontier and gates[frontier] == "blocked":
            out.append((proj, frontier))
    return out


def _pending_card(locale: dict, project: str, gate: str) -> str:
    cmd = (locale.get("pending_approve_cmd", "")
           .replace("{project}", project).replace("{gate}", gate))
    stage = _ledger.stage_for(gate)
    stage_name = locale.get("stages", {}).get(stage, "")
    return (f'<article class="pend"><header><h3>{_esc(project)}</h3>'
            f'<span class="badge blocked">{_esc(gate)} {_esc(locale.get("pending_badge",""))}</span>'
            f'</header><p class="what">{_esc(stage)} {_esc(stage_name)}</p>'
            f'<div class="cmd"><code>{_esc(cmd)}</code>'
            f'<button class="copy" data-cmd="{_esc(cmd)}">{_esc(locale.get("pending_copy",""))}</button></div>'
            f'<p class="hint">{_esc(locale.get("pending_hint",""))}</p></article>')


# Copy-to-clipboard relay for pending approval commands (the UI never approves;
# it hands you a command to relay to your agent).
_COPY_JS = (
    '<script>document.addEventListener("click",function(e){'
    'var b=e.target.closest("button.copy");if(!b)return;'
    'var c=b.getAttribute("data-cmd")||"";'
    'if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(c);}'
    'var t=b.textContent;b.textContent="✓";setTimeout(function(){b.textContent=t;},1500);'
    '});</script>'
)


def build_regular(ledgers: dict[str, dict[str, str]], events: list[dict], locale: dict,
                  instance: str, generated_at: str) -> str:
    lanes = "".join(_lane_card(locale, p, g) for p, g in sorted(ledgers.items())) \
        or f'<p class="empty">{_esc(locale.get("empty_lanes",""))}</p>'
    audit = _audit_table(locale, events)
    checks = [e for e in events if e.get("kind") == "tool_check"]
    pend = _pending_projects(ledgers)
    pending_html = "".join(_pending_card(locale, p, g) for p, g in pend) \
        or f'<p class="empty">{_esc(locale.get("empty_pending",""))}</p>'
    body = (
        '<header class="top">'
        f'<h1><span class="glass">{_esc(locale.get("brand",""))}</span> · {_esc(instance)}</h1>'
        f'<div class="meta">{_esc(locale.get("meta_projects",""))} <b>{len(ledgers)}</b> · '
        f'{_esc(locale.get("meta_pending",""))} <b>{len(pend)}</b> · '
        f'{_esc(locale.get("meta_audit",""))} <b>{len(checks)}</b> {_esc(locale.get("meta_audit_unit",""))} · '
        f'{_esc(locale.get("meta_generated",""))} <b>{_esc(generated_at)}</b></div></header>'
        f'<main><section id="pending"><h2>{_esc(locale.get("section_pending",""))}</h2>'
        f'{pending_html}</section>'
        f'<section><h2>{_esc(locale.get("section_lanes",""))}</h2>'
        f'<div id="lanes">{lanes}</div></section>'
        f'<section><h2>{_esc(locale.get("section_audit",""))}</h2>{audit}</section></main>'
        f'<footer class="bot">{_esc(locale.get("footer",""))} | {_esc(generated_at)}</footer>'
    )
    return _page(locale.get("html_lang", "en"),
                 locale.get("title", "{instance}").replace("{instance}", instance),
                 "", body, _COPY_JS)


# ── replay ──────────────────────────────────────────────────────────────────
def _replay_cells(ledgers: dict[str, dict[str, str]], events: list[dict]) -> list[dict]:
    """Union of gates seen in events + current ledgers -> chips to time-travel."""
    seen: dict[tuple[str, str], dict] = {}
    for ev in events:
        if ev.get("kind") == "snapshot":
            for proj, gates in (ev.get("ledgers") or {}).items():
                for gate in gates:
                    seen.setdefault((proj, gate), {"project": proj, "gate": gate})
        elif ev.get("kind") == "gate_transition" and ev.get("project") and ev.get("gate"):
            seen.setdefault((ev["project"], ev["gate"]), {"project": ev["project"], "gate": ev["gate"]})
    for proj, gates in ledgers.items():
        for gate in gates:
            seen.setdefault((proj, gate), {"project": proj, "gate": gate})
    cells = []
    for (proj, gate), c in seen.items():
        c["stage"] = _ledger.stage_for(gate)
        cells.append(c)
    return sorted(cells, key=lambda c: (c["project"], len(c["gate"]), c["gate"]))


# Client-side reducer — mirrors glasstrace.reduce.reduce_at. Deliberately tiny.
_REPLAY_JS = r"""
(function(){
  var D = JSON.parse(document.getElementById("gg-data").textContent);
  var evs = D.events.slice().filter(function(e){return e.ts;})
             .sort(function(a,b){return a.ts<b.ts?-1:a.ts>b.ts?1:0;});
  var stamps = []; evs.forEach(function(e){ if(stamps[stamps.length-1]!==e.ts) stamps.push(e.ts); });
  // dedupe timestamps preserving order
  var uniq=[]; stamps.forEach(function(t){ if(uniq.indexOf(t)<0) uniq.push(t); });
  var slider = document.getElementById("gg-slider");
  var clock = document.getElementById("gg-clock");
  var play = document.getElementById("gg-play");
  slider.min = 0; slider.max = Math.max(0, uniq.length-1); slider.step = 1;
  slider.value = slider.max;

  function stateAt(cutoff){
    var st = {}; // project -> gate -> state
    for(var i=0;i<evs.length;i++){
      var e = evs[i]; if(e.ts > cutoff) break;
      if(e.kind==="snapshot"){
        var L=e.ledgers||{};
        for(var p in L){ st[p]=st[p]||{}; for(var g in L[p]) st[p][g]=L[p][g]; }
      } else if(e.kind==="gate_transition" && e.project && e.gate && e.to!=null){
        st[e.project]=st[e.project]||{}; st[e.project][e.gate]=e.to;
      }
    }
    return st;
  }
  function render(){
    var idx = parseInt(slider.value,10)||0;
    var cutoff = uniq.length ? uniq[idx] : "";
    clock.textContent = cutoff || "—";
    var st = stateAt(cutoff);
    var chips = document.querySelectorAll(".chip[data-gate]");
    for(var i=0;i<chips.length;i++){
      var c=chips[i], p=c.getAttribute("data-project"), g=c.getAttribute("data-gate");
      var s = (st[p]||{})[g] || null;
      var meta = D.states[s] || {label:"—",css:"unknown",glyph:"·"};
      c.className = "chip "+meta.css;
      c.querySelector(".st").textContent = c.querySelector(".st").getAttribute("data-stage")+" "+meta.glyph;
      c.querySelector(".nm").textContent = meta.label;
    }
  }
  slider.addEventListener("input", render);
  var timer=null;
  play.addEventListener("click", function(){
    if(timer){ clearInterval(timer); timer=null; play.textContent=D.i18n.play; return; }
    play.textContent=D.i18n.pause;
    timer=setInterval(function(){
      var v=parseInt(slider.value,10);
      if(v>=parseInt(slider.max,10)){ clearInterval(timer); timer=null; play.textContent=D.i18n.play; return; }
      slider.value=v+1; render();
    }, 900);
  });
  render();
})();
"""


def build_replay(ledgers: dict[str, dict[str, str]], events: list[dict], locale: dict,
                 instance: str, generated_at: str) -> str:
    state_events = [e for e in events if e.get("kind") in ("snapshot", "gate_transition")]
    cells = _replay_cells(ledgers, events)
    rp = locale.get("replay", {})
    payload = {
        "events": state_events,
        "cells": cells,
        "states": locale.get("states", {}),
        "i18n": {"play": rp.get("play", "play"), "pause": rp.get("pause", "pause")},
    }
    data_island = ('<script id="gg-data" type="application/json">'
                   + json.dumps(payload, ensure_ascii=False) + "</script>")

    # Lane cards with identifiable, stage-annotated chips the JS can update.
    lane_html = []
    for proj in sorted({c["project"] for c in cells}):
        proj_cells = [c for c in cells if c["project"] == proj]
        chips = []
        for c in sorted(proj_cells, key=lambda x: (len(x["gate"]), x["gate"])):
            stage = c["stage"]
            stage_name = locale.get("stages", {}).get(stage, "")
            chips.append(
                f'<div class="chip unknown" data-project="{_esc(proj)}" data-gate="{_esc(c["gate"])}">'
                f'<span class="st" data-stage="{_esc(stage)}">{_esc(stage)} ·</span>'
                f'<span class="gt">{_esc(c["gate"])}</span>'
                f'<span class="nm">{_esc(stage_name)}</span></div>')
        lane_html.append(f'<article class="lane"><h3>{_esc(proj)}</h3>'
                         f'<div class="chips">{"".join(chips)}</div></article>')
    lanes = "".join(lane_html) or f'<p class="empty">{_esc(locale.get("empty_lanes",""))}</p>'

    banner = (f'<div class="replay-banner"><span class="tag">{_esc(rp.get("banner_tag",""))}</span>'
              f'{_esc(rp.get("banner_text",""))}</div>')
    timeline = (
        '<div class="timeline">'
        f'<button id="gg-play">{_esc(rp.get("play",""))}</button>'
        '<input id="gg-slider" type="range" value="0">'
        f'<span class="clock">{_esc(rp.get("at_time",""))}: <b id="gg-clock">—</b></span></div>'
    )
    body = (
        '<header class="top">'
        f'<h1><span class="glass">{_esc(locale.get("brand",""))}</span> · {_esc(instance)}</h1>'
        f'<div class="meta">{_esc(rp.get("banner_text",""))} · '
        f'{_esc(locale.get("meta_generated",""))} <b>{_esc(generated_at)}</b></div></header>'
        f'<main>{timeline}'
        f'<section><h2>{_esc(locale.get("section_lanes",""))}</h2>'
        f'<div id="lanes">{lanes}</div></section></main>'
        f'<footer class="bot">{_esc(locale.get("footer",""))} | {_esc(generated_at)}</footer>'
        f"{data_island}"
    )
    return _page(locale.get("html_lang", "en"),
                 locale.get("title", "{instance}").replace("{instance}", instance),
                 banner, body, f"<script>{_REPLAY_JS}</script>")


# ── instance scanning + CLI ─────────────────────────────────────────────────
def scan_ledgers(instance: Path | str) -> dict[str, dict[str, str]]:
    instance = Path(instance)
    ledgers: dict[str, dict[str, str]] = {}
    candidates = list(instance.glob("projects/*/_lifecycle.md"))
    candidates += list(instance.glob("docs/specs/*/_lifecycle.md"))
    for path in sorted(candidates):
        ledgers[path.parent.name] = _ledger.parse_ledger(path.read_text(encoding="utf-8"))
    return ledgers


def main(argv: list[str] | None = None) -> int:
    import argparse
    from datetime import datetime, timezone

    from . import schema

    ap = argparse.ArgumentParser(prog="glasstrace.wall", description="Generate the glass wall")
    ap.add_argument("--instance", default=str(_PKG_ROOT))
    ap.add_argument("--events", default=None, help="events.jsonl (default <instance>/logs/events.jsonl)")
    ap.add_argument("--locale", default="zh")
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    instance = Path(args.instance)
    events_path = Path(args.events) if args.events else instance / "logs" / "events.jsonl"
    ledgers = scan_ledgers(instance)

    # Reconcile FIRST: catch any manual ledger edit the hook missed and record it
    # before we render, so the wall reflects a complete event stream (R12, ②).
    cache_path = instance / "logs" / "ledger-cache.json"
    reconciled = _ledger.reconcile_instance(ledgers, events_path, cache_path)
    if reconciled:
        print(f"  reconcile: recorded {len(reconciled)} catch-up transition(s)")

    text = events_path.read_text(encoding="utf-8") if events_path.is_file() else ""
    events, _bad = schema.parse_events(text)
    locale = load_locale(args.locale)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    if args.replay:
        out = Path(args.out) if args.out else instance / "glasswall" / "replay.html"
        html_out = build_replay(ledgers, events, locale, instance.name, now)
    else:
        out = Path(args.out) if args.out else instance / "glasswall" / "wall.html"
        html_out = build_regular(ledgers, events, locale, instance.name, now)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_out, encoding="utf-8")
    print(f"✓ wall generated: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
