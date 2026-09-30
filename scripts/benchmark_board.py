"""Paired ASGI board comparison, interleaved legacy encoder and direct JSON paths."""
import asyncio, gc, json, time
from pathlib import Path
from benchmark_performance import CFG, Session, Room, RoomManager, board_state, OperationEngine, summary, web, httpx

async def main():
    web.RM=RoomManager();web.RM.checkpoint=lambda _:None
    sessions=[];tokens=[]
    for i in range(20):
        r=Room('paired board','probe');r.session=Session('FRANCE',cfg=CFG);sessions.append(r.session);web.RM.rooms[r.code]=r;web.RM.tokens[r.owner]=r.code;tokens.append(r.owner)
    route=next(r for r in web.app.routes if getattr(r,'path',None)=='/api/board')
    original=route.dependant.call
    async def legacy(token: str | None=None):
        room=web._room(token) if token else None
        return board_state(room.session.eng if room and room.session else OperationEngine())
    report={'method':'interleaved 3 blocks × 5 bursts after 2 warmups each; ASGITransport, same process/engines/payloads; excludes network; CPU shared environment', 'loads':[]}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app),base_url='http://paired.test') as client:
            assert (await client.get('/api/providers')).json()['selected']=='mock'
            for count in (1,7,20):
                result={'sessions':count,'legacy':{'lat':[],'cpu_ms':0},'direct_json':{'lat':[],'cpu_ms':0}}
                async def request(token,samples):
                    start=time.perf_counter();r=await client.get('/api/board',params={'token':token});assert r.status_code==200;samples.append((time.perf_counter()-start)*1000)
                for block in range(3):
                    variants=[('legacy',legacy),('direct_json',original)]
                    if block%2:variants.reverse()
                    for label,fn in variants:
                        route.dependant.call=fn
                        for _ in range(2):await asyncio.gather(*(request(t,[]) for t in tokens[:count]))
                        gc.collect();cpu=time.process_time()
                        for _ in range(5):await asyncio.gather(*(request(t,result[label]['lat']) for t in tokens[:count]))
                        result[label]['cpu_ms']+=(time.process_time()-cpu)*1000
                for label in ('legacy','direct_json'):
                    result[label]['latency']=summary(result[label].pop('lat'));result[label]['cpu_ms']=round(result[label]['cpu_ms'],3)
                report['loads'].append(result)
    finally:
        route.dependant.call=original
        for s in sessions:await s.aclose()
    out=Path('artifacts/performance/board-comparison.json');out.write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if __name__=='__main__':asyncio.run(main())
