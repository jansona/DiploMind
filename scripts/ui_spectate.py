"""全AI观战: 选观战开局, 不操作, 验阶段自动推进. 起服:8762."""
import time
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    b = pw.chromium.launch(); pg = b.new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e))); pg.goto("http://localhost:8762"); pg.wait_for_timeout(700)
    pg.click("text=新游戏 New Game"); pg.select_option("#hsel", ""); pg.click("text=开始 Start")
    pg.wait_for_function("()=>document.getElementById('game').className==''", timeout=10000)
    p0 = pg.eval_on_selector("#ph", "e=>e.textContent"); print("观战开局:", p0, "玩家:", pg.eval_on_selector("#h","e=>e.textContent"))
    ok = False
    for _ in range(60):
        time.sleep(5)
        if pg.eval_on_selector("#ph", "e=>e.textContent") != p0: ok = True; break
    print("自动推进到:", pg.eval_on_selector("#ph","e=>e.textContent"), "| 推进:", ok, "| JS异常:", errs or "无"); b.close()
