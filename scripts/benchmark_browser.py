"""Mock-only native cloud browser benchmark; own contexts/room, no demo changes."""
import argparse, json, math, os, platform, shutil, statistics, time
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]; BASE=os.getenv('DIPLOMIND_PERF_URL','http://127.0.0.1:8731')
INIT="""localStorage.setItem('diplomind.locale','en'); window.perfSources=[]; const NativeES=window.EventSource; window.EventSource=class extends NativeES {constructor(...args){super(...args);window.perfSources.push(this)}};window.perfLong=[];new PerformanceObserver(list=>window.perfLong.push(...list.getEntries().map(x=>({start:x.startTime,duration:x.duration})))).observe({type:'longtask',buffered:true});"""
def metrics(cdp):return {x['name']:x['value'] for x in cdp.send('Performance.getMetrics')['metrics']}
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='artifacts/performance/browser-baseline.json');args=parser.parse_args();out=ROOT/args.output;out.parent.mkdir(parents=True,exist_ok=True)
    report={'transport':'native Chromium loopback HTTP; no bandwidth/CPU throttling','cases':[],'errors':[]}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=shutil.which('chromium') or '/usr/bin/chromium',args=['--disable-dev-shm-usage','--enable-unsafe-swiftshader'])
        report['chromium']=browser.version
        try: report['gpu']=browser.new_browser_cdp_session().send('SystemInfo.getInfo')['gpu']
        except Exception as e:report['gpu_unavailable']=type(e).__name__
        request=pw.request.new_context(base_url=BASE)
        assert request.get('/api/providers').json()['selected']=='mock','Refusing non-mock server'
        for label,viewport in [('desktop',{'width':1440,'height':1000}),('mobile',{'width':390,'height':844})]:
            context=browser.new_context(viewport=viewport);context.add_init_script(INIT);page=context.new_page();page.set_default_timeout(60000);page.on('pageerror',lambda e:report['errors'].append(str(e)))
            cdp=context.new_cdp_session(page);cdp.send('Performance.enable');cdp.send('Network.enable');cdp.send('Network.setCacheDisabled',{'cacheDisabled':True})
            wall=time.perf_counter();page.goto(BASE,wait_until='domcontentloaded');page.wait_for_function("document.querySelector('#board-host').dataset.assetsLoaded==='4' && document.querySelector('#board-host').dataset.provinces==='76'")
            case={'viewport':label,'size':viewport,'cold_complete_wall_ms':round((time.perf_counter()-wall)*1000,2)}
            case['navigation']=page.evaluate("(()=>{const n=performance.getEntriesByType('navigation')[0];return {response_start_ms:n.responseStart,response_end_ms:n.responseEnd,dom_content_loaded_ms:n.domContentLoadedEventEnd,paint:performance.getEntriesByType('paint').map(x=>({name:x.name,ms:x.startTime})),glb:performance.getEntriesByType('resource').filter(x=>x.name.endsWith('.glb')).map(x=>({name:x.name.split('/').pop(),end_ms:x.responseEnd,bytes:x.transferSize})),assets:document.querySelector('#board-host').dataset.assetsLoaded,renderer:document.querySelector('#board-host').dataset.renderer}})()")
            before=metrics(cdp);page.wait_for_timeout(2500);after=metrics(cdp);case['idle_2500ms']={k:round((after[k]-before[k])*1000,3) for k in ['TaskDuration','ScriptDuration','LayoutDuration','RecalcStyleDuration']}
            identity=request.post('/api/room/create',data={'name':'Isolated performance probe','owner_name':'Performance probe','power':'FRANCE','lang':'en'}).json()
            try:
                page.evaluate("x=>sessionStorage.setItem('diplomind.session',JSON.stringify(x))",identity);page.reload(wait_until='domcontentloaded');page.wait_for_function('window._last && window.perfSources.length > 0');page.wait_for_function("document.querySelector('#board-host').dataset.assetsLoaded==='4'")
                state=request.get('/api/state',params={'token':identity['token']}).json();page.wait_for_timeout(1500);page.evaluate('window.perfSources.forEach(s=>s.close())')
                state.update(mode='NEGO',phase_type='M',round=1,turn_id='perf-stable',status='playing',secs_left=180,channels={'群聊':[f'S1901M R1 ENGLAND: synthetic benchmark {i} '+('x'*2000) for i in range(700)]},pending=['FRANCE'],your_turn=True,msgs_left=3,staged_msgs=[],centers={},legal=[])
                before=metrics(cdp)
                case['full_snapshot_injection']=page.evaluate("async s=>{const es=window.perfSources.at(-1);const t=performance.now();es.dispatchEvent(new MessageEvent('message',{data:JSON.stringify(s)}));await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);return {elapsed_ms:performance.now()-t,chat_nodes:document.querySelectorAll('.chat-message').length}}",state)
                after=metrics(cdp);case['full_snapshot_cpu']={k:round((after[k]-before[k])*1000,3) for k in ['TaskDuration','ScriptDuration','LayoutDuration','RecalcStyleDuration']}
                # Each fixture event is delivered on a timer, never a busy loop. Select production clock event if supported.
                page.evaluate("()=>{window.perfChatNode=document.querySelector('.chat-message');const input=document.querySelector('#message-input');input.value='unsent local draft';input.setSelectionRange(3,7)}")
                before=metrics(cdp)
                case['ten_timer_events']=page.evaluate("async s=>{const times=[];const es=window.perfSources.at(-1);const compact=(await fetch('/static/app.js').then(x=>x.text())).includes('addEventListener(\"clock\"');for(let i=0;i<10;i++){await new Promise(r=>setTimeout(r,100));s.secs_left=179-i;const payload=compact?{secs_left:s.secs_left,dropped:[],short:[],room:s.room,version:s.version,turn_id:s.turn_id}:s;const t=performance.now();es.dispatchEvent(new MessageEvent(compact?'clock':'message',{data:JSON.stringify(payload)}));times.push(performance.now()-t)}return {compact_clock:compact,handler_ms:times,clock_text:document.querySelector('#round-clock').textContent}}",state)
                after=metrics(cdp);case['ten_timer_events_cpu']={k:round((after[k]-before[k])*1000,3) for k in ['TaskDuration','ScriptDuration','LayoutDuration','RecalcStyleDuration']}
                case['clock_dom_guards']=page.evaluate("()=>{const before=document.querySelector('#round-clock').textContent;window.perfSources.at(-1).dispatchEvent(new MessageEvent('clock',{data:JSON.stringify({room:window._last.room,version:-99,turn_id:window._last.turn_id,secs_left:1})}));const input=document.querySelector('#message-input');return {same_chat_node:window.perfChatNode===document.querySelector('.chat-message'),draft:input.value,selection:[input.selectionStart,input.selectionEnd],stale_clock_ignored:before===document.querySelector('#round-clock').textContent}}")
                assert case['clock_dom_guards']['same_chat_node'] and case['clock_dom_guards']['stale_clock_ignored']
                assert case['clock_dom_guards']['draft']=='unsent local draft' and case['clock_dom_guards']['selection']==[3,7]
                case['presence_notice_guard']=page.evaluate("()=>{const s=window._last;const es=window.perfSources.at(-1);const base={room:s.room,version:s.version,turn_id:s.turn_id,secs_left:s.secs_left,short:[]};es.dispatchEvent(new MessageEvent('clock',{data:JSON.stringify({...base,dropped:['GERMANY']})}));const appeared=document.body.innerText.includes('Waiting for disconnected players: Germany');es.dispatchEvent(new MessageEvent('clock',{data:JSON.stringify({...base,dropped:[]})}));return {appeared,cleared:!document.body.innerText.includes('Waiting for disconnected players: Germany')}}")
                if case['ten_timer_events']['compact_clock']:assert all(case['presence_notice_guard'].values())
                # Restore real state before observing frame cadence.
                page.evaluate("s=>window.perfSources.at(-1).dispatchEvent(new MessageEvent('message',{data:JSON.stringify(s)}))",request.get('/api/state',params={'token':identity['token']}).json())
                case['frame_cadence']=page.evaluate("()=>new Promise(resolve=>{const ts=[];let prev;const start=performance.now();function f(t){if(prev!==undefined)ts.push(t-prev);prev=t;if(t-start<2000)requestAnimationFrame(f);else resolve({count:ts.length,interval_ms:ts})}requestAnimationFrame(f)})")
                page.screenshot(path=str(out.parent/(label+'-'+out.stem+'.png')),full_page=True)
            finally:request.post('/api/room/end',data={'token':identity['token']})
            case['longtasks']=page.evaluate('window.perfLong');report['cases'].append(case);context.close();print('Finished',label,flush=True)
        # Genuine server-delivered event check in a separate mock room/context.
        identity=request.post('/api/room/create',data={'name':'SSE transport probe','owner_name':'probe','power':'FRANCE','lang':'en'}).json()
        try:
            request.post('/api/room/start',data={'token':identity['token']})
            context=browser.new_context(viewport={'width':1440,'height':1000})
            context.add_init_script(INIT+"window.perfEvents=[];const PerfES=window.EventSource;window.EventSource=class extends PerfES{constructor(...a){super(...a);this.addEventListener('message',e=>window.perfEvents.push({type:'message',bytes:e.data.length}));this.addEventListener('clock',e=>window.perfEvents.push({type:'clock',bytes:e.data.length,data:JSON.parse(e.data)}))}};")
            page=context.new_page();page.goto(BASE);page.evaluate("x=>sessionStorage.setItem('diplomind.session',JSON.stringify(x))",identity);page.reload();page.wait_for_function('window._last && window.perfSources.length>0');page.wait_for_timeout(4500)
            report['real_sse']=page.evaluate("({events:window.perfEvents,clock_text:document.querySelector('#round-clock').textContent,state_seconds:window._last.secs_left})")
            if 'addEventListener("clock"' in request.get('/static/app.js').text():
                assert any(e['type']=='clock' for e in report['real_sse']['events']), 'No production clock event received'
            context.close()
        finally:request.post('/api/room/end',data={'token':identity['token']})
        request.dispose();browser.close()
    out.write_text(json.dumps(report,indent=2));print(str(out),flush=True)
if __name__=='__main__':main()
