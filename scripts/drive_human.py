"""驱动真服跑一遍人机回环: 新局→发言→AI回一轮→人下令结算。验产品主链路。"""
import httpx

c = httpx.Client(base_url="http://localhost:8731", trust_env=False, timeout=180)
s = c.post("/api/new", json={"human": "FRANCE"}).json()
print("新局", s["mode"], "法国合法令", len(s["legal"]))
c.post("/api/say", json={"content": "三国和平瓜分"})
r = c.post("/api/round").json()
print("AI回一轮 round->", r["round"], "收件", len(r["inbox"].splitlines()), "条")
o = c.post("/api/orders", json={"orders": s["legal"][:2]}).json()
print("结算->", o["phase"], "end", o["end"])
print("中心", c.get("/api/state").json()["centers"])
