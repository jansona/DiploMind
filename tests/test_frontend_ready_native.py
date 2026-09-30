"""Real Chromium event ordering for the production Ready handlers, no server/API.

Skipped where Chromium is not installed; Node handler regressions are portable.
"""
from pathlib import Path
import os
import shutil

import pytest


@pytest.mark.skipif(os.getenv('DIPLOMIND_NATIVE_BROWSER_TESTS') != '1' or not shutil.which('chromium'),
                    reason='Opt-in native browser regression: DIPLOMIND_NATIVE_BROWSER_TESTS=1 and installed Chromium required')
def test_native_ready_gestures_do_not_cross_rounds():
    from playwright.sync_api import sync_playwright
    source = (Path(__file__).parents[1] / 'diplomind/static/app.js').read_text()
    start = source.index('function captureReadyInteraction(')
    handlers = source[start:source.index('\nfunction openPrivate()', start)]
    html = '''<button id="ready">Ready</button><script>
let state={turn_id:"round-1",your_turn:true,human_done:false},busy=new Set(),readyActivation=null,readyHeldKey=null;
window.sent=[];window.notices=[];window.advanceOnReady=false;
function composerAvailable(){return state.your_turn}
function actionBody(extra){return {turn_id:state.turn_id,request_id:String(window.sent.length),...extra}}
async function act(key,path,body){window.sent.push(body);if(window.advanceOnReady)state={...state,turn_id:"round-2"};return {ok:true}}
function toast(...args){window.notices.push(args)}
''' + handlers + '''
const button=document.getElementById('ready');button.addEventListener('pointerdown',captureReadyInteraction);button.addEventListener('keydown',captureReadyInteraction);button.addEventListener('keyup',releaseReadyKey);button.addEventListener('pointercancel',cancelReadyInteraction);button.addEventListener('blur',cancelReadyInteraction);button.onclick=readyNegotiation;
window.advance=()=>{state={...state,turn_id:"round-2"}};
</script>'''
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=shutil.which('chromium'), headless=True)
        page = browser.new_page()
        def reset():
            page.goto('about:blank')
            page.set_content(html)
        reset()
        box = page.locator('#ready').bounding_box()
        page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        page.mouse.down()
        page.evaluate('window.advance()')
        page.mouse.up()
        assert page.evaluate('window.sent.length') == 0
        reset()
        page.locator('#ready').focus()
        page.keyboard.down('Space')
        page.evaluate('window.advance()')
        page.keyboard.up('Space')
        assert page.evaluate('window.sent.length') == 0
        reset()
        page.evaluate('window.advanceOnReady=true')
        page.locator('#ready').dblclick()
        assert page.evaluate('window.sent.map(x=>x.turn_id)') == ['round-1']
        reset()
        page.locator('#ready').click()
        page.evaluate('window.advance()')
        page.locator('#ready').click()
        assert page.evaluate('window.sent.map(x=>x.turn_id)') == ['round-1', 'round-2']
        reset()
        page.locator('#ready').focus()
        page.keyboard.down('Enter')
        page.evaluate('window.advance()')
        page.keyboard.down('Enter')
        page.keyboard.up('Enter')
        assert page.evaluate('window.sent.map(x=>x.turn_id)') == ['round-1']
        browser.close()
