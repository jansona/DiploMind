"""Web 前端 — 全员对等轮次同步: 你发/跳, 6AI 自主并发, 谁没发可见, 满5轮/静默转下令。
CC 测不了浏览器→端点 TestClient 测, 手测见 RESULTS.md。地图 SVG 二期。"""
from __future__ import annotations

import asyncio

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
    scope: str = "broadcast"; recipient: list[str] = []; content: str = ""; skip: bool = False

class OrdReq(BaseModel):
    orders: list[str] = []


@app.post("/api/new")
async def new(r: NewReq):
    S["game"] = Session(r.human)
    asyncio.ensure_future(S["game"].begin_phase())     # 后台预热, 前端轮询
    return S["game"].state()

@app.get("/api/state")
def state():
    return S["game"].state() if S["game"] else {"mode": "NEW", "phase": "-"}

@app.post("/api/say")
async def say(r: SayReq):
    await S["game"].human_say(r.scope, r.recipient, r.content, r.skip)
    return S["game"].state()

@app.post("/api/orders")
async def orders(r: OrdReq):
    res = await S["game"].submit(r.orders)
    asyncio.ensure_future(S["game"].begin_phase())
    return res

@app.get("/api/chronicle")
def chron():
    return {"text": book(S["game"].chronicle) if S["game"] else ""}

@app.get("/api/snapshot")
def snap():
    g = S["game"]; return snapshot(g.ai, g.bus, g.eng) if g else {}

@app.get("/api/map", response_class=HTMLResponse)
def gmap():                                          # 复用 diplomacy 引擎渲染真棋盘(省份/中心/单位)
    return S["game"].eng.game.render() if S["game"] else "<svg/>"

@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX


INDEX = """<!doctype html><meta charset=utf-8><title>DiploMind</title>
<style>body{font:13px monospace;margin:1em;max-width:760px}#log{white-space:pre-wrap;border:1px solid #ccc;padding:6px;height:150px;overflow:auto}select{width:100%}.p{color:#c60}#tabs button{font:12px monospace;margin:1px}#tabs .on{background:#c60;color:#fff}</style>
<h2>DiploMind — 你 <b id=h>FRANCE</b></h2><button onclick=nw()>新局</button>
<b id=ph></b> <span id=md></span> 轮<span id=rd></span> 待发:<span class=p id=pd></span>
<div id=map style=border:1px solid #ccc;max-height:420px;overflow:auto></div>
<h3>中心</h3><div id=c></div>
<h3>聊天</h3><div id=tabs></div><button onclick=newp()>+私聊</button><div id=log></div>
<div id=nego><input id=t size=46 placeholder=发言><button id=bs onclick=say(0)>发送</button><button id=bk onclick=say(1)>跳过本轮</button> <span class=p id=st></span></div>
<div id=ord style=display:none><select id=os multiple size=8></select><br><button onclick=sub()>下令并结算</button></div>
<h3>编年史</h3><div id=ch></div>
<script>
let busy=0;async function G(u,m,b){return(await fetch(u,{method:m||'GET',headers:{'Content-Type':'application/json'},body:b&&JSON.stringify(b)})).json()}
let act='群聊',chans={};function R(s){ph.textContent=s.phase;md.textContent=s.mode;rd.textContent=s.round;h.textContent=s.human||'观战';
c.textContent=Object.entries(s.centers||{}).map(([k,v])=>k+':'+v).join(' ');chans=s.channels||{'群聊':[]};
if(!chans[act])chans[act]=[];tabs.innerHTML=Object.keys(chans).map(k=>'<button class='+(k==act?'on':'')+' onclick=pick("'+k+'")>'+(k=='群聊'?k:k)+'</button>').join('');
log.textContent=(chans[act]||[]).join('\\n')||'(空)';
pd.textContent=(s.pending||[]).join(',')||'—';nego.style.display=s.mode=='ORDERS'?'none':'';ord.style.display=s.mode=='ORDERS'?'':'none';
let mine=(s.pending||[]).includes(s.human);bs.disabled=bk.disabled=t.disabled=!mine;  // 本轮发过就禁用,下轮恢复
if(mine)acted='';st.textContent=acted?('✓本轮已'+acted+',等其他玩家'):'';
os.innerHTML=(s.legal||[]).map(o=>'<option>'+o+'</option>').join('');
if(s.phase!=last){last=s.phase;fetch('/api/map').then(r=>r.text()).then(t=>map.innerHTML=t)}}
let last='',acted='';async function nw(){last='';acted='';R(await G('/api/new','POST',{human:'FRANCE'}));ch.textContent=''}
function pick(k){act=k;log.textContent=(chans[k]||[]).join('\\n')}
function newp(){let p=prompt('私聊对象(逗号分隔,如 GERMANY,ITALY)');if(!p)return;act=[H,...p.split(',').map(x=>x.trim().toUpperCase())].sort().join('·');if(!chans[act])chans[act]=[];pick(act)}
const H='FRANCE';async function say(sk){acted=sk?'跳过':'发言';st.textContent='✓本轮已'+acted+',等其他玩家';
let scope=act=='群聊'?'broadcast':'private',to=act=='群聊'?[]:act.split('·').filter(x=>x!=H);
R(await G('/api/say','POST',{scope,recipient:to,content:t.value,skip:!!sk}));t.value=''}
async function sub(){let o=[...os.selectedOptions].map(x=>x.value);await G('/api/orders','POST',{orders:o});ch.textContent=(await G('/api/chronicle')).text}
setInterval(async()=>{R(await G('/api/state'))},2000);nw()</script>"""
