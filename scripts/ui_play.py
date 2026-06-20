"""playwright 真浏览器模拟玩到1903: 人每轮跳过/到下令选合法提交, 周期看内脏抓状态异常+JS报错。"""
from playwright.sync_api import sync_playwright

errs = []
with sync_playwright() as pw:
    b = pw.chromium.launch(); pg = b.new_page()
    pg.on("pageerror", lambda e: errs.append(str(e)))                # 抓前端JS异常
    pg.goto("http://localhost:8746")
    pg.wait_for_function("()=>document.querySelector('#st')&&document.querySelector('#ph').textContent!=''", timeout=20000)
    seen = set()
    for _ in range(400):                                             # 跑到1903或上限
        ph = pg.eval_on_selector("#ph", "e=>e.textContent")
        md = pg.eval_on_selector("#md", "e=>e.textContent")
        if ph not in seen: seen.add(ph); print("相:", ph, md, "| 内脏:", "ok" if "persona" in (pg.eval_on_selector("#dbgv","e=>e.textContent") or "或空") else "—")
        if "1903" in ph: print("到1903✓"); break
        if md == "ORDERS":
            pg.eval_on_selector_all("#os option", "os=>os.forEach((o,i)=>o.selected=i<3)")
            pg.wait_for_selector("#ord button:not([disabled])", timeout=10000); pg.click("text=下令并结算")
            pg.wait_for_function("()=>document.querySelector('#md').textContent!='ORDERS'", timeout=15000)
        elif not pg.query_selector("#bk").is_disabled():
            pg.click("text=跳过本轮")
        pg.wait_for_timeout(1500)
        if int(_) % 12 == 0: pg.click("text=看内脏")                  # 周期观察debug
    print("到", pg.eval_on_selector("#ph","e=>e.textContent"), "中心", pg.eval_on_selector("#c","e=>e.textContent"))
    print("JS异常:", errs or "无"); b.close()
