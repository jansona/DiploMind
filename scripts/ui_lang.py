"""真浏览器: 选国(GERMANY)+切英文新局, 验界面文案随语言变、扮演国生效。需起服 :8750。"""
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    b = pw.chromium.launch(); pg = b.new_page(); pg.goto("http://localhost:8750")
    pg.wait_for_timeout(1500)
    print("初始发送按钮:", pg.text_content("#bs"))                       # 中文“发送”
    pg.select_option("#hsel", "GERMANY"); pg.select_option("#lsel", "en")
    pg.click("text=新局/New"); pg.wait_for_timeout(2000)
    print("切英文后:", pg.text_content("#bs"), pg.text_content("#bk"), "| 我=", pg.text_content("#h"))
    assert pg.text_content("#bs") == "Send" and pg.text_content("#h") == "GERMANY"
    pg.select_option("#lsel", "zh-Hans"); pg.click("text=新局/New"); pg.wait_for_timeout(2000)
    assert pg.text_content("#bs") == "发送"; print("切回中文:", pg.text_content("#bs"))
    print("ALL PASS"); b.close()
