"""Mock-only long-history SSE serialization, fanout and clock delta comparison."""
import asyncio, json, statistics, sys, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from diplomind.config import Config
import diplomind.config as config
CFG=Config(api='mock',api_key=None); config.load=lambda:CFG
from diplomind.session import Session
from diplomind.rooms import Room, RoomManager
import diplomind.web as web

def stats(samples):
    s=sorted(samples);return {'n':len(s),'p50_ms':round(statistics.median(s),4),'p95_ms':round(s[max(0,int(len(s)*.95)-1)],4),'max_ms':round(max(s),4)}

async def main():
    web.RM=RoomManager();s=Session('FRANCE',cfg=CFG);r=Room('perf','perf');r.session=s;r.status='playing';r.seats['FRANCE']={'name':'perf','token':r.owner,'kind':'human'};web.RM.rooms[r.code]=r;web.RM.tokens[r.owner]=r.code
    for i in range(700):s.bus.post(1,'ENGLAND','broadcast',[],'x'*2000,phase='S1901M')
    report={'fixture':'700 public messages × 2000 characters; one shared game, 1/7/20 independently authenticated stream clients','comparison':'old production full state+json on every tick vs new production stream generator; sleep removed equally to measure CPU only','loads':[]}
    actual_sleep=web.asyncio.sleep
    async def no_sleep(_):return None
    web.asyncio.sleep=no_sleep
    try:
        for count in (1,7,20):
            streams=[]
            for i in range(count):
                token=f'perf-{count}-{i}';web.RM.tokens[token]=r.code;streams.append((await web.stream(r.code,token)).body_iterator)
            initial=await asyncio.gather(*(anext(x) for x in streams))
            old=[];new=[];old_cpu=time.process_time();bytes_old=0
            for tick in range(30):
                r.deadline=time.time()+180-tick;start=time.perf_counter()
                frames=[f'data: {json.dumps(web._state(f"perf-{count}-{i}"))}\n\n' for i in range(count)]
                old.append((time.perf_counter()-start)*1000);bytes_old+=sum(len(x.encode()) for x in frames)
            old_cpu=(time.process_time()-old_cpu)*1000
            new_cpu=time.process_time();bytes_new=0
            for tick in range(30):
                r.deadline=time.time()+180-tick;start=time.perf_counter();frames=await asyncio.gather(*(anext(x) for x in streams));new.append((time.perf_counter()-start)*1000);bytes_new+=sum(len(x.encode()) for x in frames)
                assert all(x.startswith('event: clock\n') for x in frames)
            new_cpu=(time.process_time()-new_cpu)*1000
            report['loads'].append({'subscribers':count,'initial_full_bytes_per_subscriber':len(initial[0].encode()),'old_full_tick_fanout':stats(old),'new_clock_tick_fanout':stats(new),'old_cpu_30ticks_ms':round(old_cpu,3),'new_cpu_30ticks_ms':round(new_cpu,3),'old_bytes_30ticks':bytes_old,'new_bytes_30ticks':bytes_new})
            for x in streams:await x.aclose()
    finally:web.asyncio.sleep=actual_sleep;await s.aclose()
    out=Path('artifacts/performance/sse-comparison.json');out.parent.mkdir(exist_ok=True,parents=True);out.write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if __name__=='__main__':asyncio.run(main())
