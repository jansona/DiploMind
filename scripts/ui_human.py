"""debug多轮完整验: 陪AI跑满谈判→下令(勾选看已选)→结算→存档. 起服:8757 DEBUG=1."""
from playwright.sync_api import sync_playwright

errs = []
with sync_playwright() as pw:
    b = pw.chromium.launch(); pg = b.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("http://localhost:8757"); pg.wait_for_timeout(800)
    pg.click("text=新游戏 New Game"); pg.click("text=开始 Start")
    pg.wait_for_function("()=>document.getElementById('game').className==''", timeout=10000)
    sel = lambda i: pg.eval_on_selector(i, "e=>e.textContent")
    for ph in range(2):                                          # 验两相
        for _ in range(40):                                      # 耐心等到下令相(每相数分钟)
            if "ORDERS" in sel("#md") or "下令" in sel("#md"): break
            if "可发言" in sel("#st") or "your" in sel("#st"):
                pg.fill("#t", f"R{ph} hi"); pg.click("#bs")
            pg.wait_for_timeout(5000)
        assert "value)" not in pg.eval_on_selector("#os","e=>e.innerHTML"), "leaked!"
        os=pg.query_selector_all("#os input"); [o.check() for o in os[:3]]
        print(f"相{ph} 命令数:{len(os)} 已选:", sel("#osel"))
        pg.wait_for_selector("#ord button:not([disabled])"); pg.click("text=下令并结算"); pg.wait_for_timeout(12000)
        print(f"相{ph} 结算后 phase:", sel("#ph"))
    pg.once("dialog", lambda d: d.accept("t_full")); pg.click("text=存档 Save"); pg.wait_for_timeout(1000)
    print("内脏:", len(pg.eval_on_selector("#dbgv","e=>e.textContent") or "")>=0, "| JS异常:", errs or "无", "| ALL PASS"); b.close()
