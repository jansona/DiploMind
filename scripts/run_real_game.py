#!/usr/bin/env python3
"""Single bounded real-provider test with an approved credential reference.

This runner never changes the ordinary app configuration or the mock server.
The 1901 cap is a TEST STOP, not an official Diplomacy outcome.
Diagnostics version 2 is offline-tested only; historical run reports are unchanged.
Chronicle prose is local, and AI retreat/build choices use the engine fallback.
Default: audited human Enter gate. --configured: previously authorized fixed
conf/aliyun.local.json binding; no interactive prompt and no credential output.
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
from pathlib import Path
import re
import sys
import tempfile
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
import httpx
from pydantic import ValidationError
from diplomind.config import Config
from diplomind.gateway import Gateway, _extract
from scripts import smoke_real_provider as smoke

BASE_URL, MODEL, KEY_FILE_PATH = smoke.BASE_URL, smoke.MODEL, smoke.KEY_FILE_PATH
MAX_CALLS, MAX_OUTPUT_TOKENS, WALL_SECONDS, CONCURRENCY = 50, 2048, 600, 2
REPORT_PATH = ROOT / 'artifacts' / 'real-game' / 'report.json'
CONFIG_PATH = ROOT / 'conf' / 'aliyun.local.json'
OPTIONS = {'enable_thinking': False, 'max_tokens': MAX_OUTPUT_TOKENS}
POWERS = frozenset({'AUSTRIA', 'ENGLAND', 'FRANCE', 'GERMANY', 'ITALY', 'RUSSIA', 'TURKEY'})


class DiagnosticFailure(smoke.SmokeFailure):
    CODES = smoke.SmokeFailure.CODES | {'json_invalid', 'http_client_error', 'http_server_error'}


def safe_actor(tag):
    prefix = tag.split(':', 1)[0] if type(tag) is str else ''
    return prefix if prefix in POWERS else 'unknown'


def response_error(status):
    if 300 <= status < 400: return 'redirect_refused'
    if status == 401: return 'authentication_failed'
    if status == 403: return 'access_denied'
    if status == 429: return 'rate_or_quota_limit'
    if 400 <= status < 500: return 'http_client_error'
    if 500 <= status < 600: return 'http_server_error'
    return 'invalid_response'


def safe_error(exc):
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)): return 'timeout'
    if isinstance(exc, httpx.HTTPError): return 'transport_error'
    if isinstance(exc, json.JSONDecodeError): return 'json_invalid'
    if isinstance(exc, ValidationError): return 'schema_invalid'
    if isinstance(exc, smoke.SmokeFailure): return exc.code
    if isinstance(exc, (ValueError, TypeError, AttributeError, IndexError)): return 'invalid_response'
    return 'internal_error'


def response_content(data):
    if not isinstance(data, dict): raise DiagnosticFailure('invalid_response')
    choices = data.get('choices')
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise DiagnosticFailure('invalid_response')
    choice = choices[0]
    if choice.get('finish_reason') == 'length': raise DiagnosticFailure('truncated_output')
    message = choice.get('message')
    if not isinstance(message, dict): raise DiagnosticFailure('invalid_response')
    content = message.get('content')
    if not isinstance(content, str) or not content: raise DiagnosticFailure('invalid_response')
    if len(content.encode('utf-8')) > smoke.MAX_RESPONSE_BYTES: raise DiagnosticFailure('response_limit')
    return content


def inspect_orders(session, actor, orders):
    """Observe the existing resolver; do not change what the engine receives."""
    agent = session.ai.get(actor)
    if agent is None: return {}
    flat = agent._legal_flat(session.eng)
    try: resolved = agent._resolve(orders, flat)
    except (ValueError, TypeError, IndexError): resolved = []
    expected = len(session.eng.legal_orders(actor))
    result = {'orders_submitted_count': len(orders), 'orders_resolved_count': len(resolved),
              'orders_expected_count': expected,
              'orders_rejected_count': max(0, len(orders)-len(resolved)),
              'orders_default_hold_count': max(0, expected-len(resolved))}
    if not orders and expected: result['error'] = 'no_orders'
    elif len(resolved) < len(orders): result['error'] = 'illegal_orders'
    return result



class Budget:
    """One process-wide counter, shared by every room and gateway."""
    def __init__(self, path=REPORT_PATH, clock=time.monotonic):
        self.path, self.clock = Path(path), clock
        self.started = self.deadline = self.deadline_unix = None
        self.calls = self.active = 0
        self.state, self.error, self.listening = 'awaiting_input', None, False
        self.records = []
        self.usage = dict(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        self.usage_reported_calls = 0
        self.phases = []
        self.gate = asyncio.Semaphore(CONCURRENCY)
        self.phase_check = lambda: True

    def start(self):
        self.started = self.clock()
        self.deadline = self.started + WALL_SECONDS
        self.deadline_unix = time.time() + WALL_SECONDS
        self.state = 'starting'
        self.persist()

    def remaining(self):
        return max(0., self.deadline - self.clock()) if self.deadline is not None else 0.

    def blocked(self):
        if self.started is None: return 'awaiting_input'
        if self.remaining() <= 0: return 'timeout'
        if not self.phase_check(): return 'year_cap'
        if self.calls >= MAX_CALLS: return 'call_budget'
        if self.state in {'test_stopped', 'failed', 'interrupted'}: return self.error or 'stopped'
        return None

    def reserve(self, schema, tag=''):
        reason = self.blocked()
        if reason: return None, reason
        self.calls += 1
        self.active += 1
        self.state = 'running'
        name = schema.__name__
        row = dict(call=self.calls, actor=safe_actor(tag), step=name if name in {'AttitudeUpdate','Intent','Message','OrderSet','Summary'} else 'unknown', status='running')
        self.records.append(row)
        self.persist()
        return row, None

    def country_health(self):
        result = {actor: dict(status='unverified', calls=0, successes=0, failures=0,
                             fallbacks=0, cancelled=0, last_error=None) for actor in sorted(POWERS)}
        for row in self.records:
            health = result.get(row.get('actor'))
            if health is None: continue
            health['calls'] += 1
            if row['status'] == 'running': health['status'] = 'running'
            elif row['status'] == 'ok':
                health['successes'] += 1
                health.update(status='ready', last_error=None)
            else:
                health['failures'] += 1
                health.update(status='degraded', last_error=row.get('error'))
            health['fallbacks'] += int(bool(row.get('fallback')))
            health['cancelled'] += int(row.get('error') == 'interrupted')
        return result

    def persist(self):
        report = dict(telemetry_schema_version=2, health_by_country=self.country_health(), state=self.state, error=self.error, ready=self.listening,
                      listening=self.listening, host='127.0.0.1', port=8732,
                      model=MODEL, provider='Aliyun', thinking_enabled=False,
                      calls=self.calls, remaining_calls=MAX_CALLS-self.calls,
                      active_requests=self.active, deadline_unix=self.deadline_unix,
                      remaining_seconds=round(self.remaining(), 3), usage=self.usage,
                      usage_reported_calls=self.usage_reported_calls,
                      limits=dict(calls=MAX_CALLS, output_tokens_per_call=MAX_OUTPUT_TOKENS,
                                  total_max_output_tokens=MAX_CALLS*MAX_OUTPUT_TOKENS,
                                  wall_seconds=WALL_SECONDS, concurrency=CONCURRENCY, retries=0),
                      phases=self.phases, call_reports=self.records,
                      outcome='TEST_STOP_ONLY_NOT_OFFICIAL_RESULT', max_year=1901,
                      chronicle='local_only', retreat_build_ai='engine_fallback',
                      updated_at_unix=round(time.time(), 3))
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile('w', dir=self.path.parent, delete=False) as out:
            name = out.name
            json.dump(report, out, ensure_ascii=False, indent=2)
        os.chmod(name, 0o600)
        os.replace(name, self.path)


class NullLog:
    def record(self, **fields): pass
    def stats(self): return {}


class BoundedGateway(Gateway):
    def __init__(self, key, budget, *, transport=None):
        # No normal Gateway clients/retry loops or credential-bearing log objects.
        self._key, self.budget = key, budget
        self.api, self.model = 'openai', MODEL
        self.temperature, self.think, self.constrain = .7, False, True
        self.request_options = dict(OPTIONS)
        self.timeout, self.concurrency, self.cli_enabled = 60., CONCURRENCY, False
        self._closed = False
        self.log = NullLog()
        self.order_inspector = None
        self.health = dict(status='unverified', calls=0, successes=0, failures=0, fallbacks=0, cancelled=0, last_error=None)
        self.aclient = httpx.AsyncClient(base_url=BASE_URL, trust_env=False, follow_redirects=False,
            timeout=60, transport=transport if transport is not None else smoke.runtime_transport())

    def chat(self, *args, **kwargs):
        # Real gameplay is async; never open an unbudgeted synchronous route.
        return None

    async def aclose(self):
        if not self._closed:
            self._closed = True
            await self.aclient.aclose()
        self._key = ''
        self.health['status'] = 'closed'

    def close(self):
        try: asyncio.get_running_loop().create_task(self.aclose())
        except RuntimeError: asyncio.run(self.aclose())

    async def achat(self, messages, schema, tag='', retry=0, temp=None):
        if self._closed or schema.__name__ == 'Summary': return None
        row = None
        started = self.budget.clock()
        self.health['calls'] += 1
        try:
            async with asyncio.timeout(max(.001, self.budget.remaining())):
                async with self.budget.gate:
                    if self._closed: return None
                    payload = self._body(messages, schema, temp)
                    # Final outbound override cannot be changed by config or caller.
                    payload.update(model=MODEL, enable_thinking=False, max_tokens=MAX_OUTPUT_TOKENS, stream=False)
                    payload.pop('reasoning_effort', None)
                    if len(json.dumps(payload).encode()) > smoke.MAX_INPUT_BYTES:
                        raise smoke.SmokeFailure('invalid_input')
                    row, reason = self.budget.reserve(schema, tag)
                    if reason:
                        self.health.update(status='stopped', last_error=reason)
                        return None
                    async with asyncio.timeout(min(60., self.budget.remaining())):
                        async with self.aclient.stream('POST', BASE_URL+'/chat/completions',
                                headers={'Authorization': 'Bearer '+self._key}, json=payload) as response:
                            row['http_status'] = response.status_code if 100 <= response.status_code <= 599 else 0
                            if response.status_code != 200:
                                raise DiagnosticFailure(response_error(response.status_code))
                            body = bytearray()
                            async for part in response.aiter_bytes():
                                body.extend(part)
                                if len(body) > smoke.MAX_RESPONSE_BYTES: raise smoke.SmokeFailure('response_limit')
                    data = json.loads(body)
                    if isinstance(data, dict) and isinstance(data.get('usage'), dict):
                        self.budget.usage_reported_calls += 1
                        for field in self.budget.usage:
                            value = data['usage'].get(field, 0)
                            if type(value) is int and 0 <= value <= 100_000_000:
                                self.budget.usage[field] += value
                    # Separate syntactic JSON failures from schema validation failures.
                    decoded = json.loads(_extract(response_content(data)))
                    out = schema.model_validate(decoded)
                    diagnostics = {}
                    if schema.__name__ == 'OrderSet':
                        if self.order_inspector:
                            diagnostics = self.order_inspector(row['actor'], out.orders)
                        elif not out.orders:
                            diagnostics = {'error': 'no_orders', 'orders_submitted_count': 0}
                    for field in ('orders_submitted_count', 'orders_resolved_count', 'orders_expected_count',
                                  'orders_rejected_count', 'orders_default_hold_count'):
                        value = diagnostics.get(field)
                        if type(value) is int and 0 <= value <= 1000: row[field] = value
                    error = diagnostics.get('error')
                    if error in {'no_orders', 'illegal_orders'}:
                        row.update(status='failed', error=error, fallback='engine_order_filter')
                        self._failure(error)
                        self.health['fallbacks'] += 1
                    else:
                        row['status'] = 'ok'
                        self._success()
                    # Preserve existing resolver/engine behavior even for partial orders.
                    return out
        except asyncio.CancelledError:
            if row: row.update(status='failed', error='interrupted')
            self.health['cancelled'] += 1
            raise
        except Exception as exc:
            error = safe_error(exc)
            if row: row.update(status='failed', error=error,
                               fallback='engine_hold' if row['step'] == 'OrderSet' else 'step_skipped')
            self._failure(error)
            self.health['fallbacks'] += 1
            return None
        finally:
            if row:
                row['latency_ms'] = round((self.budget.clock()-started)*1000)
                self.budget.active -= 1
                self.budget.persist()


def acquire_key(budget):
    """Reuse the audited TTY gate, starting the clock at Enter before file read."""
    original = smoke.read_private_key_file
    def after_enter(path):
        budget.start()
        return original(path)
    smoke.read_private_key_file = after_enter
    try: return smoke.confirmed_key_file(KEY_FILE_PATH)
    finally: smoke.read_private_key_file = original


def _resolve_key_reference():
    from diplomind.credentials import resolve_api_key
    return resolve_api_key(api='openai', api_key=None, api_key_file=str(KEY_FILE_PATH))


def acquire_configured_key(budget):
    """Consume only the exact, previously approved persistent app binding.

    The application's vetted reader resolves the key at runtime. This function
    neither prints the key nor writes it into app configuration or reports.
    """
    budget.start()  # This mode's wall clock starts at configured startup.
    if CONFIG_PATH.is_symlink() or CONFIG_PATH.stat().st_size > 16_384:
        raise smoke.SmokeFailure('invalid_input')
    data = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    required = {'api': 'openai', 'base_url': BASE_URL, 'model': MODEL,
                'api_key': None, 'api_key_file': str(KEY_FILE_PATH),
                'request_options': OPTIONS}
    if not isinstance(data, dict) or any(k not in data or data[k] != value for k, value in required.items()):
        raise smoke.SmokeFailure('wrong_destination')
    # No env/config fallback or arbitrary path/endpoint is accepted by this mode.
    return _resolve_key_reference()


def install_app(key, budget):
    from diplomind import config, session, rooms, web
    cfg = Config(api='openai', base_url=BASE_URL, model=MODEL, api_key=key,
                 rounds=2, concurrency=CONCURRENCY, timeout=60, max_year=1901,
                 game_mode='classic', end_rule='draw', request_options=dict(OPTIONS))
    class PinnedGateway(BoundedGateway):
        @classmethod
        def from_config(cls, ignored): return cls(key, budget)
    class PinnedSession(session.Session):
        def __init__(self, human='__cfg__', max_year=None, lang=None, personas=None, cfg=None, game_mode=None):
            humans = [human] if isinstance(human, str) else list(human or [])
            if len(humans) != 2: raise ValueError('This test requires exactly two human seats')
            super().__init__(human=human, max_year=1901, lang=lang, personas=personas,
                             cfg=config.load(), game_mode='classic')
            self.gw.order_inspector = lambda actor, orders: inspect_orders(self, actor, orders)
    class PinnedRoomManager(rooms.RoomManager):
        created = False
        def create(self, name, owner_name, power, lang='zh-Hans', passcode='', end_rule='', game_mode='classic', max_year=None):
            if self.created: raise ValueError('This bounded test allows one room only')
            result = super().create(name, owner_name, power, lang, passcode, 'draw', 'classic', 1901)
            self.created = True
            return result
        def join(self, code, power, name, token, passcode=''):
            room = self.rooms.get(code.strip().upper())
            if room and power and power not in room.humans() and len(room.humans()) >= 2:
                return None, 'seatunavailable'
            return super().join(code, power, name, token, passcode)
        def kick(self, code, power): return False
        def recover(self, token): return None
        def load(self, room, name='auto'): raise ValueError('Restore is disabled for this test')
    async def local_summary(gateway, year, public, centers, lang='zh-Hans'):
        return f'=== {year} ===\nLocal test chronicle; no model call. Centers: ' + ', '.join(
            f'{power}={count}' for power, count in sorted(centers.items()))
    session.summarize_year = local_summary
    config.load = session.load_config = web.load_config = lambda: cfg
    session.Gateway = PinnedGateway
    session.Session.SAVES = budget.path.parent / 'data' / 'saves'
    PinnedSession.SAVES = session.Session.SAVES
    rooms.Session = web.Session = PinnedSession
    web.RM = PinnedRoomManager()
    def phase_allowed():
        for room in web.RM.rooms.values():
            if room.session:
                match = re.search(r'\d{4}', room.session.eng.phase())
                if not match or int(match.group()) > 1901: return False
        return True
    budget.phase_check = phase_allowed
    return web


def stop_for_limit(budget, manager, server, reason):
    budget.error = reason
    if reason == 'call_budget':
        # Request 51 is already impossible. Let pending human orders and local
        # retreat/build adjudication finish 1901 rather than freezing before it.
        budget.state = 'network_stopped'
        return
    budget.state = 'test_stopped'
    for room in manager.rooms.values():
        if room.session: room.session.pause()
        if room.status == 'playing': room.status = 'paused'
    if reason == 'timeout': server.should_exit = True


async def serve(key, budget):
    import uvicorn
    web = install_app(key, budget)
    server = uvicorn.Server(uvicorn.Config(web.app, host='127.0.0.1', port=8732,
                             access_log=False, log_config=None, log_level='critical',
                             timeout_graceful_shutdown=3))
    async def watch():
        while not server.should_exit:
            budget.listening = bool(server.started)
            if budget.listening and budget.state == 'starting': budget.state = 'listening'
            budget.phases = [dict(phase=r.session.eng.phase(), mode=r.session.mode,
                                round=r.session.round, humans=len(r.session.humans), ai=len(r.session.ai))
                             for r in web.RM.rooms.values() if r.session]
            reason = budget.blocked()
            if reason and (reason == 'timeout' or not budget.active):
                stop_for_limit(budget, web.RM, server, reason)
            budget.persist()
            await asyncio.sleep(.1)
    watcher = asyncio.create_task(watch())
    # A diagnostic/watchdog failure must stop serving, never silently lose the deadline.
    watcher.add_done_callback(lambda task: setattr(server, 'should_exit', True)
        if not task.cancelled() and task.exception() is not None else None)
    try: await server.serve()
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
        budget.listening = False
        if budget.state != 'test_stopped': budget.state = 'interrupted'
        budget.persist()


def disable_core_dumps():
    """Fail closed before credential acquisition if process dumps cannot be blocked."""
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if resource.getrlimit(resource.RLIMIT_CORE) != (0, 0):
        raise RuntimeError('unsafe_runtime')


def main(argv=None):
    budget = Budget()
    key = ''
    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        args = sys.argv[1:] if argv is None else argv
        if args not in ([], ['--configured']): raise smoke.SmokeFailure('invalid_input')
        configured = args == ['--configured']
        disable_core_dumps()
        budget.persist()
        print('REAL GAME TEST: 50 total HTTP calls, 2048 output tokens/call, no retries, concurrency 2.\n'
              'Input tokens are extra. Non-thinking mode. 600-second wall limit.\n'
              'Two human seats + five Aliyun AI; 1901 TEST STOP, no official outcome.\n'
              'Server: http://127.0.0.1:8732', flush=True)
        key = acquire_configured_key(budget) if configured else acquire_key(budget)
        asyncio.run(serve(key, budget))
        return 0
    except KeyboardInterrupt:
        budget.state, budget.error = 'interrupted', 'interrupted'
        return 130
    except Exception as exc:
        budget.state = 'failed'
        budget.error = exc.code if isinstance(exc, smoke.SmokeFailure) else 'internal_error'
        return 1
    finally:
        key = ''
        budget.listening = False
        try: budget.persist()
        except Exception: pass  # Diagnostics must never print raw exceptions.
        logging.disable(previous_logging)


if __name__ == '__main__': raise SystemExit(main())
