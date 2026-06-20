"""真浏览器端到端验: 人开局即可发(不等AI), 空发拒, 双发幂等, 切tab, 私聊。需先起服 :8744。"""
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    b = pw.chromium.launch(); pg = b.new_page(); pg.goto("http://localhost:8744")
    pg.wait_for_function("()=>document.querySelector('#st').textContent.includes('可发言')", timeout=20000)
    print("✓ 开局即可发(不等AI)")
    assert not pg.query_selector("#bs").is_disabled()
    pg.fill("#t", "")  ; pg.click("#bs"); assert "空" in pg.text_content("#st"); print("✓ 空消息被拦")
    pg.fill("#t", "大家好"); pg.click("#bs")
    pg.wait_for_function("()=>document.querySelector('#bs').disabled", timeout=5000); print("✓ 发后即禁用")
    pg.wait_for_function("()=>document.querySelector('#st').textContent.includes('待投递')", timeout=5000)
    print("✓ 发后进待投递栏(等全员)")
    pg.on("dialog", lambda d: d.accept("GERMANY"))
    pg.click("text=+私聊"); pg.wait_for_timeout(3000)
    tabs = pg.eval_on_selector_all("#tabs button", "els=>els.map(e=>e.textContent)")
    assert "FRANCE·GERMANY" in tabs; pg.click("text=FRANCE·GERMANY"); print("✓ 私聊tab可切:", tabs)
    pg.click("text=刷新关系/背叛"); pg.wait_for_timeout(500); assert "关系" in pg.text_content("#rel"); print("✓ 关系/背叛面板")
    pg.click("text=看内脏"); pg.wait_for_timeout(500); assert "AUSTRIA" in pg.text_content("#dbgv"); print("✓ 观战内脏(意图/记忆/暗盘)")
    assert "性格" in pg.text_content("#per"); print("✓ 性格显示")
    pg.click("text=Guide"); pg.wait_for_timeout(500); assert "命令缩写" in pg.text_content("#gv") and "PAR" in pg.text_content("#gv"); print("✓ Guide:地名+命令缩写表")
    b.close(); print("ALL PASS")
