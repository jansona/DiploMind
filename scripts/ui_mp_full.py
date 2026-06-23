"""2人deepseek完整试玩: 建房+加入, 两人各相谈判跳过+下令并结算, 跑到1903, 验界面/无卡死. 起服:8785 deepseek."""
import time
from playwright.sync_api import sync_playwright

B = "http://localhost:8785"; errs = []
with sync_playwright() as pw:
    br = pw.chromium.launch(); H = br.new_page(); G = br.new_page()
    for p in (H, G): p.on("dialog", lambda d: d.accept()); p.on("pageerror", lambda e: errs.append(str(e)))
    sel = lambda p, i: p.eval_on_selector(i, "e=>e.textContent")
    H.goto(B); H.wait_for_timeout(500); H.click("text=新游戏 New Game"); H.fill("#rn", "T"); H.select_option("#hsel", "FRANCE"); H.click("text=建房 Create")
    H.wait_for_function("()=>game.className==''"); code = sel(H, "#rc")
    G.goto(B); G.wait_for_timeout(400); G.click("text=新游戏 New Game"); G.fill("#jc", code); G.select_option("#jp", "GERMANY"); G.click("text=加入 Join")
    G.wait_for_function("()=>game.className==''"); H.click("text=开局")
    H.wait_for_function("()=>document.querySelector('#h').textContent=='FRANCE'", timeout=15000); print("✓ 双人进局", code)

    def act(p):                              # one player: skip nego if able, submit orders if in ORDERS
        if "可发言" in (sel(p, "#st") or ""): p.click("#bk")
        if "block" in p.eval_on_selector("#ord", "e=>getComputedStyle(e).display!='none'?'block':'no'") or sel(p, "#md").find("ORDERS") >= 0:
            for o in p.query_selector_all("#os input")[:3]:
                try: o.check()
                except Exception: pass
            b = p.query_selector("#ord button:not([disabled])")
            if b: b.click()

    for _ in range(120):
        if "1903" in sel(H, "#ph"): break
        for p in (H, G):
            try: act(p)
            except Exception: pass
        time.sleep(4)
    print("达到:", sel(H, "#ph"), "中心:", sel(H, "#c")); print("JS异常:", errs[:2] or "无"); H.screenshot(path="/tmp/mp_full.png"); br.close()
