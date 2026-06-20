"""系统测: 人每轮发1条后只轮询(不再点), 后端应自动推进到ORDERS不卡; 再下令结算。"""
import time
import httpx

c = httpx.Client(base_url="http://localhost:8731", trust_env=False, timeout=180)
c.post("/api/new", json={"human": "FRANCE"})
sent = set()
for _ in range(40):                       # 最多轮询40次, 验不卡死
    s = c.get("/api/state").json()
    if s["mode"] == "ORDERS":
        break
    if s["pending"] == ["FRANCE"] and s["round"] not in sent:   # 轮到我且没发过本轮→发1条
        sent.add(s["round"]); c.post("/api/say", json={"content": f"第{s['round']}轮发言"})
    time.sleep(3)
print("到达", s["mode"], "用轮次", sorted(sent), "法国合法令", len(c.get("/api/state").json()["legal"]))
o = c.post("/api/orders", json={"orders": c.get("/api/state").json()["legal"][:2]}).json()
print("结算->", o["phase"], "end", o["end"])
