"""驱动真服: 验对等轮(后台预热不卡, pending收敛, 人发推进, 满轮转下令, 结算)。"""
import time
import httpx

c = httpx.Client(base_url="http://localhost:8731", trust_env=False, timeout=180)
print("新局", c.post("/api/new", json={"human": "FRANCE"}).json()["mode"])
for _ in range(6):
    while True:
        s = c.get("/api/state").json()
        if s["mode"] == "ORDERS" or s["pending"] == ["FRANCE"]:
            break
        time.sleep(2)
    if s["mode"] == "ORDERS":
        break
    s = c.post("/api/say", json={"content": "和平瓜分"}).json()
    print("发言后 round", s["round"], "待发", s["pending"])
print("转下令, 法国合法令", len(c.get("/api/state").json()["legal"]))
o = c.post("/api/orders", json={"orders": s.get("legal", [])[:2]}).json()
print("结算->", o["phase"], "中心", c.get("/api/state").json()["centers"])
