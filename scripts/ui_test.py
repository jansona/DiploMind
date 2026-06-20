"""真浏览器端到端验: 人开局即可发(不等AI), 空发拒, 双发幂等, 切tab, 私聊。需先起服 :8740。"""
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    b = pw.chromium.launch(); pg = b.new_page(); pg.goto("http://localhost:8740")
    pg.wait_for_function("()=>document.querySelector('#st').textContent.includes('轮到你')", timeout=20000)
    print("✓ 开局即轮到我(不等AI)")
    assert not pg.query_selector("#bs").is_disabled()
    pg.fill("#t", "")  ; pg.click("#bs"); assert "空" in pg.text_content("#st"); print("✓ 空消息被拦")
    pg.fill("#t", "大家好"); pg.click("#bs")
    pg.wait_for_function("()=>document.querySelector('#bs').disabled", timeout=5000); print("✓ 发后即禁用")
    assert pg.query_selector("#bs").is_disabled(); print("✓ 双发被禁(轮末统一投递)")
    pg.on("dialog", lambda d: d.accept("GERMANY"))
    pg.click("text=+私聊"); pg.wait_for_timeout(3000)
    tabs = pg.eval_on_selector_all("#tabs button", "els=>els.map(e=>e.textContent)")
    assert "FRANCE·GERMANY" in tabs; pg.click("text=FRANCE·GERMANY"); print("✓ 私聊tab可切:", tabs)
    b.close(); print("ALL PASS")
