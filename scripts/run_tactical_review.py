"""Paired tactical diagnostics experiment, at most 30 HTTP calls / 15 minutes.

Twelve initial decisions use today's normal prompt. Each is replayed locally into
an identical fresh agent: only a conditional review may issue another HTTP call.
This isolates the effect of one feedback pass without resampling the first answer.
All dialogue is synthetic; public positions reproduce the completed 1901 replay.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import logging
from pathlib import Path
import random
import resource
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from diplomind.agent import Agent
from diplomind.engine import OperationEngine
from diplomind.personalities import PERSONAS
from diplomind.schemas import OrderSet, UnitPlan
from scripts import run_context_ab as ab

OUT=ROOT/'artifacts/tactical-review'
CASES=('england_opening','england_after_bounce','italy_convoy','invalid_mapping','intentional_standoff','foreign_convoy')


class TacticalGateway(ab.ABGateway):
    call_limit=30
    wall_seconds=900
    maximum_output=2048
    total_output_budget=61440
    thinking_label=False
    method_description='12 current decisions with identical cached first-response pairs; 4 historical-order replay reviews + 2 no-review controls. One optional review each; no transport retries or foreign hidden orders. Hard30HTTP/2048output/900s.'
    def output_directory(self): return OUT


def fixture(name,gw):
    if name not in CASES: raise ValueError('unknown_fixture')
    eng=OperationEngine()
    if name!='england_opening':
        # Published engine orders only. No runtime save, private memory or token.
        public=json.loads((ROOT/'docs/evidence/1901-replay-public-orders.json').read_text())[0]
        for power,orders in public['orders'].items(): eng.submit(power,orders)
        eng.process()
        assert eng.phase()=='F1901M'
    country='ENGLAND' if name.startswith('england') or name=='intentional_standoff' else 'AUSTRIA' if name=='invalid_mapping' else 'ITALY'
    persona='opportunist' if country in {'ENGLAND','ITALY'} else 'balancer'
    agent=Agent(country,PERSONAS[persona],gw,lang='zh-Hans')
    if name in {'england_opening','england_after_bounce'}:
        agent.mem.intent={'goal':'先让舰队进入北海与挪威海，下一阶段争取挪威；不要误把当前本土舰队当成已在NTH。',
                          'ally':'GERMANY','target':'','grab':['NWY'],'move_turn':1902}
        if name=='england_after_bounce':
            prior=['F EDI - NTH','F LON - NTH','A LVP - YOR']
            agent.mem.record_order_diagnostics('S1901M',[{'code':'own_destination_collision','destination':'NTH','orders':prior[:2],
                'message':'两支己方舰队上季误入同一区而互撞；本季应协调不同目的地或支援。'}])
    elif name=='italy_convoy':
        agent.mem.intent={'goal':'争取TUN及GRE，但必须先验证陆军跨海与舰队行动能否同时成立。',
                          'ally':'GERMANY','target':'AUSTRIA','grab':['TUN','GRE'],'move_turn':1902}
        bad=['A APU - GRE VIA','F ION - TUN','A VEN H']
        agent.mem.record_order_diagnostics(eng.phase(),agent._diagnose_orders(eng,bad,[]))
    elif name=='invalid_mapping':
        agent.mem.intent={'goal':'SER军争取GRE；VIE军与TRI舰保持合法协调，不能凭愿望虚构跨越邻接的支援。',
                          'ally':'ITALY','target':'','grab':['GRE'],'move_turn':1902}
        diagnostics=[]
        chosen=agent._resolve(['A VIE - RUM','F TRI S A SER - GRE','A SER - GRE'],agent._legal_flat(eng),diagnostics)
        diagnostics.extend(agent._diagnose_orders(eng,chosen,[]))
        agent.mem.record_order_diagnostics(eng.phase(),diagnostics)
    elif name=='intentional_standoff':
        agent.mem.intent={'goal':'这次明确有意让EDI和LON两舰同时去NTH，造成己方对撞并留在本土；这是本次控制样例的战术虚招，不是误操作。请在intentional_self_standoffs写NTH。YOR军留守。',
                          'ally':'','target':'','grab':[],'move_turn':1902}
    elif name=='foreign_convoy':
        eng.game.clear_units('ITALY');eng.game.set_units('ITALY',['A APU','A VEN','F TYS'])
        eng.game.clear_units('TURKEY');eng.game.set_units('TURKEY',['F ION','A BUL','A SMY'])
        agent.mem.intent={'goal':'按已收到的土方海运提议，用土舰ION运APU军去GRE，同时自己的TYS舰去TUN；外国命令未知，承诺可能被背弃。',
                          'ally':'TURKEY','target':'','grab':['GRE','TUN'],'move_turn':1902}
        agent.observe_messages(eng.phase(),[{'sender':'TURKEY','scope':'private','to':['ITALY'],'rnd':2,
            'text':'我承诺本秋F ION C A APU - GRE。请你A APU - GRE VIA，自己的TYS舰可以去TUN。'}])
        agent.mem.record_order_diagnostics(eng.phase(),agent._diagnose_orders(eng,['A APU - GRE VIA','F TYS - TUN','A VEN H'],[]))
    # Excluded canary catches visibility regressions in baseline AND review prompts.
    agent.observe_messages(eng.phase(),[{'sender':'RUSSIA','scope':'private','to':['GERMANY'],'rnd':2,'text':ab.CANARY}])
    return agent,eng


def digest(messages):
    return hashlib.sha256(json.dumps(messages,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


class CaptureGateway:
    def __init__(self,live): self.live=live;self.messages=None
    async def achat(self,messages,schema,**kwargs):
        self.messages=[dict(m) for m in messages]
        return await self.live.achat(messages,schema,**kwargs)


class ReplayFirstGateway:
    def __init__(self,live,initial,messages):
        self.live,self.initial,self.fingerprint=live,initial,digest(messages)
        self.calls=0
        self.health={}
    async def achat(self,messages,schema,**kwargs):
        self.calls+=1
        if self.calls==1:
            if digest(messages)!=self.fingerprint: raise RuntimeError('paired_initial_prompt_changed')
            return self.initial.model_copy(deep=True) if self.initial is not None else None
        if self.calls>2 or not kwargs.get('tag','').endswith(':order_review') or kwargs.get('retry')!=0:
            raise RuntimeError('unbounded_review_attempt')
        return await self.live.achat(messages,schema,**kwargs)


def snapshot(agent,eng,out,chosen):
    warnings=agent.mem.order_diagnostics
    current=[w for w in warnings if w['phase']==eng.phase()]
    flat=agent._legal_flat(eng)
    raw=agent._resolve(out.orders,flat) if out else []
    expected={x.split('/')[0] for x in eng.legal_orders(agent.country)}
    assigned={o.split()[1].split('/')[0] for o in chosen if len(o.split())>=3}
    return {'typed_output':out is not None,'chosen_orders':list(chosen),
        'raw_order_count':len(out.orders) if out else 0,'raw_resolved_count':len(raw),
        'defaulted_units':sorted(expected-assigned),'all_explicit_holds':bool(chosen) and all(o.split()[2]=='H' for o in chosen),
        'non_hold_orders':sum(o.split()[2]!='H' for o in chosen),
        'warning_codes':[w['code'] for w in current],
        'unacknowledged_warning_codes':[w['code'] for w in current if not w.get('acknowledged')],
        'intentional_standoffs':list(out.intentional_self_standoffs) if out else [],
        'decision_health':dict(agent.decision_health),'context_stats':agent.context_stats}


async def evaluate(key,transport=None):
    gw=TacticalGateway(key,transport=transport)
    initial=[]
    try:
        jobs=[(name,repeat) for name in CASES for repeat in range(2)]
        random.Random(20261002).shuffle(jobs)
        for name,repeat in jobs:
            capture=CaptureGateway(gw);agent,eng=fixture(name,capture)
            gw.meta={'scenario':name,'repeat':repeat,'country':agent.country,'variant':'baseline'}
            trial={'scenario':name,'repeat':repeat,'country':agent.country,'status':'running'};gw.trials.append(trial)
            out,chosen=await agent.a_decide_orders(eng)
            trial['baseline']=snapshot(agent,eng,out,chosen)
            initial.append((name,repeat,out,capture.messages,trial))
            gw.persist('running')
        for name,repeat,out,messages,trial in initial:
            replay=ReplayFirstGateway(gw,out,messages);agent,eng=fixture(name,replay)
            gw.meta={'scenario':name,'repeat':repeat,'country':agent.country,'variant':'optimized'}
            before=len(gw.records)
            revised,chosen=await agent.a_decide_orders(eng,preflight_review=True)
            trial.update(status='completed',review=snapshot(agent,eng,revised,chosen),
                         additional_http_calls=len(gw.records)-before,
                         initial_response_reused=True,initial_prompt_matched=replay.calls>=1)
            assert trial['additional_http_calls']<=1
            gw.persist('running')
        # Separate known-failure replay probes. Their initial candidate is the
        # actually published historical order set, not a newly sampled answer.
        # Original hidden rationale is unavailable and is not reconstructed.
        public=json.loads((ROOT/'docs/evidence/1901-replay-public-orders.json').read_text())
        seeds=[('england_opening',repeat,public[0]['orders']['ENGLAND'],[]) for repeat in range(2)]
        seeds += [('italy_convoy',repeat,public[1]['orders']['ITALY'],[]) for repeat in range(2)]
        seeds += [('intentional_standoff',0,['F EDI - NTH','F LON - NTH','A YOR H'],['NTH']),
                  ('foreign_convoy',0,['A APU - GRE VIA','F TYS - TUN','A VEN H'],[])]
        for name,repeat,orders,flags in seeds:
            capture=CaptureGateway(gw);baseline,eng=fixture(name,capture)
            candidate=OrderSet(orders=orders,intentional_self_standoffs=flags,
                unit_plan=[UnitPlan(unit=' '.join(o.split()[:2]),order=o) for o in orders])
            # Dry first call captures the real prompt and normal diagnostics.
            class SeedGateway:
                async def achat(self,messages,schema,**kwargs):
                    capture.messages=[dict(m) for m in messages]
                    return candidate.model_copy(deep=True)
            baseline.gw=SeedGateway()
            out,chosen=await baseline.a_decide_orders(eng)
            trial={'scenario':name,'repeat':repeat,'country':baseline.country,
                   'initial_source':'public_historical_orders' if name in {'england_opening','italy_convoy'} else 'synthetic_control',
                   'baseline':snapshot(baseline,eng,out,chosen),'status':'running'}
            gw.trials.append(trial)
            replay=ReplayFirstGateway(gw,candidate,capture.messages);agent,eng=fixture(name,replay)
            gw.meta={'scenario':name,'repeat':repeat,'country':agent.country,'variant':'seed_review'}
            before=len(gw.records)
            revised,chosen=await agent.a_decide_orders(eng,preflight_review=True)
            trial.update(status='completed',review=snapshot(agent,eng,revised,chosen),
                         additional_http_calls=len(gw.records)-before,initial_response_reused=True,
                         initial_prompt_matched=replay.calls>=1)
            assert trial['additional_http_calls']<=1
            if name in {'intentional_standoff','foreign_convoy'}:
                assert trial['additional_http_calls']==0
            gw.persist('running')
        gw.persist('completed')
        return len(gw.records)
    except BaseException:
        gw.persist('stopped')
        raise
    finally: await gw.close()


def main():
    previous=logging.root.manager.disable;logging.disable(logging.CRITICAL);key=''
    try:
        if sys.argv[1:]!=['--configured']: raise RuntimeError('explicit_configuration_required')
        resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        if resource.getrlimit(resource.RLIMIT_CORE)!=(0,0): raise RuntimeError('unsafe_runtime')
        key=ab.configured_key()
        calls=asyncio.run(evaluate(key))
        print(json.dumps({'status':'completed','calls':calls}),flush=True)
        return 0
    except Exception:
        print('{"status":"failed","error":"evaluation_stopped"}',flush=True)
        return 1
    finally: key='';logging.disable(previous)


if __name__=='__main__': raise SystemExit(main())
