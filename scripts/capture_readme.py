"""Real UI screenshots from isolated mock contexts; no credentials or private chats."""
from pathlib import Path
import json,shutil,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from playwright.sync_api import sync_playwright,expect
from scripts import e2e_mixed as flow
OUT=ROOT/'docs/screenshots'
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 with sync_playwright() as pw:
  browser=pw.chromium.launch(headless=True,executable_path=shutil.which('chromium'),args=['--disable-dev-shm-usage'])
  contexts=[browser.new_context(viewport={'width':1600,'height':1080}) for _ in range(2)]
  host,guest=[c.new_page() for c in contexts]
  for page in (host,guest):
   page.set_default_timeout(30000);page.add_init_script("localStorage.setItem('diplomind.locale','zh')")
  flow.go(host)
  assert host.evaluate("async()=>(await(await fetch('/api/providers')).json()).selected")=='mock'
  host.screenshot(path=str(OUT/'lobby.png'),full_page=True)
  host.locator('#new-game-button').click();host.locator('#room-name').fill('Classic · 离线演示');host.locator('#owner-name').fill('法国玩家')
  host.locator('#create-power').select_option('FRANCE');host.locator('#create-form [name=lang]').select_option('zh-Hans');host.locator('#create-form [type=submit]').click()
  host.wait_for_selector('#game-view:not([hidden])');flow.join(guest,flow.state(host)['room'],'GERMANY','德国玩家')
  host.locator('#start-game').click();flow.close_room(host);flow.finish_negotiation([host,guest])
  for loc,value in [('PAR','A PAR - PIC'),('MAR','A MAR - SPA'),('BRE','F BRE - MAO')]:flow.order(host,loc,value)
  if host.locator('#close-editor').is_visible():host.locator('#close-editor').click()
  host.locator('#view-3d').click();expect(host.locator('.toast')).to_have_count(0,timeout=10000)
  host.screenshot(path=str(OUT/'classic-table.png'),full_page=True)
  host.set_viewport_size({'width':430,'height':932});host.locator('#orders-tab').click();host.screenshot(path=str(OUT/'mobile-orders.png'),full_page=True)
  (ROOT/'artifacts/publish/capture.json').write_text(json.dumps({'provider':'mock','assets_loaded':host.locator('#board-host').get_attribute('data-assets-loaded'),'provinces':host.locator('#board-host').get_attribute('data-provinces'),'private_messages_sent':0}))
  browser.close()
if __name__=='__main__':main()
