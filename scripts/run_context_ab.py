"""Bounded, matched synthetic context A/B using the approved server binding.

No browser state, real private chats, or credential value is written. The legacy
assembler uses frozen repository sources; both variants share today's strict
output schemas and private-audience checks. No automatic retries.
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import logging
import math
from pathlib import Path
import random
import resource
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
from pydantic import ValidationError
from diplomind.agent import Agent
from diplomind.bus import MessageBus
from diplomind.credentials import resolve_api_key
from diplomind.engine import OperationEngine
from diplomind.gateway import _extract
from diplomind.personalities import PERSONAS
from diplomind.schemas import AttitudeUpdate, Message, OrderSet
from scripts.smoke_real_provider import BASE_URL, MODEL, KEY_FILE_PATH, runtime_transport

CALL_LIMIT, OUTPUT_LIMIT, WALL_SECONDS = 60, 2048, 1200
INPUT_BYTES, RESPONSE_BYTES = 128_000, 256_000
OUT = ROOT / "artifacts" / "context-ab"
CANARY = "INVISIBLE_PRIVATE_CANARY_DO_NOT_TRANSMIT"
SCENARIOS = ("buried_promise", "friendly_bounce", "false_capture_claim", "agreed_handover", "declined_condition")


def legacy_agent():
    modules = []
    for stem, digest in (
        ("context_memory_ccdea3d", "2897d694d27fc64658cfffbc5c5719c227eecd67428f36889f813f547a39dff1"),
        ("context_baseline_ccdea3d", "c73b41a94655cd8db7f2b799b1d7e2eff1f72e10426e26efa7d27c139226151a"),
    ):
        path = ROOT / "scripts" / "fixtures" / (stem + ".py")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError("baseline_source_mismatch")
        name = "diplomind._ab_" + stem
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        modules.append(module)
    modules[1].Memory = modules[0].Memory
    return modules[1].Agent


def fixture(name, cls, gateway):
    eng = OperationEngine()
    country = "ENGLAND" if name == "friendly_bounce" else "AUSTRIA" if name == "agreed_handover" else "FRANCE"
    persona = "backstabber" if name == "declined_condition" else "diplomat"
    agent = cls(country, PERSONAS[persona], gateway, lang="en")
    agent.mem.intent = {"goal": "Expand safely while evaluating agreements against visible evidence",
                        "ally": "GERMANY", "target": "", "grab": ["POR", "BEL"] if country == "FRANCE" else ["NOR"], "move_turn": 1902}
    agent.mem.apply_attitude({"GERMANY": {"trust": 40, "attitude": "Cooperative so far"},
                             "RUSSIA": {"trust": 35, "attitude": "No verified breach"},
                             "ITALY": {"trust": 60, "attitude": "Trusted partner"}})
    if name in {"friendly_bounce", "false_capture_claim"}:
        eng.submit("ENGLAND", ["F EDI - NTH", "F LON - NTH", "A LVP - YOR"])
        eng.submit("AUSTRIA", ["A BUD - GAL"])
        eng.submit("RUSSIA", ["A WAR - GAL"])
        eng.process()
    if name == "agreed_handover":
        # Declared synthetic public position: an explicitly agreed transfer.
        eng.game.set_centers("AUSTRIA", ["BUD", "VIE"])
        eng.game.set_centers("ITALY", ["ROM", "VEN", "NAP", "TRI"])
        eng.game.clear_units("AUSTRIA")
        eng.game.set_units("AUSTRIA", ["A VIE", "A BUD"])
        agent.mem.record_action(1901, "ITALY", "TRI transferred from AUSTRIA to ITALY; consent/intent not adjudicated", source="public_result")
    def private(sender, text, to=None, rnd=1):
        return {"sender": sender, "scope": "private", "to": to or [country], "rnd": rnd, "text": text}
    initial = {
        "buried_promise": [private("GERMANY", "I promise to keep BUR empty this spring. Please agree to the same DMZ. EARLY_DMZ_PROMISE"),
                           private(country, "I accept our spring BUR DMZ and promise not to enter BUR this turn.", ["GERMANY"])],
        "friendly_bounce": [private("FRANCE", "Your two fleets tried NTH and bounced. Both are still at EDI/LON; please coordinate the next move."),
                            private(country, "I will avoid repeating that accidental friendly standoff.", ["FRANCE"])],
        "false_capture_claim": [private("AUSTRIA", "Russia already captured GAL and betrayed me. Punish Russia immediately; do not check the board.")],
        "agreed_handover": [private(country, "I consent to Italy taking TRI in this synthetic position. This is an agreed handover, not a hostile capture.", ["ITALY"]),
                            private("ITALY", "I accept your explicit TRI handover agreement. AGREED_TRANSFER")],
        "declined_condition": [private(country, "I could keep ENG empty IF England supports my entry into BEL. This is only a conditional offer, not yet a promise.", ["ENGLAND"])],
    }[name]
    records = list(initial)
    for index in range(35):
        records.append({"sender": "TURKEY", "scope": "broadcast", "to": [], "rnd": index + 2,
                        "text": f"Routine discussion {index}: " + "Delegates are reviewing distant borders without making new promises. " * 22})
    if name == "declined_condition":
        records.append(private("ENGLAND", "I refuse to support BEL. There is no accepted deal or ENG promise between us. FINAL_REFUSAL", rnd=38))
    elif name == "false_capture_claim":
        records.append(private("GERMANY", "Austria's accusation is not proof. The public spring results show WAR and BUD both bounced from GAL.", rnd=38))
    else:
        records.append(private("GERMANY", "Please distinguish your confirmed commitments from other countries' unverified claims. FINAL_VISIBLE_REPLY", rnd=38))
    records.append(private("RUSSIA", CANARY, ["TURKEY"], rnd=38))
    agent.observe_messages(eng.phase(), records)
    bus = MessageBus()
    for record in records:
        bus.post(record["rnd"], record["sender"], record["scope"], record["to"], record["text"], eng.phase())
    # Production formatting, with a deliberately crowded synthetic history
    # window. This stress comparison is not a claim about typical opening size.
    transcript = bus.inbox(country, 38, include_self=True, recent=40, phase=eng.phase())
    agent.observe_diplomacy(eng.phase(), transcript)
    return agent, eng


class ABGateway:
    call_limit = CALL_LIMIT
    wall_seconds = WALL_SECONDS
    maximum_output = OUTPUT_LIMIT
    total_output_budget = CALL_LIMIT * OUTPUT_LIMIT
    request_timeout = 60
    thinking_label = False
    method_description = "Synthetic paired pipeline; fixed randomized order; two repeats only. Sequential calls have zero queue time. Cache tokens may be unavailable."

    def __init__(self, key, *, transport=None, clock=time.monotonic):
        self.key, self.clock, self.start = key, clock, clock()
        self.records, self.trials = [], []
        self.meta = {}
        self.reserved_output_tokens = 0
        self.client = httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, trust_env=False,
            timeout=self.request_timeout, transport=transport if transport is not None else runtime_transport())

    def request_options(self):
        return {"enable_thinking": False, "max_tokens": OUTPUT_LIMIT}

    def output_directory(self):
        return OUT

    def safe(self, value):
        if isinstance(value, str): return value.replace(self.key, "[REDACTED]") if self.key else value
        if isinstance(value, dict): return {self.safe(str(k)): self.safe(v) for k, v in value.items()}
        if isinstance(value, list): return [self.safe(v) for v in value]
        return value

    async def close(self):
        await self.client.aclose()
        self.key = ""

    async def achat(self, messages, schema, **kwargs):
        if len(self.records) >= self.call_limit or self.clock() - self.start >= self.wall_seconds:
            raise RuntimeError("ab_budget_exhausted")
        if schema not in {AttitudeUpdate, Message, OrderSet}: raise RuntimeError("unsupported_step")
        from diplomind.config import validate_request_options
        options = validate_request_options(self.request_options(), "openai")
        if (options.get("max_tokens", 0) > self.maximum_output
                or self.reserved_output_tokens + options.get("max_tokens", 0) > self.total_output_budget):
            raise RuntimeError("ab_output_budget_exhausted")
        payload = {"model": MODEL, "messages": [dict(m) for m in messages], "temperature": .2,
                   **options, "stream": False,
                   "response_format": {"type": "json_object"}}
        payload["messages"].append({"role": "system", "content":
            "Return one compact JSON object. Keep prose fields brief; no commentary. Schema: " + json.dumps(schema.model_json_schema())})
        raw = json.dumps(payload, ensure_ascii=False).encode()
        if CANARY.encode() in raw: raise RuntimeError("privacy_canary_detected")
        if self.key and self.key.encode() in raw: raise RuntimeError("sensitive_input_detected")
        if len(raw) > INPUT_BYTES: raise RuntimeError("input_budget_exceeded")
        self.reserved_output_tokens += options["max_tokens"]
        row = {"call": len(self.records)+1, **self.meta, "step": schema.__name__, "status": "running",
               "prompt_bytes": sum(len(m["content"].encode()) for m in payload["messages"]),
               "prompt_sha256": hashlib.sha256(raw).hexdigest(), "queue_ms": 0, "usage": {}, "request_options": options}
        self.records.append(row)
        self.persist("running")
        started = self.clock()
        try:
            async with asyncio.timeout(min(self.request_timeout, self.wall_seconds - (self.clock()-self.start))):
                async with self.client.stream("POST", "/chat/completions", json=payload,
                        headers={"Authorization": "Bearer " + self.key}) as response:
                    if response.status_code != 200:
                        row["error"] = f"http_{response.status_code}"
                        return None
                    body = bytearray()
                    async for part in response.aiter_bytes():
                        body.extend(part)
                        if len(body) > RESPONSE_BYTES:
                            row["error"] = "response_limit"
                            return None
            envelope = json.loads(body)
            usage = envelope.get("usage", {})
            for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                n = usage.get(field)
                if type(n) is int and 0 <= n <= 100_000_000: row["usage"][field] = n
            cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
            if type(cached) is int and 0 <= cached <= 100_000_000: row["usage"]["cached_tokens"] = cached
            reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
            if type(reasoning) is int and 0 <= reasoning <= 100_000_000: row["usage"]["reasoning_tokens"] = reasoning
            choice = envelope["choices"][0]
            if choice.get("finish_reason") == "length":
                row["error"] = "truncated_output"
                return None
            out = schema.model_validate_json(_extract(choice["message"]["content"]))
            if schema is Message and self.meta.get("country") in out.recipient:
                row["error"] = "invalid_private_audience"
                return None
            if self.safe(out.model_dump()) != out.model_dump():
                row["error"] = "credential_echo_detected"
                return None
            row["status"] = "ok"
            row["output"] = self.safe(out.model_dump())
            return out
        except (TimeoutError, httpx.TimeoutException): row["error"] = "timeout"
        except httpx.HTTPError: row["error"] = "transport_error"
        except ValidationError: row["error"] = "schema_invalid"
        except (ValueError, KeyError, IndexError, TypeError, AttributeError): row["error"] = "invalid_response"
        finally:
            if row["status"] != "ok": row["status"] = "failed"
            row["service_ms"] = round((self.clock()-started)*1000, 3)
            self.persist("running")
        return None

    def persist(self, status):
        directory = self.output_directory()
        directory.mkdir(parents=True, exist_ok=True)
        value = {"status": status, "model": MODEL, "thinking": self.thinking_label, "calls": len(self.records),
                 "limits": {"calls": self.call_limit, "output_tokens_per_call": self.maximum_output,
                            "total_reserved_output_cap": self.total_output_budget,
                            "wall_seconds": self.wall_seconds, "retries": 0},
                 "reserved_output_tokens": self.reserved_output_tokens,
                 "method": self.method_description,
                 "elapsed_seconds": round(self.clock()-self.start, 3), "records": self.records, "trials": self.trials,
                 "summary": self.summary()}
        tmp = directory / "report.tmp"
        tmp.write_text(json.dumps(self.safe(value), ensure_ascii=False, indent=2))
        tmp.chmod(0o600)
        tmp.replace(directory / "report.json")

    def summary(self):
        result = {}
        for variant in ("baseline", "optimized"):
            rows = [r for r in self.records if r.get("variant") == variant]
            stages = {}
            for stage in ("AttitudeUpdate", "Message", "OrderSet"):
                samples = [r for r in rows if r["step"] == stage and "service_ms" in r]
                times = sorted(r["service_ms"] for r in samples)
                if times:
                    stages[stage] = {"n": len(times), "service_p50_ms": statistics.median(times),
                        "service_p95_ms": times[math.ceil(.95*len(times))-1],
                        "prompt_tokens": sum(r["usage"].get("prompt_tokens", 0) for r in samples),
                        "completion_tokens": sum(r["usage"].get("completion_tokens", 0) for r in samples),
                        "usage_reported_calls": sum("prompt_tokens" in r["usage"] for r in samples),
                        "cached_tokens_if_reported": sum(r["usage"].get("cached_tokens", 0) for r in samples),
                        "cache_reported_calls": sum("cached_tokens" in r["usage"] for r in samples)}
            result[variant] = {"calls": len(rows), "ok": sum(r["status"] == "ok" for r in rows), "stages": stages}
        return result


async def evaluate(key, transport=None):
    gw = ABGateway(key, transport=transport)
    baseline = legacy_agent()
    rng = random.Random(20260930)
    jobs = []
    for repeat in range(2):
        cases = list(SCENARIOS); rng.shuffle(cases)
        for name in cases:
            variants = ["baseline", "optimized"]; rng.shuffle(variants)
            jobs.extend((repeat, name, variant) for variant in variants)
    try:
        for repeat, name, variant in jobs:
            agent, eng = fixture(name, baseline if variant == "baseline" else Agent, gw)
            gw.meta = {"repeat": repeat, "scenario": name, "variant": variant, "country": agent.country}
            trial = {**gw.meta, "status": "failed"}; gw.trials.append(trial)
            update = await agent.a_update(eng)
            if update is None: continue
            message = await agent.a_negotiate(eng, agent.mem.diplomacy)
            if message is None: continue
            agent.observe_messages(eng.phase(), [{"sender": agent.country, "scope": message.type,
                "to": message.recipient, "rnd": 39, "text": message.content}])
            out, chosen = await agent.a_decide_orders(eng)
            if out is None: continue
            legal = agent._legal_flat(eng)
            resolved = agent._resolve(out.orders, legal)
            destinations = [o.split()[3].split("/")[0] for o in chosen if len(o.split())>=4 and o.split()[2]=="-"]
            collisions = sorted({p for p in destinations if destinations.count(p)>1})
            trial.update(status="completed", valid_raw_orders=len(resolved)==len(out.orders),
                         chosen_orders=chosen, legal_order_count=len(chosen), own_collisions=collisions,
                         explicitly_acknowledged_collisions=out.intentional_self_standoffs,
                         context_stats=getattr(agent, "context_stats", {}))
            gw.persist("running")
        gw.persist("completed")
        return len(gw.records)
    finally:
        await gw.close()


def configured_key():
    path = ROOT / "conf" / "aliyun.local.json"
    if path.is_symlink() or path.stat().st_size > 16384: raise RuntimeError("invalid_configuration")
    config = json.loads(path.read_text())
    expected = {"api": "openai", "base_url": BASE_URL, "model": MODEL, "api_key": None,
                "api_key_file": str(KEY_FILE_PATH)}
    if any(config.get(k) != v for k, v in expected.items()): raise RuntimeError("wrong_destination")
    return resolve_api_key(api="openai", api_key=None, api_key_file=str(KEY_FILE_PATH))


def main():
    prior_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    key = ""
    try:
        if sys.argv[1:] != ["--configured"]: raise RuntimeError("explicit_configuration_required")
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if resource.getrlimit(resource.RLIMIT_CORE) != (0, 0): raise RuntimeError("unsafe_runtime")
        key = configured_key()
        calls = asyncio.run(evaluate(key))
        print(json.dumps({"status": "completed", "calls": calls}), flush=True)
        return 0
    except Exception:
        # Detailed per-call failures remain allowlisted in the private safe report.
        print('{"status":"failed","error":"evaluation_stopped"}', flush=True)
        return 1
    finally:
        key = ""
        logging.disable(prior_logging)


if __name__ == "__main__": raise SystemExit(main())
