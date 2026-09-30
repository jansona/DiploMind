"""Production order path opt-in, no real providers or credentials."""
import asyncio
import json
import pytest
from diplomind.config import Config,load
from diplomind.session import Session,POWERS
from diplomind.schemas import OrderSet
from diplomind.players import AIPlayer
from scripts.run_real_game import Budget,BoundedGateway
import httpx


@pytest.mark.parametrize('bad',['true',1,None,{},[]])
def test_flag_is_strict_server_boolean(bad,tmp_path,monkeypatch):
    with pytest.raises(ValueError,match='boolean'):Config(order_preflight_review=bad)
    p=tmp_path/'cfg.json';p.write_text(json.dumps({'order_preflight_review':bad}))
    monkeypatch.setenv('DIPLOMIND_CONFIG',str(p))
    with pytest.raises(ValueError,match='boolean'):load()


def test_file_opt_in_and_default_off(tmp_path,monkeypatch):
    assert Config().order_preflight_review is False
    p=tmp_path/'cfg.json';p.write_text('{"api":"mock","order_preflight_review":true}')
    monkeypatch.setenv('DIPLOMIND_CONFIG',str(p))
    assert load().order_preflight_review is True


class GW:
    def __init__(self,fail=False):self.calls=[];self.fail=fail
    async def achat(self,messages,schema,**kwargs):
        self.calls.append(kwargs)
        if kwargs['tag'].endswith('order_review'):
            if self.fail:return None
            return OrderSet(orders=['F EDI - NTH','F LON S F EDI - NTH','A LVP - YOR'])
        return OrderSet(orders=['F EDI - NTH','F LON - NTH','A LVP - YOR'])
    async def aclose(self):pass


@pytest.mark.asyncio
@pytest.mark.parametrize('enabled,fail,expected',[(False,False,1),(True,False,2),(True,True,2)])
async def test_session_production_order_path_uses_flag_and_retains_initial_on_error(enabled,fail,expected):
    session=Session([p for p in POWERS if p!='ENGLAND'],cfg=Config(api='mock',order_preflight_review=enabled))
    original=session.gw;gw=GW(fail)
    session.gw=gw;session.ai['ENGLAND'].gw=gw
    try:
        chosen=await session._decide_one(session.players['ENGLAND'])
        assert len(gw.calls)==expected
        assert chosen==session._ai_orders['ENGLAND']
        if enabled and not fail:assert 'F LON S F EDI - NTH' in chosen
        else:assert 'F LON - NTH' in chosen
        if enabled:assert gw.calls[-1]['retry']==0
        assert len(session.ai['ENGLAND'].mem.actions)==3
        assert 'order_preflight_review' not in session.state('FRANCE')
        session.aiify('FRANCE')
        assert session.players['FRANCE'].preflight_review is enabled
    finally:await session.aclose();await original.aclose()


@pytest.mark.asyncio
async def test_review_uses_same_process_request_budget_not_a_new_gateway(tmp_path):
    rows=[]
    def endpoint(request):
        rows.append(request)
        orders=['F EDI - NTH','F LON - NTH','A LVP - YOR'] if len(rows)==1 else ['F EDI - NTH','F LON S F EDI - NTH','A LVP - YOR']
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'orders':orders})},'finish_reason':'stop'}]})
    budget=Budget(tmp_path/'report.json');budget.start()
    # Only one physical HTTP slot remains. The attempted review must preserve the
    # initial usable plan rather than silently obtaining another gateway budget.
    budget.calls=49
    gw=BoundedGateway('SYNTHETIC',budget,transport=httpx.MockTransport(endpoint))
    session=Session([p for p in POWERS if p!='ENGLAND'],cfg=Config(api='mock',order_preflight_review=True))
    original=session.gw;session.gw=gw;session.ai['ENGLAND'].gw=gw
    try:
        chosen=await session._decide_one(session.players['ENGLAND'])
        assert budget.calls==50 and len(rows)==1
        assert 'F LON - NTH' in chosen
        assert session.ai['ENGLAND'].decision_health['review_used'] is False
    finally:await session.aclose();await original.aclose()


def test_saved_game_cannot_override_operator_policy(monkeypatch):
    import diplomind.session as sessions
    cfg=Config(api='mock',order_preflight_review=False)
    monkeypatch.setattr(sessions,'load_config',lambda:cfg)
    original=Session(['FRANCE'],cfg=cfg)
    blob=original.to_dict();blob['order_preflight_review']=True
    restored=Session.from_dict(blob)
    try:
        assert all(not p.preflight_review for p in restored.ai_players())
    finally:original.close();restored.close()


@pytest.mark.asyncio
async def test_batch_orchestrator_uses_same_explicit_option():
    from diplomind.engine import OperationEngine
    from diplomind.orchestrator import Orchestrator
    class AgentProbe:
        async def a_decide_orders(self,eng,**kwargs):
            assert kwargs=={'preflight_review':True}
            return None,['A PAR H','A MAR H','F BRE H']
    result=await Orchestrator(OperationEngine(),{'FRANCE':AgentProbe()},preflight_review=True).collect_and_process()
    assert result['orders']['FRANCE']['rejected']==[]
