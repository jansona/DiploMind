"""Offline-only contracts for paired tactical review and strict HTTP budget."""
import json
import httpx
import pytest
from diplomind.providers.mock import MockProvider
from diplomind.schemas import OrderSet
from scripts import run_tactical_review as tr

KEY='SYNTHETIC_AUTH_KEY_DO_NOT_LOG'


def response(output):
    return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(output)},'finish_reason':'stop'}],
                                  'usage':{'prompt_tokens':100,'completion_tokens':30,'total_tokens':130}})


@pytest.mark.asyncio
async def test_pair_reuses_initial_response_and_respects_model_privacy_and_options(tmp_path,monkeypatch):
    monkeypatch.setattr(tr,'OUT',tmp_path)
    seen=[];mock=MockProvider()
    def endpoint(request):
        data=json.loads(request.content);seen.append(data)
        return response(mock.complete(data['messages'],OrderSet))
    count=await tr.evaluate(KEY,httpx.MockTransport(endpoint))
    report=json.loads((tmp_path/'report.json').read_text())
    assert count==len(seen) and 12<=count<=28<=30
    assert len(report['trials'])==18
    controls=[t for t in report['trials'] if t.get('initial_source')=='synthetic_control']
    assert len(controls)==2 and all(t['additional_http_calls']==0 for t in controls)
    assert all(t['status']=='completed' and t['initial_prompt_matched'] and t['initial_response_reused'] for t in report['trials'])
    assert all(t['additional_http_calls']<=1 for t in report['trials'])
    assert all(p['model']==tr.ab.MODEL and p['enable_thinking'] is False and p['max_tokens']==2048 for p in seen)
    assert all(tr.ab.CANARY not in json.dumps(p) and KEY not in json.dumps(p) for p in seen)
    assert KEY not in (tmp_path/'report.json').read_text()


@pytest.mark.asyncio
async def test_all_failures_consume_budget_and_never_retry(tmp_path,monkeypatch):
    monkeypatch.setattr(tr,'OUT',tmp_path)
    seen=[]
    def endpoint(request):seen.append(request);return httpx.Response(500,json={'error':KEY})
    gw=tr.TacticalGateway(KEY,transport=httpx.MockTransport(endpoint))
    for _ in range(30):assert await gw.achat([],OrderSet,retry=100) is None
    with pytest.raises(RuntimeError,match='budget_exhausted'): await gw.achat([],OrderSet)
    assert len(seen)==30 and gw.reserved_output_tokens==61440
    assert KEY not in (tmp_path/'report.json').read_text()
    await gw.close()


@pytest.mark.asyncio
async def test_wall_clock_prevents_request_after_fifteen_minutes(tmp_path,monkeypatch):
    monkeypatch.setattr(tr,'OUT',tmp_path)
    clock=[0.]
    gw=tr.TacticalGateway(KEY,transport=httpx.MockTransport(lambda _:pytest.fail('no HTTP allowed')),clock=lambda:clock[0])
    clock[0]=900
    with pytest.raises(RuntimeError,match='budget_exhausted'): await gw.achat([],OrderSet)
    assert not gw.records
    await gw.close()


@pytest.mark.asyncio
async def test_replayed_first_prompt_must_be_identical_and_third_call_forbidden(tmp_path,monkeypatch):
    monkeypatch.setattr(tr,'OUT',tmp_path)
    gw=tr.TacticalGateway(KEY,transport=httpx.MockTransport(lambda _:response({'orders':[]})))
    proxy=tr.ReplayFirstGateway(gw,OrderSet(orders=[]),[{'role':'user','content':'first'}])
    with pytest.raises(RuntimeError,match='paired_initial_prompt_changed'):
        await proxy.achat([{'role':'user','content':'changed'}],OrderSet)
    assert not gw.records
    proxy=tr.ReplayFirstGateway(gw,OrderSet(orders=[]),[])
    await proxy.achat([],OrderSet)
    await proxy.achat([],OrderSet,tag='ITALY:order_review',retry=0)
    with pytest.raises(RuntimeError,match='unbounded_review_attempt'):
        await proxy.achat([],OrderSet,tag='ITALY:order_review',retry=0)
    assert len(gw.records)==1
    await gw.close()


def test_fixtures_use_actual_public_positions_and_preserve_unknown_cooperation():
    england,eng=tr.fixture('england_opening',None)
    assert set(eng.game.powers['ENGLAND'].units)=={'F EDI','F LON','A LVP'}
    england,eng=tr.fixture('england_after_bounce',None)
    assert set(eng.game.powers['ENGLAND'].units)=={'F EDI','F LON','A YOR'}
    italy,eng=tr.fixture('italy_convoy',None)
    assert any(d['code']=='no_planned_convoy_path' for d in italy.mem.order_diagnostics)
    ally,eng=tr.fixture('foreign_convoy',None)
    assert 'A APU - GRE VIA' in ally._legal_flat(eng)
    assert any(d['code']=='convoy_requires_foreign_cooperation' for d in ally.mem.order_diagnostics)
    assert tr.ab.CANARY not in ally.perceive(eng)
