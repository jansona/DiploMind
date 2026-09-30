"""Offline-only verification of the explicitly authorized bounded smoke runner."""
import asyncio
import io
import json

import httpx
import pytest

from scripts.smoke_real_provider import (BASE_URL, MODEL, MAX_CALLS, MAX_OUTPUT_TOKENS,
    SmokeFailure, SmokeGateway, main, run_smoke, secure_key_prompt)
from diplomind.providers.mock import MockProvider, context_from
from diplomind.schemas import AttitudeUpdate, Intent, Message, OrderSet

FAKE_KEY = 'synthetic-test-only-never-a-real-key'


@pytest.fixture(autouse=True)
def isolated_result_path(tmp_path, monkeypatch):
    import scripts.smoke_real_provider as smoke
    monkeypatch.setattr(smoke, 'RESULT_PATH', tmp_path / 'report' / 'safe.json')


def local_endpoint(seen):
    mock = MockProvider()
    schemas = {c.__name__:c for c in (AttitudeUpdate,Intent,Message,OrderSet)}
    def handler(request):
        payload=json.loads(request.content)
        seen.append((request,payload))
        contract=json.loads(payload['messages'][-1]['content'].split('brief. ',1)[1])
        schema=schemas[contract['title']]
        content=json.dumps(mock.complete(payload['messages'],schema),ensure_ascii=False)
        return httpx.Response(200,json={'choices':[{'message':{'content':content},'finish_reason':'stop'}],
                                       'usage':{'prompt_tokens':100,'completion_tokens':30,'total_tokens':130}})
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_fake_local_endpoint_eight_calls_caps_provenance_and_legality(tmp_path,monkeypatch):
    seen=[]
    # No application log/save output can be created by the smoke's provider.
    monkeypatch.chdir(tmp_path)
    report=await run_smoke(FAKE_KEY,transport=local_endpoint(seen))
    assert report['status']=='ok', report
    assert report['calls']==len(seen)==MAX_CALLS
    assert report['usage']=={'prompt_tokens':800,'completion_tokens':240,'total_tokens':1040}
    assert report['usage_reported_calls']==8
    assert len(report['scenarios'])==2
    assert all(s['final_round_in_order_context'] and s['legal_orders']==3 for s in report['scenarios'])
    assert not list(tmp_path.iterdir())
    for request,payload in seen:
        assert str(request.url)==BASE_URL+'/chat/completions'
        assert request.headers['authorization']=='Bearer '+FAKE_KEY
        assert payload['model']==MODEL and payload['max_tokens']==MAX_OUTPUT_TOKENS
        assert FAKE_KEY not in request.content.decode()
        assert 'INVISIBLE_SMOKE_CONTROL' not in request.content.decode()
        ctx=context_from(payload['messages'])
        assert any(e['kind']=='reported_claim' and not e['verified'] for e in ctx['visible_evidence'])
    order_calls=[payload for _,payload in seen if 'OrderSet' in payload['messages'][-1]['content']]
    assert all('Final confirmation' in p['messages'][1]['content'] for p in order_calls)
    assert FAKE_KEY not in json.dumps(report)
    assert 'unverified third-party accusation' not in json.dumps(report)  # no prompt/body output


@pytest.mark.asyncio
@pytest.mark.parametrize('status,code',[(301,'redirect_refused'),(401,'authentication_failed'),
                                        (403,'access_denied'),(429,'rate_or_quota_limit'),(500,'provider_error')])
async def test_errors_stop_without_retry_or_secret_error_body(status,code):
    calls=[]
    def fail(request):
        calls.append(request)
        return httpx.Response(status,json={'error':{'message':FAKE_KEY}},headers={'location':'https://evil.invalid'})
    report=await run_smoke(FAKE_KEY,transport=httpx.MockTransport(fail))
    assert report['error']==code and report['calls']==len(calls)==1
    assert FAKE_KEY not in json.dumps(report) and 'evil.invalid' not in json.dumps(report)


@pytest.mark.asyncio
async def test_hard_call_budget_even_when_agent_requests_retries():
    seen=[];gw=SmokeGateway(FAKE_KEY,transport=local_endpoint(seen))
    for _ in range(MAX_CALLS):
        await gw.achat([{'role':'user','content':'test'}],Intent,retry=999)
    with pytest.raises(SmokeFailure,match='call_budget'):
        await gw.achat([],Intent)
    assert len(seen)==8
    await gw.aclose();assert gw._key==''


@pytest.mark.asyncio
async def test_invalid_json_and_truncation_stop_immediately():
    for choice,code in [({'message':{'content':'not JSON'}},'schema_invalid'),
                        ({'message':{'content':'{}'},'finish_reason':'length'},'truncated_output')]:
        report=await run_smoke(FAKE_KEY,transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'choices':[choice]})))
        assert report['calls']==1 and report['error']==code


@pytest.mark.asyncio
async def test_transport_timeout_and_exception_are_redacted(monkeypatch):
    async def fail(request): raise httpx.ConnectError(FAKE_KEY)
    report=await run_smoke(FAKE_KEY,transport=httpx.MockTransport(fail))
    assert report['error']=='transport_error' and FAKE_KEY not in json.dumps(report)
    import scripts.smoke_real_provider as smoke
    monkeypatch.setattr(smoke,'TIMEOUT_SECONDS',.01)
    async def stall(request): await asyncio.sleep(1)
    report=await run_smoke(FAKE_KEY,transport=httpx.MockTransport(stall))
    assert report['error']=='timeout' and report['calls']==1


def test_non_tty_fails_before_getpass_or_request(monkeypatch,capsys):
    import scripts.smoke_real_provider as smoke
    monkeypatch.setattr(smoke.sys,'stdin',io.StringIO(FAKE_KEY))
    monkeypatch.setattr(smoke.getpass,'getpass',lambda *a,**k:pytest.fail('getpass must not run'))
    assert main([])==2
    captured=capsys.readouterr()
    assert 'unsafe_terminal' in captured.err and FAKE_KEY not in captured.out+captured.err


def test_no_echo_fallback_on_getpass_warning(monkeypatch):
    import scripts.smoke_real_provider as smoke
    class TTY(io.StringIO):
        def isatty(self): return True
    for stream in ('stdin','stdout','stderr'): monkeypatch.setattr(smoke.sys,stream,TTY())
    def insecure(*a,**k):
        import warnings
        warnings.warn('Cannot control echo',smoke.getpass.GetPassWarning)
        pytest.fail('echo fallback was allowed')
    monkeypatch.setattr(smoke.getpass,'getpass',insecure)
    with pytest.raises(SmokeFailure,match='unsafe_terminal'):secure_key_prompt()


def test_destination_and_model_are_pinned():
    with pytest.raises(SmokeFailure,match='wrong_destination'):SmokeGateway(FAKE_KEY,base_url='https://evil.invalid')
    with pytest.raises(SmokeFailure,match='wrong_destination'):SmokeGateway(FAKE_KEY,model='some-other-model')
    assert main(['--base-url','https://evil.invalid']) == 2


def test_runtime_https_proxy_is_explicit_and_not_logged(monkeypatch,capsys):
    import scripts.smoke_real_provider as smoke
    calls=[]
    def construct(**kwargs): calls.append(kwargs);return object()
    monkeypatch.setattr(smoke.httpx,'AsyncHTTPTransport',construct)
    monkeypatch.setenv('HTTPS_PROXY','http://synthetic-user:synthetic-proxy-password@proxy.invalid:8080')
    monkeypatch.setenv('ALL_PROXY','socks5://must-not-be-used.invalid:1080')
    smoke.runtime_transport()
    assert calls[0]['proxy']=='http://synthetic-user:synthetic-proxy-password@proxy.invalid:8080'
    assert calls[0]['trust_env'] is True and calls[0]['retries']==0
    monkeypatch.delenv('HTTPS_PROXY')
    monkeypatch.setenv('https_proxy','http://lowercase.invalid:8080')
    smoke.runtime_transport();assert calls[1]['proxy']=='http://lowercase.invalid:8080'
    monkeypatch.delenv('https_proxy');smoke.runtime_transport();assert calls[2]['proxy'] is None
    captured=capsys.readouterr()
    assert 'synthetic-proxy-password' not in captured.out+captured.err


def test_saved_diagnostic_result_is_allowlisted_and_private(tmp_path):
    import stat
    from scripts.smoke_real_provider import persist_safe_result
    path=tmp_path/'safe-result.json'
    report={'status':'failed','error':'schema_invalid','calls':1,'key':FAKE_KEY,
            'usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120},
            'scenarios':[{'model_text':FAKE_KEY,'orders':[FAKE_KEY]}],
            'call_reports':[{'call':1,'step':'Intent','status':'failed','error':'schema_invalid','raw':FAKE_KEY}]}
    persist_safe_result(report,path)
    text=path.read_text();assert FAKE_KEY not in text
    result=json.loads(text);assert result['calls']==1 and result['error']=='schema_invalid'
    assert result['scenarios_completed']==1
    assert stat.S_IMODE(path.stat().st_mode)==0o600
    assert 'key' not in result and 'orders' not in text and 'model_text' not in text


@pytest.fixture
def private_key(tmp_path, monkeypatch):
    import scripts.smoke_real_provider as smoke
    directory = tmp_path / 'private'
    directory.mkdir(mode=0o700)
    path = directory / 'api-key.txt'
    path.write_text(FAKE_KEY)
    path.chmod(0o600)
    monkeypatch.setattr(smoke, 'KEY_FILE_PATH', path)
    return path


def test_secure_file_retained_and_end_whitespace_stripped(private_key):
    import scripts.smoke_real_provider as smoke
    private_key.write_text('  ' + FAKE_KEY + '\n')
    assert smoke.read_private_key_file(private_key) == FAKE_KEY
    assert private_key.read_text() == '  ' + FAKE_KEY + '\n'


@pytest.mark.parametrize('contents,code', [('', 'empty_key'), (' \n', 'empty_key'),
    ('two keys', 'invalid_key'), ('bad\x00key', 'invalid_key'), ('非ASCII', 'invalid_key'),
    ('x' * 8193, 'unsafe_key_file')])
def test_invalid_file_contents(private_key, contents, code):
    import scripts.smoke_real_provider as smoke
    private_key.write_text(contents)
    with pytest.raises(SmokeFailure, match=code):
        smoke.read_private_key_file(private_key)


@pytest.mark.parametrize('target,mode', [('file', 0o644), ('file', 0o400), ('parent', 0o755)])
def test_private_permissions_required(private_key, target, mode):
    import scripts.smoke_real_provider as smoke
    (private_key if target == 'file' else private_key.parent).chmod(mode)
    with pytest.raises(SmokeFailure, match='unsafe_key_file'):
        smoke.read_private_key_file(private_key)


def test_symlink_and_hardlink_refused(private_key):
    import os
    import scripts.smoke_real_provider as smoke
    other = private_key.with_name('other')
    private_key.rename(other)
    private_key.symlink_to(other)
    with pytest.raises(SmokeFailure, match='unsafe_key_file'):
        smoke.read_private_key_file(private_key)
    private_key.unlink()
    os.link(other, private_key)
    with pytest.raises(SmokeFailure, match='unsafe_key_file'):
        smoke.read_private_key_file(private_key)


def fake_tty(monkeypatch):
    import scripts.smoke_real_provider as smoke
    class TTY(io.StringIO):
        def isatty(self): return True
    streams = [TTY(), TTY(), TTY()]
    for name, stream in zip(('stdin', 'stdout', 'stderr'), streams):
        monkeypatch.setattr(smoke.sys, name, stream)
    return streams


def test_confirmation_precedes_any_file_open(private_key, monkeypatch):
    import scripts.smoke_real_provider as smoke
    fake_tty(monkeypatch)
    events = []
    monkeypatch.setattr(smoke.getpass, 'getpass', lambda *a, **k: events.append('enter') or '')
    original = smoke.os.open
    def track_open(*args, **kwargs):
        assert events == ['enter']
        return original(*args, **kwargs)
    monkeypatch.setattr(smoke.os, 'open', track_open)
    assert smoke.confirmed_key_file(private_key) == FAKE_KEY


def test_cancel_prevents_file_read(private_key, monkeypatch):
    import scripts.smoke_real_provider as smoke
    fake_tty(monkeypatch)
    def cancel(*a, **k): raise KeyboardInterrupt()
    monkeypatch.setattr(smoke.getpass, 'getpass', cancel)
    monkeypatch.setattr(smoke, 'read_private_key_file', lambda path: pytest.fail('read before Enter'))
    assert main(['--key-file', str(private_key)]) == 130
    assert json.loads(smoke.RESULT_PATH.read_text())['status'] == 'interrupted'


def test_main_file_flow_statuses_and_no_key_output(private_key, monkeypatch):
    import scripts.smoke_real_provider as smoke
    streams = fake_tty(monkeypatch)
    states = []
    save = smoke.persist_safe_result
    def capture(report):
        states.append(report['status'])
        save(report)
    monkeypatch.setattr(smoke, 'persist_safe_result', capture)
    monkeypatch.setattr(smoke.getpass, 'getpass', lambda *a, **k: '')
    async def offline(key, **kwargs):
        assert key == FAKE_KEY
        return {'status': 'ok', 'calls': 0}
    monkeypatch.setattr(smoke, 'run_smoke', offline)
    assert main(['--key-file', str(private_key)]) == 0
    assert states == ['awaiting_input', 'running', 'ok']
    assert FAKE_KEY not in ''.join(stream.getvalue() for stream in streams)


def test_main_failures_are_sanitized_and_persisted(private_key, monkeypatch):
    import scripts.smoke_real_provider as smoke
    streams = fake_tty(monkeypatch)
    monkeypatch.setattr(smoke.getpass, 'getpass', lambda *a, **k: '')
    def failure(path): raise RuntimeError(FAKE_KEY)
    monkeypatch.setattr(smoke, 'read_private_key_file', failure)
    assert main(['--key-file', str(private_key)]) == 1
    assert json.loads(smoke.RESULT_PATH.read_text())['error'] == 'internal_error'
    assert FAKE_KEY not in ''.join(stream.getvalue() for stream in streams)
    assert main(['--key-file', FAKE_KEY]) == 2
    assert json.loads(smoke.RESULT_PATH.read_text())['error'] == 'invalid_input'
    assert FAKE_KEY not in ''.join(stream.getvalue() for stream in streams)


def test_file_confirmation_hides_and_rejects_accidental_key(private_key, monkeypatch):
    import scripts.smoke_real_provider as smoke
    streams = fake_tty(monkeypatch)
    monkeypatch.setattr(smoke.getpass, 'getpass', lambda *a, **k: FAKE_KEY)
    monkeypatch.setattr(smoke, 'read_private_key_file', lambda path: pytest.fail('read without empty Enter'))
    assert main(['--key-file', str(private_key)]) == 2
    assert json.loads(smoke.RESULT_PATH.read_text())['error'] == 'invalid_input'
    assert FAKE_KEY not in ''.join(stream.getvalue() for stream in streams)


def test_file_confirmation_no_echo_fallback(private_key, monkeypatch):
    import warnings
    import scripts.smoke_real_provider as smoke
    fake_tty(monkeypatch)
    def insecure(*a, **k):
        warnings.warn('Cannot control echo', smoke.getpass.GetPassWarning)
        pytest.fail('echo fallback was allowed')
    monkeypatch.setattr(smoke.getpass, 'getpass', insecure)
    monkeypatch.setattr(smoke, 'read_private_key_file', lambda path: pytest.fail('read before confirmation'))
    assert main(['--key-file', str(private_key)]) == 2
    assert json.loads(smoke.RESULT_PATH.read_text())['error'] == 'unsafe_terminal'


@pytest.mark.asyncio
@pytest.mark.parametrize('disable_thinking,core_only,expected_calls', [
    (False, False, 8), (True, False, 8), (True, True, 6), (False, True, 6)])
async def test_explicit_thinking_and_core_modes(disable_thinking, core_only, expected_calls):
    import scripts.smoke_real_provider as smoke
    seen = []
    report = await run_smoke(FAKE_KEY, transport=local_endpoint(seen),
                             disable_thinking=disable_thinking, core_only=core_only)
    assert report['status'] == 'ok', report
    assert report['calls'] == len(seen) == expected_calls
    assert report['limits'] == {'calls': expected_calls, 'output_tokens_per_call': 700,
                                'timeout_seconds': 30, 'retries': 0}
    assert report['thinking_enabled'] is (False if disable_thinking else None)
    assert report['core_only'] is core_only
    expected = ['Intent', 'Message', 'OrderSet'] if core_only else ['AttitudeUpdate', 'Intent', 'Message', 'OrderSet']
    assert [call['step'] for call in report['call_reports']] == expected * 2
    constraints = {'AttitudeUpdate': '12 words per attitude', 'Intent': '24 words for goal',
                   'Message': '80 words for content', 'OrderSet': '40 words for reasoning'}
    for (_, payload), call in zip(seen, report['call_reports']):
        if disable_thinking:
            assert payload['enable_thinking'] is False
        else:
            assert 'enable_thinking' not in payload
        assert constraints[call['step']] in payload['messages'][-1]['content']
    smoke.persist_safe_result(report)
    saved = json.loads(smoke.RESULT_PATH.read_text())
    assert saved['limits']['calls'] == expected_calls
    assert saved['thinking_enabled'] is report['thinking_enabled']
    assert FAKE_KEY not in json.dumps(saved)


@pytest.mark.asyncio
async def test_core_mode_hard_six_call_budget():
    seen = []
    gateway = SmokeGateway(FAKE_KEY, transport=local_endpoint(seen), core_only=True, disable_thinking=True)
    try:
        for _ in range(6):
            await gateway.achat([{'role': 'user', 'content': 'test'}], Intent, retry=99)
        with pytest.raises(SmokeFailure, match='call_budget'):
            await gateway.achat([], Intent)
        assert len(seen) == 6
    finally:
        await gateway.aclose()


def test_main_threads_explicit_core_thinking_flags(private_key, monkeypatch):
    import scripts.smoke_real_provider as smoke
    streams = fake_tty(monkeypatch)
    monkeypatch.setattr(smoke.getpass, 'getpass', lambda *a, **k: '')
    async def offline(key, *, disable_thinking, core_only):
        assert key == FAKE_KEY and disable_thinking is True and core_only is True
        saved = json.loads(smoke.RESULT_PATH.read_text())
        assert saved['status'] == 'running' and saved['thinking_enabled'] is False
        assert saved['limits']['calls'] == 6
        return {'status': 'ok', 'calls': 0, 'thinking_enabled': False, 'core_only': True}
    monkeypatch.setattr(smoke, 'run_smoke', offline)
    assert main(['--key-file', str(private_key), '--disable-thinking', '--core-only']) == 0
    output = ''.join(stream.getvalue() for stream in streams)
    assert '6 calls total' in output and 'enable_thinking=false' in output
    assert 'Core-only mode' in output and FAKE_KEY not in output
