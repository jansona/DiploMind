"""debug模式模拟人类多轮: 群发→私聊→勾选下令→结算, 验已选显示/无碎字/无JS异常. 起服:8757 DEBUG=1."""
from playwright.sync_api import sync_playwright

errs = []
with sync_playwright() as pw:
    b = pw.chromium.launch(); pg = b.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("http://localhost:8757"); pg.wait_for_timeout(700)
    pg.click("text=新游戏 New Game"); pg.click("text=开始 Start")
    pg.wait_for_function("()=>document.getElementById('game').className==''", timeout=10000)
    for ph in range(4):                                              # 玩几相
        for r in range(6):
            pg.wait_for_timeout(2500); s = lambda i: pg.eval_on_selector(i, "e=>e.textContent")
            if "ORDERS" in s("#md") or "下令" in s("#md"): break
            if "可发言" in s("#st") or "your" in s("#st"):
                pg.fill("#t", f"R{ph}-{r} hi"); pg.click("#bs"); pg.wait_for_timeout(400)
        # orders: check first 3 + verify selected shown, no leaked text
        opts = pg.query_selector_all("#os input")
        for o in opts[:3]: o.check()
        sel = pg.eval_on_selector("#osel", "e=>e.textContent")
        assert "value)" not in pg.eval_on_selector("#os","e=>e.innerHTML"), "leaked JS text!"
        print(f"相{ph} 已选:", sel)
        pg.click("text=下令并结算"); pg.wait_for_timeout(8000)
    pg.click("text=看内脏"); pg.wait_for_timeout(800)
    print("内脏有数据:", len(pg.eval_on_selector("#dbgv","e=>e.textContent"))>50, "| JS异常:", errs or "无"); b.close()
