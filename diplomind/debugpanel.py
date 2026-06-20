"""Debug panel: aggregate snapshots + LLM logs into one timeline, filter by round/country/channel.

Spectate = chat+orders+map; debug = intent+memory+every call."""
from __future__ import annotations

import json
from pathlib import Path


def llm_calls(run_id: str, country: str | None = None) -> list[dict]:
    p = Path("logs") / f"calls-{run_id}.jsonl"
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    if country:
        rows = [r for r in rows if r.get("tag", "").startswith(country)]
    return rows


def messages(bus, country: str | None = None, scope: str | None = None) -> list[dict]:
    out = []
    for m in bus.msgs:
        if country and country not in (m.sender, *m.to):
            continue
        if scope and m.scope != scope:
            continue
        out.append({"rnd": m.rnd, "from": m.sender, "scope": m.scope, "to": m.to, "text": m.text})
    return out


def snapshot(agents: dict, bus, eng) -> dict:
    """Full internals: intent/memory/persona + chat + map."""
    return {"phase": eng.phase(), "centers": eng.centers(),
            "agents": {c: a.snapshot() for c, a in agents.items()},
            "messages": messages(bus)}
