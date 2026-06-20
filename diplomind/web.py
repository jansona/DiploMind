"""Web 前端 — 人操一国(默认法国)+6AI: 聊天发言/点选下令/AI异步陪跑; 全AI=观战。
CC 测不了浏览器→端点有 TestClient 测, 手测说明见 RESULTS.md。"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .chronicle import book
from .debugpanel import snapshot
from .session import Session

app = FastAPI(title="DiploMind")
S: dict = {"game": None}


class NewReq(BaseModel):
    human: str | None = "FRANCE"


class SayReq(BaseModel):
    scope: str = "broadcast"
    recipient: list[str] = []
    content: str = ""


class OrdReq(BaseModel):
    orders: list[str] = []


@app.post("/api/new")
async def new(r: NewReq):
    S["game"] = Session(r.human)
    await S["game"].begin_phase()
    return S["game"].state()


@app.get("/api/state")
def state():
    return S["game"].state() if S["game"] else {"human": None, "phase": "-", "mode": "NEW"}


@app.post("/api/say")
def say(r: SayReq):
    S["game"].human_say(r.scope, r.recipient, r.content)
    return {"ok": True}


@app.post("/api/round")          # AI 发一轮言并投递
async def ai_round():
    await S["game"].ai_round()
    return S["game"].state()


@app.post("/api/orders")         # 人下令→6AI下令→结算→下一相
async def orders(r: OrdReq):
    res = await S["game"].submit(r.orders)
    await S["game"].begin_phase()
    return res


@app.get("/api/chronicle")
def chron():
    return {"text": book(S["game"].chronicle) if S["game"] else ""}


@app.get("/api/snapshot")        # 上帝视角(观战/debug): 意图/记忆/暗盘
def snap():
    g = S["game"]
    return snapshot(g.ai, g.bus, g.eng) if g else {}


@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX


INDEX = """<!doctype html><meta charset=utf-8><title>DiploMind</title>
<style>body{font:13px monospace;margin:1em;max-width:720px}button{margin:2px}#log{white-space:pre-wrap;border:1px solid #ccc;padding:6px;height:140px;overflow:auto}select{width:100%}</style>
<h2>DiploMind — 你操 <span id=h>FRANCE</span></h2>
<button onclick=nw()>新局</button> <b id=ph></b> 模式<span id=md></span> 轮<span id=rd></span>
<h3>中心</h3><div id=c></div>
<h3>收件</h3><div id=log></div>
<h3>发言</h3><input id=t size=50 placeholder=群发内容><button onclick=say()>发</button><button onclick=rnd()>AI回一轮</button>
<h3>下令(点选合法)</h3><select id=ords multiple size=8></select><br><button onclick=sub()>提交并结算</button>
<h3>编年史</h3><div id=ch></div>
<script>
async function g(u,m,b){return (await fetch(u,{method:m||'GET',headers:{'Content-Type':'application/json'},body:b&&JSON.stringify(b)})).json()}
function ren(s){ph.textContent=s.phase;md.textContent=s.mode;rd.textContent=s.round;h.textContent=s.human;
c.textContent=Object.entries(s.centers||{}).map(([k,v])=>k+':'+v).join(' ');log.textContent=s.inbox||'(空)';
ords.innerHTML=(s.legal||[]).map(o=>'<option>'+o+'</option>').join('')}
async function nw(){ren(await g('/api/new','POST',{human:'FRANCE'}));ch.textContent=''}
async function say(){await g('/api/say','POST',{scope:'broadcast',content:t.value});t.value=''}
async function rnd(){ren(await g('/api/round','POST'))}
async function sub(){let o=[...ords.selectedOptions].map(x=>x.value);await g('/api/orders','POST',{orders:o});ren(await g('/api/state'));ch.textContent=(await g('/api/chronicle')).text}
nw()</script>"""
