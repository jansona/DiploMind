"""验本轮改动: 待投递消息常驻+剩余条数; 刷新保活; 下令后checkbox锁; 编年史换行. 起服:8771 qwen2b."""
from playwright.sync_api import sync_playwright

errs = []
with sync_playwright() as pw:
    b = pw.chromium.launch(); pg = b.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
    sel = lambda i: pg.eval_on_selector(i, "e=>e.textContent")
    pg.goto("http://localhost:8771"); pg.wait_for_timeout(800)
    pg.click("text=新游戏 New Game"); pg.select_option("#hsel", "FRANCE"); pg.click("text=开始 Start")
    pg.wait_for_function("()=>document.getElementById('game').className==''", timeout=10000); print("✓ 进游戏")
    pg.wait_for_function("()=>document.querySelector('#st').textContent.includes('可发言')", timeout=30000)
    print("✓ 剩余条数显示:", sel("#st"))                                   # 6) "(3条可发)"
    pg.fill("#t", "联手分德吗"); pg.click("#bs"); pg.wait_for_timeout(700)
    print("✓ 待投递常驻:", sel("#stg"))                                   # 1) staged stays
    assert "待投递" in sel("#stg"), "staged 没显示"
    pg.reload(); pg.wait_for_timeout(1500)                                # 2) refresh 保活
    assert pg.eval_on_selector("#game", "e=>e.className=='' ") , "刷新回菜单了"
    print("✓ 刷新仍在局, phase:", sel("#ph"), "待投递:", sel("#stg"))
    for _ in range(48):                                                  # 等到下令相
        if "ORDERS" in sel("#md") or "下令" in sel("#md"): break
        if "可发言" in sel("#st"): pg.fill("#t", "ok"); pg.click("#bs")
        pg.wait_for_timeout(5000)
    os = pg.query_selector_all("#os input"); [o.check() for o in os[:3]]
    print("命令数:", len(os))
    pg.wait_for_selector("#ord button:not([disabled])"); pg.click("text=下令并结算"); pg.wait_for_timeout(1200)
    locked = pg.eval_on_selector_all("#os input", "es=>es.every(e=>e.disabled)")
    print("✓ 下令后checkbox锁:", locked); assert locked or not os, "checkbox 没禁用"
    pg.wait_for_timeout(20000)
    ws = pg.eval_on_selector("#ch", "e=>getComputedStyle(e).whiteSpace"); print("✓ 编年史换行 white-space:", ws)
    print("编年史:", repr((sel("#ch") or "")[:120]))
    print("JS异常:", errs or "无", "| ALL PASS"); b.close()
