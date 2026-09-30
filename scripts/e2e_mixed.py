"""Real-browser offline acceptance: two human contexts, five heuristic AIs, observer.

Run a mock-config server, then `uv run python scripts/e2e_mixed.py`.
DIPLOMIND_E2E_URL / CHROMIUM_EXECUTABLE can override local defaults.
No credentials, external model calls, or privileged application test hooks.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import time
import traceback

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "e2e"
OUT.mkdir(parents=True, exist_ok=True)
BASE = os.getenv("DIPLOMIND_E2E_URL", "http://127.0.0.1:8731")
report = {"provider": "mock", "human_clients": 2, "ai_opponents": 5, "observer_clients": 1, "checks": []}
errors: list[str] = []


def check(name):
    report["checks"].append(name)
    print("PASS", name, flush=True)


def capture(page, name):
    expect(page.locator(".toast")).to_have_count(0, timeout=8000)
    page.screenshot(path=str(OUT/name), full_page=True)


def identity(page):
    return page.evaluate("JSON.parse(sessionStorage.getItem('diplomind.session'))")


def state(page):
    return page.evaluate("async () => {const s=JSON.parse(sessionStorage.getItem('diplomind.session'));return (await fetch('/api/state?token='+encodeURIComponent(s.token))).json()}")


def wait_for(predicate, label, timeout=20):
    until=time.monotonic()+timeout
    while time.monotonic()<until:
        if predicate(): return
        time.sleep(.12)
    raise AssertionError("Timed out: "+label)


def close_room(page):
    if page.locator('#room-dialog').is_visible(): page.locator('#room-dialog [data-close]').click()


def go(page):
    started=time.monotonic()
    page.goto(BASE)
    page.wait_for_selector('#new-game-button')
    page.wait_for_function("document.querySelector('#board-host').dataset.assetsLoaded==='4'")
    page.wait_for_function("document.querySelector('#board-host').dataset.renderer==='3d'")
    report.setdefault('cold_board_load_seconds',[]).append(round(time.monotonic()-started,2))


def join(page, code, power, name):
    go(page)
    page.locator('#join-game-button').click()
    page.locator('#join-code').fill(code)
    page.locator('#join-form [name=name]').fill(name)
    page.locator('#join-power').select_option(power)
    page.locator('#join-form [type=submit]').click()
    page.wait_for_selector('#game-view:not([hidden])')
    wait_for(lambda: state(page).get('human')==(power or None), 'joined power')


def finish_negotiation(pages):
    for _ in range(25):
        current=state(pages[0])
        if current['mode']=='ORDERS':
            for page in pages:
                wait_for(lambda page=page: state(page)['mode']=='ORDERS','orders shared')
            return
        for page in pages:
            s=state(page)
            if s['mode']=='NEGO' and s['your_turn']:
                close_room(page)
                page.locator('#diplomacy-tab').click()
                page.locator('#ready-negotiation').click()
        time.sleep(.15)
    raise AssertionError('Negotiation did not reach orders')


def order(page, location, value):
    page.locator('#orders-tab').click()
    page.locator(f'#unit-list [data-unit="{location}"]').click()
    page.locator('#order-action').select_option(value.split()[2])
    page.locator('#order-choice').select_option(value)
    page.locator('#save-order').click()


def call(page, route, body):
    return page.evaluate("async ({route,body})=>{const r=await fetch(route,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});return {status:r.status,data:await r.json()}}", {"route":route,"body":body})


def main():
    started=time.monotonic()
    with sync_playwright() as pw:
        path=os.getenv('CHROMIUM_EXECUTABLE') or shutil.which('chromium')
        browser=pw.chromium.launch(**({'executable_path':path} if path else {}), args=['--disable-dev-shm-usage','--enable-unsafe-swiftshader'])
        contexts=[browser.new_context(viewport={"width":1600,"height":1050}) for _ in range(3)]
        host,guest,observer=[c.new_page() for c in contexts]
        for page in (host,guest,observer):
            page.set_default_timeout(30000)
            page.add_init_script("localStorage.setItem('diplomind.locale','en')")
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('dialog',lambda d:d.accept('browser-checkpoint') if d.type=='prompt' else d.accept())
        try:
            go(host)
            assert host.locator('#board-host').get_attribute('data-provinces')=='76'
            capture(host,'01-landing.png')
            host.locator('#new-game-button').click()
            host.keyboard.press('Escape')
            expect(host.locator('#setup-dialog')).not_to_be_visible()
            host.locator('#new-game-button').click()
            assert host.locator('#create-form [value=plus]').count()==0
            host.locator('#room-name').fill('Browser acceptance')
            host.locator('#owner-name').fill('Alice <b>France</b>')
            host.locator('#create-power').select_option('FRANCE')
            host.locator('#create-form [name=lang]').select_option('en')
            host.locator('#create-form [type=submit]').click()
            host.wait_for_selector('#game-view:not([hidden])')
            h=identity(host); code=h['code']
            join(guest,code,'GERMANY','Bob')
            join(observer,code,'','Observer')
            assert len({identity(p)['token'] for p in (host,guest,observer)})==3
            assert host.locator('#room-members b').count()==0
            check('3D assets, cancelable onboarding, distinct human identities and safe nicknames')
            host.locator('#timer-select').select_option('0')
            host.locator('#start-game').click()
            wait_for(lambda:state(guest).get('mode')=='NEGO','game began')
            assert state(host)['humans']==['FRANCE','GERMANY']
            before=state(host)['turn_id']
            assert call(host,'/api/room/start',{'token':h['token']})['status']==409
            assert state(host)['turn_id']==before
            assert not state(observer)['your_turn'] and state(observer)['legal']==[]
            check('mixed game starts once; observer has no seat or private controls')
            close_room(host); host.locator('#diplomacy-tab').click()
            host.locator('#new-private-button').click()
            host.locator('#private-form input[value=GERMANY]').check()
            host.locator('#private-form [type=submit]').click()
            expect(host.locator('#private-dialog')).not_to_be_visible()
            canary='FR-GER private: I will leave BUR open; please support Belgium.'
            host.locator('#message-input').fill(canary)
            host.locator('#send-message').click()
            expect(host.locator('#staged-messages')).to_contain_text(canary)
            assert canary not in json.dumps(state(guest)['channels'])
            assert canary not in json.dumps(state(observer))
            capture(host,'02-private-negotiation.png')
            finish_negotiation([host,guest])
            assert canary in json.dumps(state(guest)['channels'])
            assert canary not in json.dumps(state(observer))
            check('private message staged, delivered simultaneously, visible only to participants')
            # Plan through the real editor, edit/remove, choose pieces on the map, reload drafts.
            order(host,'PAR','A PAR - BUR')
            host.locator('#unit-list [data-unit=PAR]').click()
            host.locator('#remove-order').click()
            expect(host.locator('#unit-list [data-unit=PAR]')).not_to_contain_text('DRAFT')
            host.locator('#close-editor').click()
            host.locator('#view-2d').click()
            host.locator('#board-host g.unit[data-unit=PAR]').click()
            host.locator('#order-action').select_option('-')
            host.locator('#order-choice').select_option('A PAR - BUR')
            host.locator('#save-order').click()
            order(host,'MAR','A MAR - SPA')
            order(host,'BRE','F BRE - MAO')
            host.locator('#view-3d').click()
            capture(host,'03-orders-3d.png')
            token_before=identity(host)['token']; host.reload()
            host.wait_for_selector('#game-view:not([hidden])')
            host.locator('#orders-tab').click()
            expect(host.locator('#order-count')).to_have_text('3')
            assert identity(host)['token']==token_before
            check('2D map picking, draft editing/removal, 3D arrows and refresh recovery')
            # Offline/reconnect keeps locally drafted intent and server identity.
            contexts[0].set_offline(True)
            wait_for(lambda:'Reconnecting' in host.locator('#connection-status').inner_text(),'offline indicator')
            contexts[0].set_offline(False)
            wait_for(lambda:'Live' in host.locator('#connection-status').inner_text(),'reconnected')
            expect(host.locator('#order-count')).to_have_text('3')
            phase=state(host)['phase']
            host.locator('#submit-orders').click()
            wait_for(lambda:state(host)['order_submitted'],'host ready')
            assert state(host)['phase']==phase and 'GERMANY' in state(host)['order_pending']
            host.locator('#cancel-orders').click()
            wait_for(lambda:not state(host)['order_submitted'],'host withdrew')
            host.locator('#submit-orders').click()
            wait_for(lambda:state(host)['order_submitted'],'host ready again')
            check('offline recovery and submit/withdraw waits for the other human')
            # Same-room checkpoint retains pending orders, pauses, and preserves identities.
            host.locator('#room-button').click();host.locator('#save-game').click()
            host.locator('#show-saves').click()
            host.locator('[data-save=browser-checkpoint]').click()
            wait_for(lambda:state(host)['status']=='paused','checkpoint paused')
            assert state(host)['submitted_orders']==['A PAR - BUR','A MAR - SPA','F BRE - MAO']
            assert identity(host)['token']==token_before
            host.locator('#pause-game').click()
            wait_for(lambda:state(host)['status']=='playing','resumed')
            close_room(host)
            guest.locator('#orders-tab').click()
            guest.locator('#submit-orders').click()
            wait_for(lambda:state(host)['phase']!=phase,'adjudication')
            wait_for(lambda:host.locator('#phase-title').inner_text()!= 'Spring 1901','UI next phase')
            assert state(host)['phase']=='F1901M'
            check('checkpoint restores sealed orders and identities; two-human adjudication reaches autumn')
            # Complete the autumn season and any human retreats/adjustments through visible UI.
            phases=[phase,state(host)['phase']]
            for _ in range(12):
                current=state(host)
                if current['phase'].startswith('S1902'): break
                if current['mode']=='NEGO': finish_negotiation([host,guest])
                for page in (host,guest):
                    s=state(page)
                    if s['mode']=='ORDERS' and s['human'] in s['order_pending'] and not s['order_submitted']:
                        page.locator('#orders-tab').click();page.locator('#submit-orders').click()
                time.sleep(.15)
                if state(host)['phase'] not in phases: phases.append(state(host)['phase'])
            assert state(host)['phase'].startswith('S1902'),state(host)['phase']
            report['phases']=phases
            capture(host,'04-year-two.png')
            check('full spring/autumn/retreat-or-build loop reaches spring 1902')
            host.set_viewport_size({'width':390,'height':844})
            capture(host,'05-mobile.png')
            assert host.evaluate('document.documentElement.scrollWidth <= innerWidth+2')
            check('mobile layout fits without horizontal overflow')
            assert not errors,errors
            report['page_errors']=errors;report['result']='PASS'
            check('no uncaught browser exceptions')
            host.locator('#room-button').click();host.locator('#end-game').click()
        except Exception:
            report['result']='FAIL';report['failure']=traceback.format_exc();report['page_errors']=errors
            for index,page in enumerate((host,guest,observer)):
                try:
                    page.screenshot(path=str(OUT/f'failure-{index}.png'),full_page=True)
                    (OUT/f'failure-{index}.txt').write_text(page.url+'\n'+page.locator('body').inner_text())
                except Exception:pass
            raise
        finally:
            report['duration_seconds']=round(time.monotonic()-started,2)
            (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
            browser.close()

if __name__=='__main__':
    main()
