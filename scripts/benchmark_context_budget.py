"""Matched synthetic offline context measurements; never constructs a real provider.

Run before/after an implementation with --label and --output. Token estimates
are byte/4 estimates only, not tokenizer measurements, latency, or quality scores.
"""
from __future__ import annotations
import argparse
import asyncio
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from diplomind.agent import Agent
try:
    from diplomind.context_budget import legal_from_context
except ImportError:  # Allows this capture script to run against the pre-budget revision.
    def legal_from_context(ctx): return list(ctx.get("legal", []))
from diplomind.engine import OperationEngine
from diplomind.personalities import PERSONAS
from diplomind.providers.mock import context_from


class Capture:
    def __init__(self): self.calls = []
    async def achat(self, messages, schema, **kwargs):
        self.calls.append((kwargs.get("tag", "").split(":")[-1], messages))
        return schema()


def scenario(name):
    eng = OperationEngine()
    gw = Capture()
    ag = Agent("ENGLAND", PERSONAS["diplomat"], gw)
    if name == "opening": return ag, eng, gw
    eng.submit("ENGLAND", ["F EDI - NTH", "F LON - NTH", "A LVP - YOR"])
    eng.process()
    ag.mem.record_order_diagnostics("S1901M", [{"code": "own_destination_collision", "destination": "NTH",
        "orders": ["F EDI - NTH", "F LON - NTH"], "acknowledged": False}])
    ag.mem.intent = {"goal": "Take NOR safely", "ally": "FRANCE", "target": "GERMANY", "grab": ["NOR"]}
    ag.mem.add_commitment("FRANCE", "UNRESOLVED_NEEDLE: keep ENG demilitarized until F1902M", 1901, 3)
    for p in ("FRANCE", "GERMANY", "ITALY", "RUSSIA", "TURKEY", "AUSTRIA"):
        ag.mem.apply_attitude({p: {"trust": 10, "attitude": "Unverified cooperation proposal"}})
    records = [{"sender": "FRANCE", "scope": "private", "to": ["ENGLAND"], "rnd": 1,
                "text": "DIRECT_NEEDLE: I propose support F NTH - NOR this phase. Please confirm."}]
    for i in range(110):
        records.append({"sender": "ITALY", "scope": "broadcast", "to": [], "rnd": i + 2,
                        "text": f"OLD_CHAT_{i}: " + "We are discussing distant southern borders and reviewing diplomatic possibilities. " * 10})
    records += [{"sender": "GERMANY", "scope": "private", "to": ["ENGLAND"], "rnd": 113,
                 "text": "UNCERTAIN_NEEDLE: France betrayed Russia, according to a rumour."},
                {"sender": "FRANCE", "scope": "private", "to": ["ENGLAND"], "rnd": 114,
                 "text": "FINAL_NEEDLE: I can support your fleet into NOR; confirm your reply."},
                {"sender": "RUSSIA", "scope": "private", "to": ["TURKEY"], "rnd": 114,
                 "text": "PRIVATE_CANARY_DO_NOT_EXPOSE"}]
    ag.observe_messages(eng.phase(), records)
    visible = records[:-1]
    transcript = "\n".join(f"R{r['rnd']} {r['sender']}·{'私聊@你' if r['scope']=='private' else '群发'}: {r['text']}" for r in visible)
    ag.observe_diplomacy(eng.phase(), transcript)
    for i in range(12): ag.mem.add_diary(f"S{1880+i}M", "Earlier diplomatic chatter " * 40)
    return ag, eng, gw


async def run(label):
    results = []
    for name in ("opening", "crowded_bounce"):
        ag, eng, gw = scenario(name)
        for stage in ("attitude", "intent", "nego", "order"):
            start = time.perf_counter()
            if stage == "attitude": await ag.a_update(eng)
            elif stage == "intent":
                saved = ag.mem.intent
                await ag.a_intent(eng)
                ag.mem.intent = saved
            elif stage == "nego": await ag.a_negotiate(eng, ag.mem.diplomacy)
            else: await ag.a_decide_orders(eng)
            duration = (time.perf_counter() - start) * 1000
            _, messages = gw.calls[-1]
            text = "\n".join(m["content"] for m in messages)
            ctx = context_from(messages)
            row = {"scenario": name, "stage": stage, "utf8_bytes": len(text.encode()), "characters": len(text),
                   "estimated_tokens_bytes_div_4": round(len(text.encode()) / 4), "offline_build_ms": round(duration, 3),
                   "legal_count": len(legal_from_context(ctx)), "recall": {
                       "current_board": ctx.get("units") == eng.game.get_state()["units"],
                       "stable_profile": ctx.get("behavioral_profile") == ag.mem.profile,
                       "private_canary_absent": "PRIVATE_CANARY_DO_NOT_EXPOSE" not in text}}
            if name == "crowded_bounce":
                row["recall"].update({"unresolved_commitment": "UNRESOLVED_NEEDLE" in text,
                                      "older_direct_proposal": "DIRECT_NEEDLE" in text,
                                      "final_received_message": "FINAL_NEEDLE" in text,
                                      "own_bounce": any("bounce" in flags for a in ctx.get("recent_own_adjudications", []) for flags in a.get("results", {}).values()),
                                      "private_warning": bool(ctx.get("own_order_diagnostics")),
                                      "uncertain_claim": any(e.get("kind") == "reported_claim" and e.get("verified") is False for e in ctx.get("visible_evidence", []))})
            row["pruning"] = getattr(ag, "context_stats", {}).get(stage, {})
            results.append(row)
    return {"label": label, "method": "Matched synthetic offline capture only; no model call, credentials, or quality/latency claim. Token counts are byte/4 estimates, not a model tokenizer.", "results": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(run(args.label))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
