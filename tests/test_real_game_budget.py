"""Offline transports and synthetic keys only; never inspect a user's file."""
import asyncio
import json
import httpx
import pytest
from pydantic import BaseModel
from scripts import run_real_game as real

class Result(BaseModel):
    value: int

@pytest.mark.asyncio
async def test_fifty_total_failures_count_no_retry_and_pinned_route(tmp_path):
    seen=[]
    def handler(req):
        seen.append(req)
        return httpx.Response(503, text='secret provider body')
    budget=real.Budget(tmp_path/'r.json'); budget.start()
    g1=real.BoundedGateway('synthetic', budget, transport=httpx.MockTransport(handler))
    g2=real.BoundedGateway('synthetic', budget, transport=httpx.MockTransport(handler))
    for i in range(51):
        assert await (g1 if i%2 else g2).achat([{'role':'user','content':'synthetic'}],Result,retry=99) is None
    assert len(seen)==budget.calls==50
    assert all(str(req.url)==real.BASE_URL+'/chat/completions' for req in seen)
    for req in seen:
        data=json.loads(req.content)
        assert data['model']==real.MODEL and data['max_tokens']==2048
        assert data['enable_thinking'] is False
    report=(tmp_path/'r.json').read_text()
    assert 'secret provider body' not in report and 'synthetic' not in report
    await g1.aclose(); await g2.aclose()

@pytest.mark.asyncio
async def test_deadline_and_year_cap_prevent_requests(tmp_path):
    now=[0.]
    budget=real.Budget(tmp_path/'r.json',clock=lambda:now[0]); budget.start()
    def forbidden(req): raise AssertionError('network must not start')
    gw=real.BoundedGateway('synthetic',budget,transport=httpx.MockTransport(forbidden))
    now[0]=601
    assert await gw.achat([],Result) is None
    assert budget.calls==0
    now[0]=1; budget.phase_check=lambda:False
    assert await gw.achat([],Result) is None
    assert budget.calls==0
    await gw.aclose()

@pytest.mark.asyncio
async def test_concurrency_and_timeout_cancellation(tmp_path):
    active=maximum=0
    async def handler(req):
        nonlocal active,maximum
        active+=1; maximum=max(maximum,active)
        try:
            await asyncio.sleep(.025)
            return httpx.Response(200,json={'choices':[{'message':{'content':'{"value":1}'}}]})
        finally: active-=1
    b=real.Budget(tmp_path/'r.json'); b.start()
    gw=real.BoundedGateway('synthetic',b,transport=httpx.MockTransport(handler))
    values=await asyncio.gather(*(gw.achat([],Result,retry=10) for _ in range(6)))
    assert maximum==2 and all(v.value==1 for v in values)
    before=b.calls
    b.deadline=b.clock()+.001
    assert await gw.achat([],Result) is None
    assert active==0 and b.active==0
    # Expiry before reservation is equally valid: no HTTP attempt was admitted.
    assert b.calls in (before,before+1)
    if b.calls > before: assert b.records[-1]['error']=='timeout'
    await gw.aclose()


def test_gate_reuses_confirmed_reader_clock_before_file(monkeypatch,tmp_path):
    b=real.Budget(tmp_path/'r.json'); events=[]
    def fake_read(path):
        assert path==real.KEY_FILE_PATH and b.started is not None
        events.append('read'); return 'synthetic'
    def fake_confirm(path):
        assert b.started is None
        events.append('human_enter')
        return real.smoke.read_private_key_file(path)
    monkeypatch.setattr(real.smoke,'read_private_key_file',fake_read)
    monkeypatch.setattr(real.smoke,'confirmed_key_file',fake_confirm)
    assert real.acquire_key(b)=='synthetic'
    assert events==['human_enter','read']
    assert real.smoke.read_private_key_file is fake_read


def test_cli_rejects_arbitrary_args_without_gate(monkeypatch,tmp_path):
    budget=real.Budget(tmp_path/'r.json')
    monkeypatch.setattr(real,'Budget',lambda: budget)
    monkeypatch.setattr(real,'acquire_key',lambda _: pytest.fail('gate must not run'))
    assert real.main(['--endpoint','https://example.invalid'])==1
    assert budget.error=='invalid_input' and budget.calls==0

@pytest.mark.asyncio
async def test_pinned_app_config_local_summary_and_no_credential_persistence(monkeypatch,tmp_path):
    from diplomind import config,session,rooms,web
    # Register restorations before the runner's deliberately process-local injection.
    for module,name in ((config,'load'),(session,'load_config'),(web,'load_config'),
                        (session,'Gateway'),(session,'summarize_year'),(rooms,'Session'),
                        (web,'Session'),(web,'RM')):
        monkeypatch.setattr(module,name,getattr(module,name))
    monkeypatch.setattr(session.Session,'SAVES',session.Session.SAVES)
    monkeypatch.setattr(real.smoke,'runtime_transport',lambda:httpx.MockTransport(
        lambda req: pytest.fail('integration test must not call any endpoint')))
    b=real.Budget(tmp_path/'r.json'); b.start()
    app=real.install_app('synthetic-test-key',b)
    room=app.RM.create('Synthetic room','Host','FRANCE',max_year=1920,game_mode='plus',end_rule='topcount')
    assert room.max_year==1901 and room.game_mode=='classic' and room.end_rule=='draw'
    with pytest.raises(ValueError): room.start()
    joined,_=app.RM.join(room.code,'GERMANY','Second',None)
    joined.start()
    s=joined.session
    assert s.rounds==2 and len(s.ai)==5 and len(s.humans)==2
    assert s.gw.request_options==real.OPTIONS and s.gw.model==real.MODEL
    text=await session.summarize_year(s.gw,'S1902M',[],s.eng.centers())
    assert 'Local test chronicle' in text and b.calls==0
    app.RM.checkpoint(joined)
    for file in tmp_path.rglob('*.json'):
        assert 'synthetic-test-key' not in file.read_text()
    monkeypatch.setattr(s.eng,'phase',lambda:'S1902M')
    assert not b.phase_check()
    assert await s.gw.achat([],Result) is None and b.calls==0
    await s.aclose()


def test_limit_stop_allows_final_local_orders_but_deadline_pauses(tmp_path):
    from types import SimpleNamespace
    paused=[]
    room=SimpleNamespace(status='playing',session=SimpleNamespace(pause=lambda:paused.append(True)))
    manager=SimpleNamespace(rooms={'synthetic':room})
    server=SimpleNamespace(should_exit=False)
    b=real.Budget(tmp_path/'r.json'); b.start(); b.calls=50
    real.stop_for_limit(b,manager,server,'call_budget')
    assert b.blocked()=='call_budget' and room.status=='playing'
    assert not paused and not server.should_exit and b.state=='network_stopped'
    real.stop_for_limit(b,manager,server,'timeout')
    assert paused==[True] and room.status=='paused' and server.should_exit


def write_binding(path,**overrides):
    data={'api':'openai','base_url':real.BASE_URL,'model':real.MODEL,
          'api_key':None,'api_key_file':str(real.KEY_FILE_PATH),'request_options':dict(real.OPTIONS)}
    data.update(overrides); path.write_text(json.dumps(data)); return path


def test_configured_binding_no_prompt_vetted_reader_only(monkeypatch,tmp_path):
    path=write_binding(tmp_path/'binding.json')
    monkeypatch.setattr(real,'CONFIG_PATH',path)
    budget=real.Budget(tmp_path/'r.json')
    def fake_resolve():
        assert budget.started is not None
        return 'synthetic'
    monkeypatch.setattr(real,'_resolve_key_reference',fake_resolve)
    monkeypatch.setattr(real,'acquire_key',lambda _:pytest.fail('configured mode must not prompt'))
    assert real.acquire_configured_key(budget)=='synthetic'
    assert 599 < budget.remaining() <= 600


@pytest.mark.parametrize('changes',[
    {'api':'mock'}, {'base_url':'https://example.invalid'}, {'model':'other'},
    {'api_key':'plaintext-rejected'}, {'api_key_file':'/tmp/elsewhere'},
    {'request_options':{'enable_thinking':True,'max_tokens':2048}},
])
def test_configured_binding_rejects_drift_before_key_resolve(monkeypatch,tmp_path,changes):
    monkeypatch.setattr(real,'CONFIG_PATH',write_binding(tmp_path/'binding.json',**changes))
    monkeypatch.setattr(real,'_resolve_key_reference',lambda:pytest.fail('must not resolve key'))
    with pytest.raises(real.smoke.SmokeFailure):
        real.acquire_configured_key(real.Budget(tmp_path/'r.json'))


def test_configured_main_never_calls_manual_gate(monkeypatch,tmp_path):
    b=real.Budget(tmp_path/'r.json')
    monkeypatch.setattr(real,'Budget',lambda:b)
    monkeypatch.setattr(real,'CONFIG_PATH',write_binding(tmp_path/'binding.json'))
    monkeypatch.setattr(real,'_resolve_key_reference',lambda:'synthetic')
    monkeypatch.setattr(real,'acquire_key',lambda _:pytest.fail('no prompt'))
    async def fake_serve(key,budget):
        assert key=='synthetic' and budget.started is not None
    monkeypatch.setattr(real,'serve',fake_serve)
    assert real.main(['--configured'])==0

@pytest.mark.asyncio
async def test_server_is_loopback_and_shutdown_sse_is_bounded(monkeypatch,tmp_path):
    from types import SimpleNamespace
    import uvicorn
    seen={}
    monkeypatch.setattr(real,'install_app',lambda key,budget:SimpleNamespace(app=object(),RM=SimpleNamespace(rooms={})))
    def fake_config(app,**kwargs): seen.update(kwargs); return object()
    class FakeServer:
        def __init__(self,config): self.should_exit=False; self.started=False
        async def serve(self): self.should_exit=True
    monkeypatch.setattr(uvicorn,'Config',fake_config)
    monkeypatch.setattr(uvicorn,'Server',FakeServer)
    b=real.Budget(tmp_path/'r.json'); b.start()
    await real.serve('synthetic',b)
    assert seen['host']=='127.0.0.1' and seen['port']==8732
    assert seen['timeout_graceful_shutdown']==3
    assert seen['access_log'] is False
    assert 'reload' not in seen and b.calls==0


def test_core_dump_failure_blocks_before_any_key_read(monkeypatch,tmp_path):
    b=real.Budget(tmp_path/'r.json')
    monkeypatch.setattr(real,'Budget',lambda:b)
    def blocked(): raise OSError('synthetic failure; must never be printed')
    monkeypatch.setattr(real,'disable_core_dumps',blocked)
    monkeypatch.setattr(real,'acquire_key',lambda _:pytest.fail('must not read a key'))
    monkeypatch.setattr(real,'acquire_configured_key',lambda _:pytest.fail('must not read a key'))
    assert real.main(['--configured'])==1
    assert b.calls==0 and b.state=='failed' and b.error=='internal_error'
    assert b.started is None


def test_core_dump_limit_is_verified(monkeypatch):
    import resource
    seen=[]
    monkeypatch.setattr(resource,'setrlimit',lambda which,limits:seen.append((which,limits)))
    monkeypatch.setattr(resource,'getrlimit',lambda which:(0,0))
    real.disable_core_dumps()
    assert seen==[(resource.RLIMIT_CORE,(0,0))]
    monkeypatch.setattr(resource,'getrlimit',lambda which:(1,1))
    with pytest.raises(RuntimeError,match='unsafe_runtime'): real.disable_core_dumps()


@pytest.mark.asyncio
@pytest.mark.parametrize('status,expected',[
    (302,'redirect_refused'), (400,'http_client_error'), (401,'authentication_failed'),
    (403,'access_denied'), (429,'rate_or_quota_limit'), (503,'http_server_error'),
])
async def test_http_diagnostics_are_safe_and_distinct(tmp_path,status,expected):
    secret='SYNTHETIC_SECRET_BODY_DO_NOT_SAVE'
    budget=real.Budget(tmp_path/'r.json'); budget.start()
    gw=real.BoundedGateway('synthetic',budget,transport=httpx.MockTransport(
        lambda req:httpx.Response(status,text=secret)))
    assert await gw.achat([],Result,tag='RUSSIA:order:'+secret) is None
    row=budget.records[-1]
    assert row['actor']=='RUSSIA' and row['error']==expected and row['http_status']==status
    assert budget.country_health()['RUSSIA']['fallbacks']==1
    assert secret not in (tmp_path/'r.json').read_text()
    await gw.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,expected',[
    ('transport','transport_error'), ('timeout','timeout'), ('envelope_json','json_invalid'),
    ('content_json','json_invalid'), ('schema','schema_invalid'), ('truncated','truncated_output'),
    ('envelope_shape','invalid_response'), ('oversize','response_limit'), ('unexpected','internal_error'),
])
async def test_error_diagnostic_classes_never_expose_provider_text(tmp_path,kind,expected):
    secret='SYNTHETIC_SECRET_DO_NOT_SAVE'
    def handler(req):
        if kind=='transport': raise httpx.ConnectError(secret,request=req)
        if kind=='timeout': raise httpx.ReadTimeout(secret,request=req)
        if kind=='unexpected': raise RuntimeError(secret)
        if kind=='envelope_json': return httpx.Response(200,text=secret)
        if kind=='oversize': return httpx.Response(200,text=secret*(real.smoke.MAX_RESPONSE_BYTES//len(secret)+1))
        if kind=='envelope_shape': return httpx.Response(200,json={'body':secret})
        content=secret if kind=='content_json' else json.dumps({'value':secret})
        return httpx.Response(200,json={'choices':[{'message':{'content':content},
                                   'finish_reason':'length' if kind=='truncated' else 'stop'}]})
    budget=real.Budget(tmp_path/'r.json'); budget.start()
    gw=real.BoundedGateway('synthetic',budget,transport=httpx.MockTransport(handler))
    assert await gw.achat([],Result,tag=secret+':order') is None
    row=budget.records[-1]
    assert row['error']==expected and row['actor']=='unknown'
    assert secret not in (tmp_path/'r.json').read_text()
    assert sum(v['calls'] for v in budget.country_health().values())==0
    await gw.aclose()


@pytest.mark.parametrize('tag,actor',[
    ('RUSSIA:order','RUSSIA'),('RUSSIA:order:SECRET','RUSSIA'),
    ('RUSSIA\nSECRET:order','unknown'),('SECRET:RUSSIA','unknown'),
    ('RUSSIA?token=SECRET','unknown'),(None,'unknown'),({},'unknown'),
])
def test_actor_prefix_is_allowlisted(tag,actor):
    assert real.safe_actor(tag)==actor


@pytest.mark.asyncio
@pytest.mark.parametrize('orders,expected',[([], 'no_orders'),(['not a legal order'],'illegal_orders'),(['A MOS H','A MOS H'],'illegal_orders')])
async def test_order_diagnostics_preserve_engine_input_and_country_fallback(tmp_path,orders,expected):
    from types import SimpleNamespace
    from diplomind.agent import Agent
    from diplomind.engine import OperationEngine
    from diplomind.personalities import PERSONAS
    from diplomind.schemas import OrderSet
    budget=real.Budget(tmp_path/'r.json'); budget.start()
    response={'choices':[{'message':{'content':json.dumps({'orders':orders,'reasoning':'SECRET_REASONING'})}}]}
    gw=real.BoundedGateway('synthetic',budget,transport=httpx.MockTransport(lambda req:httpx.Response(200,json=response)))
    engine=OperationEngine()
    agent=Agent('RUSSIA',PERSONAS['diplomat'],gw)
    session=SimpleNamespace(ai={'RUSSIA':agent},eng=engine)
    gw.order_inspector=lambda actor,orders:real.inspect_orders(session,actor,orders)
    result=await gw.achat([],OrderSet,tag='RUSSIA:order')
    assert result.orders==orders  # Metadata does not change existing gameplay behavior.
    row=budget.records[-1]
    assert row['step']=='OrderSet' and row['error']==expected
    assert row['fallback']=='engine_order_filter' and row['orders_expected_count']==4
    health=budget.country_health()['RUSSIA']
    assert health['failures']==health['fallbacks']==1 and health['last_error']==expected
    assert 'SECRET_REASONING' not in (tmp_path/'r.json').read_text()
    await gw.aclose()
