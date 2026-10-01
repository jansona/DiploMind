"""Mock-only private-compose race regression in real Chromium.

Run against a fresh server configured with conf/mock.json. This script refuses
any provider other than mock before creating a table. All messages are synthetic.
No credential files, external services, model inference or production rooms.

DIPLOMIND_E2E_URL overrides http://127.0.0.1:8731. Reports are written to
artifacts/message-race/. MESSAGE_RACE_DIAGNOSE=1 records baseline failures without
stopping before the remaining scenarios. Tokens are excluded from the report.
"""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
import shutil
import time
import traceback
from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts' / 'message-race'
BASE = os.getenv('DIPLOMIND_E2E_URL', 'http://127.0.0.1:8731')
REPORT = {'provider': 'mock', 'scenarios': [], 'errors': [], 'requests': [], 'checks': []}

async def tick(predicate, timeout=8):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if await predicate(): return
        await asyncio.sleep(.05)
    raise AssertionError('Timed out waiting for acknowledged UI state')

async def snapshot(page):
    return await page.evaluate("""() => ({input:document.querySelector('#message-input').value,
      disabled:document.querySelector('#message-input').disabled,
      sendDisabled:document.querySelector('#send-message').disabled,
      modal:document.querySelector('#private-dialog').open,
      channel:document.querySelector('#channel-list [aria-selected=true]')?.dataset.channel,
      recipients:document.querySelector('#recipient-banner').textContent,
      staged:document.querySelector('#staged-messages').textContent,
      status:document.querySelector('#message-status')?.textContent,
      turn:window._last?.turn_id,sent:window._last?.sent})""")

async def open_private(page, power):
    await page.locator('#new-private-button').click()
    await page.locator(f'#private-form input[value={power}]').check()
    await page.locator('#private-form [type=submit]').click()

async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    host_token = None
    started = time.monotonic()
    async with async_playwright() as pw:
        api = await pw.request.new_context(base_url=BASE)
        providers = await (await api.get('/api/providers')).json()
        if providers.get('selected') != 'mock':
            raise RuntimeError('SAFETY STOP: /api/providers is not mock; no room created or gameplay action taken')
        async def post(route, body):
            response = await api.post(route, data=body)
            value = await response.json()
            if response.status >= 400: raise AssertionError(f'{route}: {response.status} {value}')
            return value
        async def state(token):
            return await (await api.get('/api/state', params={'token': token})).json()
        host_id = await post('/api/room/create', {'name': 'Synthetic compose-race regression', 'owner_name': 'Race France', 'power': 'FRANCE', 'lang': 'en', 'game_mode': 'classic'})
        host_token = host_id['token']
        guest_id = await post('/api/room/join', {'code': host_id['code'], 'name': 'Race Germany', 'power': 'GERMANY'})
        observer_id = await post('/api/room/join', {'code': host_id['code'], 'name': 'Race Observer', 'power': None})
        await post('/api/room/secs', {'token': host_token, 'secs': 0})
        await post('/api/room/start', {'token': host_token})
        browser = await pw.chromium.launch(executable_path=os.getenv('CHROMIUM_EXECUTABLE') or shutil.which('chromium'), args=['--disable-dev-shm-usage', '--enable-unsafe-swiftshader'])
        contexts = []
        try:
            async def client(identity):
                context = await browser.new_context(viewport={'width': 1440, 'height': 1050})
                contexts.append(context)
                await context.add_init_script("localStorage.setItem('diplomind.locale','en');sessionStorage.setItem('diplomind.session'," + json.dumps(json.dumps({'token': identity['token'], 'code': identity['code']})) + ");")
                page = await context.new_page()
                page.set_default_timeout(15000)
                page.on('pageerror', lambda error: REPORT['errors'].append(str(error)))
                page.on('dialog', lambda dialog: dialog.accept())
                await page.goto(BASE)
                await page.locator('#game-view:not([hidden])').wait_for()
                await page.locator('#diplomacy-tab').click()
                return page
            host = await client(host_id)
            guest = await client(guest_id)
            await host.wait_for_function('window._last?.your_turn === true')
            async def record_request(request):
                if request.method == 'POST' and request.url.split('?')[0].endswith(('/api/open', '/api/say')):
                    data = request.post_data_json or {}
                    data.pop('token', None)
                    REPORT['requests'].append({'route': request.url.split('/')[-1], 'body': data})
            host.on('request', record_request)
            failures = []
            delayed = {'open': False, 'say': False}
            async def latency(route):
                kind = route.request.url.rsplit('/', 1)[-1]
                if delayed.get(kind):
                    response = await route.fetch()
                    await asyncio.sleep(.65)
                    await route.fulfill(response=response)
                else: await route.continue_()
            await host.route('**/api/open', latency)
            await host.route('**/api/say', latency)
            for index, (power, slow) in enumerate([('GERMANY', False), ('GERMANY', True), ('ENGLAND', True)]):
                text = f'RACE-{index + 1}-{power}: synthetic private proposal.'
                delayed['open'] = slow
                before = await state(host_token)
                await open_private(host, power)
                pending = await snapshot(host)
                await host.locator('#message-input').fill(text)
                filled = await snapshot(host)
                await host.locator('#send-message').click()
                await asyncio.sleep(.9)
                after = await state(host_token)
                ui = await snapshot(host)
                matching = [x for x in REPORT['requests'] if x['route'] == 'say' and x['body'].get('content') == text]
                ok = text in after.get('staged_msgs', []) and len(matching) == 1 and matching[0]['body'].get('recipient') == [power] and matching[0]['body'].get('scope') == 'private'
                REPORT['scenarios'].append({'name': 'rapid-existing' if index == 1 else 'rapid-new', 'delay_open_ack_ms': 650 if slow else 0, 'text': text, 'before_sent': before.get('sent'), 'pending': pending, 'filled': filled, 'after': ui, 'server_sent': after.get('sent'), 'result': 'PASS' if ok else 'FAIL'})
                if not ok: failures.append(f'Private message {index + 1} was not acknowledged exactly once to {power}')
                if failures and os.getenv('MESSAGE_RACE_DIAGNOSE') != '1': break
            REPORT['checks'].append('three messages per round route only to selected private recipients' if not failures else 'baseline lost-send reproduced')
            await host.screenshot(path=str(OUT / 'compose.png'), full_page=True)
            if not failures:
                await guest.locator('#ready-negotiation').click()
                async def next_round(): return (await state(host_token))['turn_id'] != before['turn_id']
                await tick(next_round)
                s = await state(host_token)
                assert s['mode'] == 'NEGO', 'Need second mock negotiation round for compose draft tests'
                await host.wait_for_function('window._last?.your_turn === true')
                await open_private(host, 'GERMANY')
                await host.locator('#private-dialog').wait_for(state='hidden')
                await host.locator('#message-input').fill('UNSENT-GERMANY: keep this channel draft')
                await host.locator('#channel-list [data-channel="群聊"]').click()
                await expect(host.locator('#message-input')).to_have_value('')
                await host.locator('#message-input').fill('UNSENT-PUBLIC: distinct public draft')
                await host.locator('#channel-list [data-channel="FRANCE·GERMANY"]').click()
                await expect(host.locator('#message-input')).to_have_value('UNSENT-GERMANY: keep this channel draft')
                await host.reload()
                await host.locator('#game-view:not([hidden])').wait_for()
                await host.locator('#diplomacy-tab').click()
                await expect(host.locator('#message-input')).to_have_value('UNSENT-GERMANY: keep this channel draft')
                REPORT['checks'].append('separate channel drafts survive switching and refresh without sending')
                # Send with a delayed acknowledgement, then switch channels while the request is pending.
                delayed['say'] = True
                await host.locator('#message-input').fill('ACK-GERMANY: do not clear another channel')
                await host.locator('#send-message').click()
                await host.locator('#channel-list [data-channel="群聊"]').click()
                await expect(host.locator('#message-input')).to_have_value('UNSENT-PUBLIC: distinct public draft')
                await asyncio.sleep(.9)
                await expect(host.locator('#message-input')).to_have_value('UNSENT-PUBLIC: distinct public draft')
                s = await state(host_token)
                assert 'ACK-GERMANY: do not clear another channel' in s['staged_msgs']
                REPORT['checks'].append('late acknowledgement clears only its submitted channel draft')
                # Failed network delivery must preserve text. A retry is explicit and uses the same id.
                delayed['say'] = False
                async def abort_once(route): await route.abort('failed')
                await host.route('**/api/say', abort_once, times=1)
                await host.locator('#message-input').fill('RETRY-PUBLIC: recover after a network failure')
                await host.locator('#send-message').click()
                await expect(host.locator('#message-input')).to_have_value('RETRY-PUBLIC: recover after a network failure')
                await expect(host.locator('#send-message')).to_be_enabled()
                await host.locator('#send-message').click()
                await expect(host.locator('#message-input')).to_have_value('')
                retries = [x for x in REPORT['requests'] if x['route'] == 'say' and x['body'].get('content') == 'RETRY-PUBLIC: recover after a network failure']
                assert len(retries) == 2 and retries[0]['body']['request_id'] == retries[1]['body']['request_id']
                REPORT['checks'].append('failed send preserves draft and explicit retry reuses request identity')
                # Cancelling a pending channel open must not steal the composer later.
                delayed['open'] = True
                await host.locator('#message-input').fill('CANCEL-PUBLIC: keep my current destination')
                await open_private(host, 'AUSTRIA')
                await host.keyboard.press('Escape')
                await asyncio.sleep(.9)
                assert (await snapshot(host))['channel'] == '群聊'
                await expect(host.locator('#message-input')).to_have_value('CANCEL-PUBLIC: keep my current destination')
                REPORT['checks'].append('cancelled slow private open does not change the current channel or draft')
                # A newer draft typed while an earlier message is awaiting ack survives.
                delayed['say'] = True
                await host.locator('#message-input').fill('ACK-OLD-PUBLIC: only this text is submitted')
                await host.locator('#send-message').click()
                await host.locator('#message-input').fill('NEWER-PUBLIC: keep this text unsent')
                await asyncio.sleep(.9)
                await expect(host.locator('#message-input')).to_have_value('NEWER-PUBLIC: keep this text unsent')
                s = await state(host_token)
                assert 'ACK-OLD-PUBLIC: only this text is submitted' in s['staged_msgs']
                assert 'NEWER-PUBLIC: keep this text unsent' not in s['staged_msgs']
                await expect(host.locator('#message-status')).to_contain_text('newer draft is still unsent')
                REPORT['checks'].append('late acknowledgement preserves newer text in the same channel with explicit status')
                # Round one deliveries are visible only to Germany for Germany-private content.
                g = await state(guest_id['token']); o = await state(observer_id['token'])
                german_msgs = [x['text'] for x in REPORT['scenarios'] if 'GERMANY' in x['text']]
                english_msgs = [x['text'] for x in REPORT['scenarios'] if 'ENGLAND' in x['text']]
                assert all(x in json.dumps(g['channels']) for x in german_msgs)
                assert all(x not in json.dumps(g['channels']) for x in english_msgs)
                assert all(x not in json.dumps(o['channels']) for x in german_msgs + english_msgs)
                REPORT['checks'].append('private deliveries exclude wrong recipient and observer')
                assert not REPORT['errors'], REPORT['errors']
            REPORT['result'] = 'FAIL' if failures else 'PASS'
            REPORT['failures'] = failures
            if failures: raise AssertionError('; '.join(failures))
        except Exception:
            REPORT['result'] = 'FAIL'; REPORT['failure'] = traceback.format_exc()
            raise
        finally:
            try: await post('/api/room/end', {'token': host_token})
            except Exception: pass
            REPORT['duration_seconds'] = round(time.monotonic() - started, 2)
            (OUT / 'report.json').write_text(json.dumps(REPORT, indent=2, ensure_ascii=False))
            await browser.close(); await api.dispose()
            print(json.dumps({k: v for k, v in REPORT.items() if k not in {'requests', 'scenarios'}}, ensure_ascii=False), flush=True)

if __name__ == '__main__':
    asyncio.run(main())
