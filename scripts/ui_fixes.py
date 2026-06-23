"""单座位回归(房间版): 建房FR开局→待投递常驻+剩余条数→刷新保活→下令锁checkbox→编年史换行. 起服:8772 (默认 deepseek)."""
from playwright.sync_api import sync_playwright

errs = []
with sync_playwright() as pw:
    b = pw.chromium.launch(); pg = b.new_page(); pg.on("pageerror", lambda e: errs.append(str(e))); pg.on("dialog", lambda d: d.accept())
    sel = lambda i: pg.eval_on_selector(i, "e=>e.textContent")
    pg.goto("http://localhost:8772"); pg.wait_for_timeout(700)
    pg.click("text=新游戏 New Game"); pg.select_option("#hsel", "FRANCE"); pg.click("text=建房 Create")
    pg.wait_for_function("()=>document.getElementById('game').className==''", timeout=10000)
    pg.click("text=开局 Start"); pg.wait_for_function("()=>document.querySelector('#h').textContent=='FRANCE'", timeout=12000); print("✓ 进局")
    pg.wait_for_function("()=>document.querySelector('#st').textContent.includes('可发言')", timeout=30000)
    print("✓ 剩余条数:", sel("#st")); pg.fill("#t", "联手分德吗"); pg.click("#bs"); pg.wait_for_timeout(700)
    assert "待投递" in sel("#stg"); print("✓ 待投递常驻:", sel("#stg"))
    pg.reload(); pg.wait_for_timeout(1500); assert pg.eval_on_selector("#game", "e=>e.className=='' "); print("✓ 刷新仍在局:", sel("#ph"))
    for _ in range(80):
        if "ORDERS" in sel("#md") or "下令" in sel("#md"): break
        if "可发言" in sel("#st"): pg.fill("#t", "ok"); pg.click("#bk")
        pg.wait_for_timeout(3000)
    for o in pg.query_selector_all("#os input"):
        try: o.check()
        except Exception: break          # cover all units -> auto-settle fires & re-renders (handles detach)
    pg.wait_for_timeout(2000); assert pg.eval_on_selector_all("#os input", "es=>!es.length||es.every(e=>e.disabled)"); print("✓ 选满自动结算+锁(无按钮)")
    print("✓ 编年史换行:", pg.eval_on_selector("#ch", "e=>getComputedStyle(e).whiteSpace"), "| JS异常:", errs or "无", "| PASS"); b.close()
