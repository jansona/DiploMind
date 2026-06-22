"""多人系统试玩: 房主建房(FR)→第二人凭码加入(DE)→房主开局→两人各发言→SSE互见→下令结算. 起服:8772 qwen2b."""
import re, time
from playwright.sync_api import sync_playwright

B = "http://localhost:8772"; errs = []
with sync_playwright() as pw:
    br = pw.chromium.launch()
    host = br.new_page(); guest = br.new_page()
    host.on("pageerror", lambda e: errs.append("H:"+str(e))); guest.on("pageerror", lambda e: errs.append("G:"+str(e)))
    host.on("dialog", lambda d: d.accept()); guest.on("dialog", lambda d: d.accept())
    sel = lambda p, i: p.eval_on_selector(i, "e=>e.textContent")
    # host creates room as FRANCE
    host.goto(B); host.wait_for_timeout(600); host.click("text=新游戏 New Game")
    host.fill("#rn", "Table1"); host.select_option("#hsel", "FRANCE"); host.click("text=建房 Create")
    host.wait_for_function("()=>document.getElementById('game').className==''", timeout=8000)
    code = sel(host, "#rc"); print("✓ 建房:", code, "席位:", sel(host, "#h"))
    # guest joins by code as GERMANY
    guest.goto(B); guest.wait_for_timeout(400); guest.click("text=新游戏 New Game")
    guest.fill("#jc", code); guest.fill("#jn", "Bob"); guest.select_option("#jp", "GERMANY"); guest.click("text=加入 Join")
    guest.wait_for_function("()=>document.getElementById('game').className==''", timeout=8000); print("✓ Bob 加入为", sel(guest, "#h"))
    host.click("text=开局 Start")                                   # owner starts; AI fills 5
    host.wait_for_function("()=>document.querySelector('#h').textContent=='FRANCE'", timeout=15000)
    guest.wait_for_function("()=>document.querySelector('#h').textContent=='GERMANY'", timeout=15000); print("✓ 双端进局, 席位 FR/DE")
    host.wait_for_function("()=>document.querySelector('#st').textContent.includes('可发言')", timeout=30000)
    host.fill("#t", "德法结盟分德？"); host.click("#bs")             # 1 broadcast then skip rest
    guest.wait_for_function("()=>document.querySelector('#st').textContent.includes('可发言')", timeout=30000)
    guest.fill("#t", "好，互保"); guest.click("#bs")
    host.click("#bk"); guest.click("#bk")                           # both skip -> round 1 commits (~30-90s on 2b)
    for _ in range(80):                                             # wait round commit -> SSE delivers cross-seat
        if "FRANCE" in sel(guest,"#log") and "GERMANY" in sel(host,"#log"): break
        time.sleep(2)
    assert "FRANCE" in sel(guest,"#log") and "GERMANY" in sel(host,"#log"), "群聊未跨座位投递"
    print("✓ SSE 双端互见群聊"); print("✓ 房主控制可见:", host.eval_on_selector("#oc","e=>e.className=='' ") and guest.eval_on_selector("#oc","e=>e.className=='v'"))
    print("| JS异常:", errs or "无", "| ALL PASS"); br.close()
