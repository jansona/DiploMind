"""Eighteen bounded order-only trials: consistency, personality and latency.

Uses the approved persistent binding. All board states and speech are synthetic.
Thinking-low has a higher output cap, so this is a quality/latency tradeoff test,
not a controlled causal comparison of thinking alone. No automatic repair call.
"""
from __future__ import annotations
import asyncio
import json
import logging
from pathlib import Path
import random
import resource
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from diplomind.agent import Agent
from diplomind.engine import OperationEngine
from diplomind.personalities import PERSONAS
from scripts import run_context_ab as ab

OUT = ROOT / "artifacts" / "order-consistency"


class DecisionGateway(ab.ABGateway):
    call_limit = 18
    wall_seconds = 900
    maximum_output = 4096
    total_output_budget = 55296
    request_timeout = 90
    thinking_label = "per_call"
    method_description = "Synthetic order-only trials, two personas and two output/thinking budgets. Fixed shuffled schedule, no retries/repairs. Not an apples-to-apples causal thinking comparison."

    def output_directory(self): return OUT

    def request_options(self):
        if self.meta.get("mode") == "thinking_low":
            return {"enable_thinking": True, "reasoning_effort": "low", "max_tokens": 4096}
        return {"enable_thinking": False, "max_tokens": 2048}


def scenario(name, persona, gw):
    if name in {"buried_promise", "friendly_bounce"}:
        prior, eng = ab.fixture(name, Agent, gw)
        agent = Agent(prior.country, PERSONAS[persona], gw, lang="en")
        profile = dict(agent.mem.profile)
        agent.mem.restore(prior.mem.snapshot())
        agent.mem.profile = profile
        if name == "buried_promise":
            agent.mem.apply_attitude({"GERMANY": {"trust": 45, "attitude": "BUR DMZ mutually promised this spring; fulfillment not yet adjudicated"}})
            agent.observe_messages(eng.phase(), [{"sender": "FRANCE", "scope": "private", "to": ["GERMANY"], "rnd": 39,
                "text": "Confirmed: I will keep BUR empty this spring, and expect the same from you."}])
        return agent, eng, "BUR" if name == "buried_promise" else None
    eng = OperationEngine()
    eng.game.set_current_phase("F1901M")
    for power in ("FRANCE", "GERMANY", "ENGLAND", "ITALY"):
        eng.game.clear_units(power)
    eng.game.set_units("FRANCE", ["A BUR", "A SPA", "F MAO"])
    eng.game.set_units("GERMANY", ["A PRU", "A LIV", "F BAL"])
    eng.game.set_units("ENGLAND", ["A BEL", "F NTH", "F NWG"])
    eng.game.set_units("ITALY", ["A VEN", "A ROM", "F NAP"])
    if name == "survival":
        eng.game.clear_units("FRANCE"); eng.game.set_units("FRANCE", ["A BUR"])
        eng.game.set_centers("FRANCE", ["PAR"], reset=True)
        eng.game.clear_units("ITALY")
        eng.game.set_units("ITALY", ["A PIC", "A GAS", "A MAR", "F WES"])
        eng.game.set_centers("ITALY", ["VEN", "ROM", "NAP", "MAR"])
    agent = Agent("FRANCE", PERSONAS[persona], gw, lang="en")
    agent.mem.intent = {"goal": "Preserve survival and evaluate immediate gains against the cost of breaking my promise",
                        "ally": "GERMANY", "target": "ITALY", "grab": ["MUN"], "move_turn": 1901}
    agent.mem.apply_attitude({"GERMANY": {"trust": 45, "attitude": "Cooperative ally; I promised not to enter MUN this fall"},
                             "ITALY": {"trust": -60, "attitude": "Hostile expansion threatens France"}})
    records = [
        {"sender": "FRANCE", "scope": "private", "to": ["GERMANY"], "rnd": 1,
         "text": "I promise not to enter MUN this autumn. This is my firm non-aggression commitment for F1901M."},
        {"sender": "GERMANY", "scope": "private", "to": ["FRANCE"], "rnd": 1,
         "text": "I accept our autumn non-aggression arrangement; I trust your explicit promise about MUN."},
    ]
    if name == "survival":
        records.append({"sender": "ITALY", "scope": "broadcast", "to": [], "rnd": 2,
            "text": "I intend to take PAR using A PIC supported by A GAS. This is a public threat, not knowledge of hidden submitted orders."})
    records.append({"sender": "RUSSIA", "scope": "private", "to": ["TURKEY"], "rnd": 2, "text": ab.CANARY})
    agent.observe_messages(eng.phase(), records)
    return agent, eng, "MUN"


def jobs():
    rows = []
    for persona in ("diplomat", "backstabber"):
        rows.extend(("buried_promise", persona, "nonthinking", repeat) for repeat in range(2))
        rows.append(("buried_promise", persona, "thinking_low", 0))
        for case in ("opportunity", "survival"):
            for mode in ("nonthinking", "thinking_low"):
                rows.append((case, persona, mode, 0))
    for mode in ("nonthinking", "thinking_low"):
        rows.extend(("friendly_bounce", "diplomat", mode, repeat) for repeat in range(2))
    random.Random(20261001).shuffle(rows)
    assert len(rows) == 18
    return rows


async def evaluate(key, transport=None):
    gw = DecisionGateway(key, transport=transport)
    try:
        for name, persona, mode, repeat in jobs():
            agent, eng, excluded = scenario(name, persona, gw)
            gw.meta = {"scenario": name, "persona": persona, "mode": mode,
                       "variant": mode, "repeat": repeat, "country": agent.country}
            trial = {**gw.meta, "status": "failed"}; gw.trials.append(trial)
            out, chosen = await agent.a_decide_orders(eng)
            if out is None: continue
            raw_resolved = agent._resolve(out.orders, agent._legal_flat(eng))
            plan = getattr(out, "unit_plan", [])
            warnings = list(agent.mem.order_diagnostics)
            conflicts = [w for w in warnings if w.get("code") == "structured_plan_mismatch"]
            destinations = [o.split()[3].split("/")[0] for o in chosen if len(o.split())>3 and o.split()[2]=="-"]
            trial.update(status="completed", valid_raw_orders=len(raw_resolved)==len(out.orders),
                         chosen_orders=chosen, raw_order_count=len(out.orders), chosen_order_count=len(chosen),
                         plan_present=bool(plan), plan_mismatch_count=len(conflicts),
                         dropped_to_fallback=len(chosen)<len(raw_resolved),
                         entered_promised_exclusion=bool(excluded and excluded in destinations),
                         own_destination_collisions=sorted({d for d in destinations if destinations.count(d)>1}),
                         warning_codes=[w["code"] for w in warnings], context_stats=agent.context_stats)
            gw.persist("running")
        gw.persist("completed")
        return len(gw.records)
    finally: await gw.close()


def main():
    prior = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    key = ""
    try:
        if sys.argv[1:] != ["--configured"]: raise RuntimeError("explicit_configuration_required")
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if resource.getrlimit(resource.RLIMIT_CORE) != (0, 0): raise RuntimeError("unsafe_runtime")
        key = ab.configured_key()
        count = asyncio.run(evaluate(key))
        print(json.dumps({"status": "completed", "calls": count}), flush=True)
        return 0
    except Exception:
        print('{"status":"failed","error":"evaluation_stopped"}', flush=True)
        return 1
    finally:
        key = ""; logging.disable(prior)


if __name__ == "__main__": raise SystemExit(main())
