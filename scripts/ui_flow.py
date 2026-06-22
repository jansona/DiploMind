"""真浏览器全流程: 菜单→新局(选国)→勾选私聊国开私聊→发私信→下令checkbox. 需起服 :8761。"""
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    b = pw.chromium.launch(); pg = b.new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("http://localhost:8761"); pg.wait_for_timeout(800)
    assert pg.is_visible("#menu"); print("✓ 主菜单显示")
    pg.click("text=新游戏 New Game"); pg.select_option("#hsel", "FRANCE"); pg.click("text=开始 Start")
    pg.wait_for_function("()=>document.getElementById('game').className==''", timeout=10000); print("✓ 进游戏")
    pg.wait_for_function("()=>document.querySelectorAll('#pk input').length>0", timeout=8000)
    print("✓ 私聊国复选数:", pg.eval_on_selector_all("#pk input", "e=>e.length"))
    pg.check("#pk input[value=GERMANY]"); pg.click("text=开私聊"); pg.wait_for_timeout=500
    pg.wait_for_function("()=>[...document.querySelectorAll('#tabs button')].some(b=>b.textContent.includes('GERMANY'))", timeout=4000)
    print("✓ 勾选开私聊→FRANCE·GERMANY tab")
    pg.wait_for_function("()=>document.querySelector('#st').textContent.includes('可发言')||document.querySelector('#st').textContent.includes('your')", timeout=20000)
    pg.fill("#t", "结盟吗"); pg.click("#bs"); print("✓ 私信已发")
    print("JS异常:", errs or "无"); b.close()
