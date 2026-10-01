#!/usr/bin/env python3
"""One-shot, explicitly authorized provider check. Never persists credentials.

Only a human in a real terminal can enter a key or authorize reading its pinned
private file. Noninteractive/echo fallback is forbidden. This file's tests use an in-process fake endpoint with synthetic auth.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import getpass
import json
import logging
import os
from pathlib import Path
import sys
import stat
import time
import warnings
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx
from pydantic import ValidationError

from diplomind.agent import Agent
from diplomind.engine import OperationEngine
from diplomind.gateway import _extract
from diplomind.personalities import PERSONAS
from diplomind.schemas import AttitudeUpdate, Intent, Message, OrderSet

BASE_URL = "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
MODEL = "deepseek-v4.1-flash"
MAX_CALLS = 8
CORE_CALLS = 6
MAX_OUTPUT_TOKENS = 700
TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 256_000
MAX_INPUT_BYTES = 100_000
RESULT_PATH = ROOT / "artifacts" / "provider-smoke-result.json"
KEY_FILE_PATH = Path.home() / ".config" / "diplomind" / "api-key.txt"
MAX_KEY_BYTES = 8192


class SmokeFailure(RuntimeError):
    """Only allowlisted codes, never exception bodies/headers or provider text."""
    CODES = {"call_budget", "invalid_input", "timeout", "transport_error", "redirect_refused",
             "authentication_failed", "access_denied", "rate_or_quota_limit", "provider_error",
             "invalid_response", "truncated_output", "schema_invalid", "response_limit",
             "no_orders", "illegal_orders", "empty_negotiation", "wrong_destination",
             "unsafe_terminal", "empty_key", "unsafe_key_file", "invalid_key",
             "interrupted", "internal_error"}

    def __init__(self, code: str):
        self.code = code if code in self.CODES else "internal_error"
        super().__init__(self.code)


def runtime_transport() -> httpx.AsyncHTTPTransport:
    """Use the platform's approved HTTPS route without reading unrelated settings.

    Explicit HTTPS_PROXY avoids implicit ALL_PROXY/SOCKS discovery. Proxy strings
    (which may include runtime credentials) are never printed or included in a
    report. The selected model's HTTPS destination remains separately pinned.
    """
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    return httpx.AsyncHTTPTransport(retries=0, trust_env=True, proxy=proxy)


class SmokeGateway:
    """Small test harness, deliberately bypassing app logs, retry and save machinery."""
    def __init__(self, key: str, *, base_url: str = BASE_URL, model: str = MODEL,
                 transport: httpx.AsyncBaseTransport | None = None,
                 disable_thinking: bool = False, core_only: bool = False) -> None:
        # Even an explicitly supplied CLI argument cannot redirect the credential.
        if base_url != BASE_URL or model != MODEL:
            raise SmokeFailure("wrong_destination")
        if not key or not key.strip():
            raise SmokeFailure("empty_key")
        self._key = key
        self.calls = 0
        self.max_calls = CORE_CALLS if core_only else MAX_CALLS
        self.thinking_enabled = False if disable_thinking else None
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self.usage_reported_calls = 0
        self.call_reports: list[dict] = []
        self.client = httpx.AsyncClient(base_url=base_url, trust_env=False, follow_redirects=False,
            timeout=httpx.Timeout(TIMEOUT_SECONDS),
            transport=transport if transport is not None else runtime_transport())
        self.model = model

    async def aclose(self) -> None:
        await self.client.aclose()
        self._key = ""  # best effort only; Python strings cannot promise zeroization

    async def achat(self, messages, schema, tag="", retry=0, temp=None):
        if self.calls >= self.max_calls:
            raise SmokeFailure("call_budget")
        if schema not in (AttitudeUpdate, Intent, Message, OrderSet):
            raise SmokeFailure("invalid_input")
        # Agent's ordinary retry argument is intentionally ignored. This harness
        # never retries and never invokes an alternative provider.
        payload = {"model": self.model, "messages": [dict(m) for m in messages],
                   "temperature": .2 if temp is None else temp, "max_tokens": MAX_OUTPUT_TOKENS,
                   "stream": False, "response_format": {"type": "json_object"}}
        if self.thinking_enabled is False:
            payload["enable_thinking"] = False
        concise = {
            AttitudeUpdate: "Use at most 12 words per attitude; use country codes as keys.",
            Intent: "Use at most 24 words for goal. Use country codes for ally/target and province codes for grab.",
            Message: "Use at most 80 words for content and country codes for recipient.",
            OrderSet: "Use at most 40 words for reasoning; copy each order verbatim from the legal list.",
        }[schema]
        payload["messages"].append({"role": "system", "content":
            concise + " Return one JSON object matching this schema. Keep every prose field brief. "
            + json.dumps(schema.model_json_schema(), ensure_ascii=False)})
        if len(json.dumps(payload, ensure_ascii=False).encode()) > MAX_INPUT_BYTES:
            raise SmokeFailure("invalid_input")
        self.calls += 1
        started = time.monotonic()
        report = {"call": self.calls, "step": schema.__name__, "status": "failed"}
        self.call_reports.append(report)
        try:
            async with asyncio.timeout(TIMEOUT_SECONDS):
                # Stream to enforce byte limits before buffering a potentially
                # malformed response. Headers and raw content are never printed.
                async with self.client.stream("POST", "/chat/completions",
                        headers={"Authorization": "Bearer " + self._key}, json=payload) as response:
                    status = response.status_code
                    if 300 <= status < 400: raise SmokeFailure("redirect_refused")
                    if status == 401: raise SmokeFailure("authentication_failed")
                    if status == 403: raise SmokeFailure("access_denied")
                    if status == 429: raise SmokeFailure("rate_or_quota_limit")
                    if status >= 400: raise SmokeFailure("provider_error")
                    body = bytearray()
                    async for part in response.aiter_bytes():
                        body.extend(part)
                        if len(body) > MAX_RESPONSE_BYTES: raise SmokeFailure("response_limit")
            envelope = json.loads(body)
            if not isinstance(envelope, dict): raise SmokeFailure("invalid_response")
            usage = envelope.get("usage")
            if isinstance(usage, dict):
                self.usage_reported_calls += 1
                for field in self.usage:
                    value = usage.get(field, 0)
                    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 100_000_000:
                        self.usage[field] += value
            choices = envelope.get("choices")
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                raise SmokeFailure("invalid_response")
            choice = choices[0]
            if choice.get("finish_reason") == "length": raise SmokeFailure("truncated_output")
            message = choice.get("message")
            if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                raise SmokeFailure("invalid_response")
            out = schema.model_validate_json(_extract(message["content"]))
            report["status"] = "ok"
            return out
        except SmokeFailure as exc:
            report["error"] = exc.code
            raise
        except (TimeoutError, httpx.TimeoutException):
            report["error"] = "timeout"
            raise SmokeFailure("timeout") from None
        except httpx.HTTPError:
            report["error"] = "transport_error"
            raise SmokeFailure("transport_error") from None
        except ValidationError:
            report["error"] = "schema_invalid"
            raise SmokeFailure("schema_invalid") from None
        except (ValueError, KeyError, IndexError, TypeError):
            report["error"] = "invalid_response"
            raise SmokeFailure("invalid_response") from None
        finally:
            report["latency_ms"] = round((time.monotonic() - started) * 1000)


def scenario_messages() -> list[dict]:
    """Synthetic game data only. The hidden control must never reach the provider."""
    return [
        {"rnd": 1, "sender": "GERMANY", "scope": "broadcast", "to": [],
         "text": "I propose DMZ BUR this spring. We can discuss support into BEL later."},
        {"rnd": 1, "sender": "FRANCE", "scope": "private", "to": ["GERMANY"],
         "text": "I agree to DMZ BUR this spring. This promise covers only the current spring."},
        {"rnd": 2, "sender": "ENGLAND", "scope": "private", "to": ["FRANCE"],
         "text": "If you keep ENG empty, I will keep my fleet out of ENG. Can you confirm?"},
        {"rnd": 2, "sender": "ITALY", "scope": "private", "to": ["FRANCE"],
         "text": "I heard GERMANY betrayed RUSSIA. This is an unverified third-party accusation, not something I witnessed."},
        {"rnd": 2, "sender": "RUSSIA", "scope": "private", "to": ["TURKEY"],
         "text": "INVISIBLE_SMOKE_CONTROL_DO_NOT_TRANSMIT"},
    ]


def visible_transcript(records: list[dict], country: str) -> str:
    visible = [r for r in records if r["scope"] == "broadcast" or r["sender"] == country or country in r["to"]]
    # JSON, not forged speaker-prefix parsing; transport only the authorized view.
    return json.dumps(visible, ensure_ascii=False, separators=(",", ":"))


async def run_smoke(key: str, *, transport: httpx.AsyncBaseTransport | None = None,
                    disable_thinking: bool = False, core_only: bool = False) -> dict:
    """At most 8 sequential calls. Stop on first failure; output only safe metadata."""
    gw = SmokeGateway(key, transport=transport, disable_thinking=disable_thinking, core_only=core_only)
    report = {"provider": "Aliyun OpenAI-compatible endpoint", "model": MODEL,
              "status": "failed", "thinking_enabled": gw.thinking_enabled, "core_only": core_only,
              "calls": 0, "limits": {"calls": gw.max_calls,
              "output_tokens_per_call": MAX_OUTPUT_TOKENS, "timeout_seconds": TIMEOUT_SECONDS,
              "retries": 0}, "scenarios": [], "error": None}
    prior_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        for persona_key in ("diplomat", "backstabber"):
            eng = OperationEngine()
            agent = Agent("FRANCE", PERSONAS[persona_key], gw, lang="en")
            agent.mem.apply_attitude({"GERMANY": {"trust": 35, "attitude": "Prior cooperation, current promise not yet adjudicated"}})
            agent.mem.add_commitment("GERMANY", "DMZ BUR this spring; do not enter BUR", rnd=1, turns=1)
            records = scenario_messages()
            agent.observe_messages(eng.phase(), records)
            transcript = visible_transcript(records, "FRANCE")
            if not core_only:
                await agent.a_update(eng, transcript)
            await agent.a_intent(eng)
            negotiation = await agent.a_negotiate(eng, transcript)
            if not negotiation or not negotiation.content.strip(): raise SmokeFailure("empty_negotiation")
            records.append({"rnd": 3, "sender": "FRANCE", "scope": negotiation.type,
                            "to": negotiation.recipient, "text": negotiation.content})
            # A final delivered human reply arrives AFTER the generated message.
            records.append({"rnd": 3, "sender": "ENGLAND", "scope": "private", "to": ["FRANCE"],
                            "text": "Final confirmation: no fleet into ENG this spring. Our agreement is limited to this turn."})
            agent.observe_messages(eng.phase(), records)
            final_transcript = visible_transcript(records, "FRANCE")
            out, chosen = await agent.a_decide_orders(eng, inbox=final_transcript)
            if not out or not chosen: raise SmokeFailure("no_orders")
            # Legal membership and unit uniqueness are checked independently of
            # resolver filtering. Raw malformed/illegal orders must fail the smoke.
            raw_resolved = agent._resolve(out.orders, agent._legal_flat(eng))
            if len(raw_resolved) != len(out.orders) or len(chosen) != len(eng.legal_orders("FRANCE")):
                raise SmokeFailure("illegal_orders")
            result = eng.submit("FRANCE", chosen)
            if result.has_error: raise SmokeFailure("illegal_orders")
            provenance = Counter(e["source"] for e in agent.mem.evidence)
            report["scenarios"].append({"persona": persona_key, "status": "ok", "orders": chosen,
                "legal_orders": len(chosen), "message_scope": negotiation.type,
                "message_characters": len(negotiation.content), "visible_evidence": dict(provenance),
                "unverified_claims": sum(e["kind"] == "reported_claim" and not e["verified"] for e in agent.mem.evidence),
                "final_round_in_order_context": agent.mem.diplomacy == final_transcript,
                "profile_persisted": agent.mem.snapshot()["profile"] == agent.mem.profile})
        report["status"] = "ok"
    except SmokeFailure as exc:
        report["error"] = exc.code
    except asyncio.CancelledError:
        report["error"] = "interrupted"
    except Exception:
        # Never stringify an exception: providers can put secrets in error text.
        report["error"] = "internal_error"
    finally:
        await gw.aclose()
        logging.disable(prior_logging)
        report.update(calls=gw.calls, usage=dict(gw.usage), usage_reported_calls=gw.usage_reported_calls,
                      call_reports=list(gw.call_reports))
    report["interpretation"] = "Connection/schema/legal-order smoke only; not proof of human-like strategy or play quality"
    return report


def secure_key_prompt() -> str:
    if not all(stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr)):
        raise SmokeFailure("unsafe_terminal")
    try:
        # If platform echo control fails, getpass normally falls back to visible
        # input. Converting its warning to an exception forbids that fallback.
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            key = getpass.getpass("API key (hidden; Enter starts the bounded test, Ctrl-C cancels): ", stream=sys.stderr)
    except (getpass.GetPassWarning, OSError, EOFError):
        raise SmokeFailure("unsafe_terminal") from None
    if not key or not key.strip(): raise SmokeFailure("empty_key")
    return key


def read_private_key_file(path: Path) -> str:
    """Read only the pinned file; never create, modify, delete, or echo it."""
    if path != KEY_FILE_PATH:
        raise SmokeFailure("unsafe_key_file")
    parent_fd = file_fd = None
    try:
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        parent = os.fstat(parent_fd)
        if parent.st_uid != os.geteuid() or stat.S_IMODE(parent.st_mode) != 0o700:
            raise SmokeFailure("unsafe_key_file")
        file_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
        info = os.fstat(file_fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_size > MAX_KEY_BYTES):
            raise SmokeFailure("unsafe_key_file")
        with os.fdopen(file_fd, "rb") as source:
            file_fd = None
            raw = source.read(MAX_KEY_BYTES + 1)
        if len(raw) > MAX_KEY_BYTES:
            raise SmokeFailure("unsafe_key_file")
        raw = raw.strip()
        if not raw:
            raise SmokeFailure("empty_key")
        if any(byte < 33 or byte > 126 for byte in raw):
            raise SmokeFailure("invalid_key")
        return raw.decode("ascii")
    except (OSError, ValueError):
        raise SmokeFailure("unsafe_key_file") from None
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if parent_fd is not None:
            os.close(parent_fd)


def confirmed_key_file(path: Path) -> str:
    if not all(stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr)):
        raise SmokeFailure("unsafe_terminal")
    print(f"Save ONLY your API key in {path}, then save and close the editor.\n"
          "The private file is retained; this program never changes or deletes it.\n"
          "保存文件后关闭编辑器，再回到此终端按 Enter 开始；Ctrl+C 取消。", flush=True)
    try:
        # Hide even accidental pastes here; only an empty Enter confirms.
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            answer = getpass.getpass(
                "Do not paste the key here; only press Enter after saving the file: ",
                stream=sys.stderr)
    except (getpass.GetPassWarning, EOFError, OSError):
        raise SmokeFailure("unsafe_terminal") from None
    if answer:
        raise SmokeFailure("invalid_input")
    return read_private_key_file(path)


def persist_safe_result(report: dict, path: Path | None = None) -> None:
    """Persist only allowlisted diagnostic counters, never provider prose or inputs.

    Results can be inspected without photographing credential-entry terminals.
    Deliberately omit orders and scenario text too: the terminal may still show
    those known-legal synthetic orders, but this file is a minimal status channel.
    """
    if path is None:
        path = RESULT_PATH
    def count(value, maximum=100_000_000):
        return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= maximum else 0
    states = {"ok", "failed", "blocked", "interrupted", "awaiting_input", "running"}
    steps = {"AttitudeUpdate", "Intent", "Message", "OrderSet"}
    result = {"status": report.get("status") if report.get("status") in states else "failed",
              "error": report.get("error") if report.get("error") in SmokeFailure.CODES else None,
              "model": MODEL, "updated_at_unix": round(time.time(), 3),
              "thinking_enabled": False if report.get("thinking_enabled") is False else None,
              "core_only": report.get("core_only") is True,
              "limits": {"calls": CORE_CALLS if report.get("core_only") is True else MAX_CALLS,
                         "output_tokens_per_call": MAX_OUTPUT_TOKENS,
                         "timeout_seconds": TIMEOUT_SECONDS, "retries": 0},
              "calls": count(report.get("calls"), MAX_CALLS),
              "usage": {k: count((report.get("usage") or {}).get(k)) for k in
                        ("prompt_tokens", "completion_tokens", "total_tokens")},
              "usage_reported_calls": count(report.get("usage_reported_calls"), MAX_CALLS),
              "scenarios_completed": min(2, len(report.get("scenarios") or [])),
              "call_reports": []}
    for item in (report.get("call_reports") or [])[:MAX_CALLS]:
        result["call_reports"].append({
            "call": count(item.get("call"), MAX_CALLS),
            "step": item.get("step") if item.get("step") in steps else "unknown",
            "status": item.get("status") if item.get("status") in states else "failed",
            "error": item.get("error") if item.get("error") in SmokeFailure.CODES else None,
            "latency_ms": count(item.get("latency_ms")),
        })
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, encoding="utf-8") as output:
        temporary = Path(output.name)
        json.dump(result, output, ensure_ascii=False, indent=2)
        output.flush()
        os.fsync(output.fileno())
    try:
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    class SafeParser(argparse.ArgumentParser):
        def error(self, message):
            # argparse normally echoes untrusted argument values.
            raise SmokeFailure("invalid_input")

    def fail(status, code, exit_code):
        result = {"status": status, "error": code, "calls": 0, **mode_report}
        try:
            persist_safe_result(result)
        except Exception:
            # A failed diagnostic write must not cause a raw traceback.
            result["error"] = "internal_error"
        print(json.dumps(result), file=sys.stderr, flush=True)
        return exit_code

    key = ""
    mode_report = {"thinking_enabled": None, "core_only": False}
    try:
        parser = SafeParser(description=__doc__)
        parser.add_argument("--base-url", choices=[BASE_URL], default=BASE_URL)
        parser.add_argument("--model", choices=[MODEL], default=MODEL)
        parser.add_argument("--key-file", choices=[str(KEY_FILE_PATH)], default=None,
                            help="Read the pinned private file only after terminal confirmation")
        parser.add_argument("--disable-thinking", action="store_true",
                            help="Explicitly request enable_thinking=false from the provider")
        parser.add_argument("--core-only", action="store_true",
                            help="Six calls: intent, message, and orders for each of two personas")
        args = parser.parse_args(argv)
        mode_report = {"thinking_enabled": False if args.disable_thinking else None,
                       "core_only": args.core_only}
        call_limit = CORE_CALLS if args.core_only else MAX_CALLS
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except (ImportError, OSError, ValueError):
            raise SmokeFailure("unsafe_terminal") from None
        if not all(stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr)):
            raise SmokeFailure("unsafe_terminal")
        print(f"Destination: {BASE_URL}\nModel: {MODEL}\n"
              f"Limit: {call_limit} calls total, {MAX_OUTPUT_TOKENS} output tokens/call, "
              f"{TIMEOUT_SECONDS}s/call, no retries or fallback. Provider usage may cost money.\n"
              "Only synthetic Diplomacy data is sent. The key is never printed.", flush=True)
        print("Thinking mode: explicitly disabled (enable_thinking=false)." if args.disable_thinking
              else "Thinking mode: provider default (enable_thinking omitted).", flush=True)
        if args.core_only:
            print("Core-only mode: intent, negotiation, and orders for each persona; seeded attitudes unchanged.", flush=True)
        persist_safe_result({"status": "awaiting_input", "calls": 0, **mode_report})
        if args.key_file:
            key = confirmed_key_file(Path(args.key_file))
        else:
            print("输入不会显示文字或星号，这是正常的。粘贴完成后直接按 Enter。\n"
                  "Linux 终端粘贴可用 Ctrl+Shift+V；Ctrl+C 取消。", flush=True)
            key = secure_key_prompt()
        persist_safe_result({"status": "running", "calls": 0, **mode_report})
        result = asyncio.run(run_smoke(key, disable_thinking=args.disable_thinking, core_only=args.core_only))
        persist_safe_result(result)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return 0 if result["status"] == "ok" else 1
    except KeyboardInterrupt:
        return fail("interrupted", "interrupted", 130)
    except SmokeFailure as exc:
        return fail("blocked", exc.code, 2)
    except Exception:
        return fail("failed", "internal_error", 1)
    finally:
        key = ""


if __name__ == "__main__":
    raise SystemExit(main())
