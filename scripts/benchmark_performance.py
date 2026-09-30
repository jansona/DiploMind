"""Offline, repeatable CPU/latency baseline. No configuration or credential reads.

Run: .venv/bin/python scripts/benchmark_performance.py --output artifacts/performance/baseline.json
HTTP metrics use httpx ASGITransport (in-process, no network/transport latency).
"""
from __future__ import annotations
import argparse, asyncio, gc, json, logging, math, os, platform, resource, statistics, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from diplomind.config import Config
import diplomind.config as config
CFG=Config(api="mock", model="offline-simulation", api_key=None, rounds=1)
config.load=lambda: CFG
from diplomind.session import Session, POWERS
import diplomind.session as session_module
session_module.load_config=lambda: CFG
from diplomind.engine import OperationEngine
from diplomind.board import board_state, _geometry
from diplomind.rooms import RoomManager, Room
import diplomind.web as web
import httpx
web.load_config=lambda: CFG
logging.disable(logging.CRITICAL)

def summary(values):
    ordered=sorted(values)
    return {"n":len(values), "p50_ms":round(statistics.median(values),4), "p95_ms":round(ordered[max(0,math.ceil(len(ordered)*.95)-1)],4), "max_ms":round(max(values),4)}

def bench(fn, count=200, warm=10):
    for _ in range(warm): fn()
    samples=[]; cpu=time.process_time()
    for _ in range(count):
        t=time.perf_counter(); fn(); samples.append((time.perf_counter()-t)*1000)
    return {**summary(samples), "cpu_total_ms":round((time.process_time()-cpu)*1000,3)}

def rss():
    return int(Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')/1024/1024

async def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--output',default='artifacts/performance/baseline.json'); args=parser.parse_args()
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True)
    Session.SAVES=out.parent/'isolated-saves'
    report={"environment":{"python":platform.python_version(),"platform":platform.platform(),"cpu_count":os.cpu_count(),"provider":"mock","transport":"httpx ASGITransport; no sockets or network latency","rss_method":"/proc/self/statm resident pages; MiB"},"micro":{},"loads":[]}
    report['rss_start_mib']=round(rss(),2)
    s=Session('FRANCE',cfg=CFG); s.mode='ORDERS'
    t=time.perf_counter(); s.legal('FRANCE'); report['micro']['legal_cold_ms']=round((time.perf_counter()-t)*1000,4)
    _geometry.cache_clear();t=time.perf_counter(); board=board_state(s.eng);report['micro']['board_geometry_cold_ms']=round((time.perf_counter()-t)*1000,4)
    for name,fn in {'legal_warm':lambda:s.legal('FRANCE'),'state_build':lambda:s.state('FRANCE'),'state_json':lambda:json.dumps(s.state('FRANCE')),'board_build':lambda:board_state(s.eng),'board_json':lambda:json.dumps(board_state(s.eng))}.items():report['micro'][name]=bench(fn)
    report['payload_bytes']={'state':len(json.dumps(s.state('FRANCE')).encode()),'board':len(json.dumps(board).encode())}
    # Real synchronous rules resolution, warmed engine construction included separately.
    report['micro']['engine_construct']=bench(OperationEngine,50,2)
    adjud=[]
    for _ in range(50):
        eng=OperationEngine();
        for p in POWERS: eng.submit(p,[f'{u} H' for u in eng.game.powers[p].units])
        t=time.perf_counter();eng.process();adjud.append((time.perf_counter()-t)*1000)
    report['micro']['adjudication_all_hold']=summary(adjud)
    # Long-history public/private filtering stays seat-specific, with no cached identities.
    for i in range(1500):s.bus.post(i%5+1,'ENGLAND','private' if i%2 else 'broadcast',['FRANCE'],f'Benchmark message {i} '+('x'*100),phase='S1901M')
    report['micro']['state_1500_messages_json']=bench(lambda:json.dumps(s.state('FRANCE')))
    await s.aclose();del s;gc.collect()
    for count in (1,7,20):
        start_rss=rss();created=time.perf_counter();sessions=[Session('FRANCE',cfg=CFG) for _ in range(count)];construct_ms=(time.perf_counter()-created)*1000
        rm=RoomManager(); web.RM=rm; tokens=[]
        for i,s in enumerate(sessions):
            s.mode='ORDERS';r=Room(f'perf-{i}','perf',lang='en');r.session=s;r.status='playing';r.timer_on=False
            r.seats['FRANCE']={'name':'perf','token':r.owner,'kind':'human'};rm.rooms[r.code]=r;rm.tokens[r.owner]=r.code;tokens.append(r.owner);s.legal('FRANCE')
        lag=[];stop=False
        async def heartbeat():
            while not stop:
                target=time.perf_counter()+.005;await asyncio.sleep(.005);lag.append(max(0,(time.perf_counter()-target)*1000))
        task=asyncio.create_task(heartbeat());await asyncio.sleep(.005)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app),base_url='http://offline.test') as client:
            assert (await client.get('/api/providers')).json()['selected']=='mock'
            state_lat=[];board_lat=[]
            async def request(route,token,results):
                t=time.perf_counter();resp=await client.get(route,params={'token':token});assert resp.status_code==200;results.append((time.perf_counter()-t)*1000)
            cpu=time.process_time();wall=time.perf_counter()
            for _ in range(20):await asyncio.gather(*(request('/api/state',token,state_lat) for token in tokens))
            for _ in range(5):await asyncio.gather(*(request('/api/board',token,board_lat) for token in tokens))
            load_cpu=(time.process_time()-cpu)*1000;load_wall=(time.perf_counter()-wall)*1000
        # One real SSE frame per subscriber, production state filtering and JSON path.
        streams=[await web.stream(r.code,t) for t in tokens for r in [rm.rooms[rm.tokens[t]]]]
        cpu=time.process_time();t=time.perf_counter();frames=await asyncio.gather(*(anext(response.body_iterator) for response in streams));sse_ms=(time.perf_counter()-t)*1000;sse_cpu=(time.process_time()-cpu)*1000
        for response in streams:await response.body_iterator.aclose()
        # Real mock phase computation for mixed rooms, no simulated HTTP provider.
        for s in sessions:s.mode='NEGO'
        t=time.perf_counter();cpu=time.process_time();await asyncio.gather(*(s.begin_phase() for s in sessions))
        while any(s._tasks for s in sessions): await asyncio.sleep(.001)
        mock_ms=(time.perf_counter()-t)*1000;mock_cpu=(time.process_time()-cpu)*1000
        stop=True;await task
        report['loads'].append({'sessions':count,'rss_delta_mib':round(rss()-start_rss,2),'rss_total_mib':round(rss(),2),'construct_ms':round(construct_ms,2),'http_state':summary(state_lat),'http_board':summary(board_lat),'http_load_cpu_ms':round(load_cpu,2),'http_load_wall_ms':round(load_wall,2),'event_loop_lag':summary(lag),'sse_initial_fanout_ms':round(sse_ms,3),'sse_initial_cpu_ms':round(sse_cpu,3),'sse_frame_total_bytes':sum(len(x.encode()) for x in frames),'mock_begin_phase_wall_ms':round(mock_ms,2),'mock_begin_phase_cpu_ms':round(mock_cpu,2),'mock_provider_calls':sum(s.gw.health['calls'] for s in sessions)})
        for s in sessions:await s.aclose()
        web.RM=RoomManager();del sessions,rm,streams;gc.collect()
    report['rss_final_mib']=round(rss(),2);report['max_rss_mib']=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,2)
    out.write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))

if __name__=='__main__':asyncio.run(main())
