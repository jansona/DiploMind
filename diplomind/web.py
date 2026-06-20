"""Web 前端 — 全员对等轮次同步: 你发/跳, 6AI 自主并发, 谁没发可见, 满5轮/静默转下令。
CC 测不了浏览器→端点 TestClient 测, 手测见 RESULTS.md。地图 SVG 二期。"""
from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .chronicle import book
from .debugpanel import snapshot
from .names import PROVINCES
from .session import Session

app = FastAPI(title="DiploMind")
S: dict = {"game": None}


@app.on_event("startup")
async def boot():                                  # config via DIPLOMIND_CONFIG=conf/x.json (api/model/rounds/lang)
    S["game"] = Session("FRANCE")
    asyncio.ensure_future(S["game"].begin_phase())


class NewReq(BaseModel):
    human: str | None = "__cfg__"; lang: str | None = None; personas: dict | None = None

class SayReq(BaseModel):
    scope: str = "broadcast"; recipient: list[str] = []; content: str = ""; skip: bool = False

class OrdReq(BaseModel):
    orders: list[str] = []


@app.post("/api/new")
async def new(r: NewReq):
    S["game"] = Session(r.human, lang=r.lang, personas=r.personas)
    asyncio.ensure_future(S["game"].begin_phase())     # warm up; frontend polls
    return S["game"].state()

@app.get("/api/state")
def state():
    return S["game"].state() if S["game"] else {"mode": "NEW", "phase": "-"}

@app.post("/api/say")
async def say(r: SayReq):
    res = await S["game"].human_say(r.scope, r.recipient, r.content, r.skip)
    return {**res, "state": S["game"].state()}

class PrivReq(BaseModel):
    recipient: list[str] = []

@app.post("/api/open")           # register a private channel (backend-owned)
def open_private(r: PrivReq):
    return {"channel": S["game"].open_private(r.recipient)}

@app.post("/api/orders")
async def orders(r: OrdReq):
    res = await S["game"].submit(r.orders)
    asyncio.ensure_future(S["game"].begin_phase())
    return res

@app.post("/api/save")
def save():
    return S["game"].save()

@app.post("/api/load")
async def load():
    S["game"] = Session.load(); await S["game"].begin_phase(); return S["game"].state()

@app.get("/api/chronicle")
def chron():
    return {"text": book(S["game"].chronicle) if S["game"] else ""}

@app.get("/api/relations")        # relations: trust
def relations():
    g = S["game"]; return {c: {k: v.trust for k, v in a.mem.relations.items()} for c, a in g.ai.items()} if g else {}

@app.get("/api/betrayals")         # betrayal highlights
def betrayals():
    g = S["game"]
    return {"items": [{"who": c, "by": a.actor, "act": a.action, "yr": a.round}
                      for c, ag in (g.ai.items() if g else []) for a in ag.mem.actions if a.betray]}

@app.get("/api/snapshot")          # debug god view: persona+intent+memory+private
def snap():
    g = S["game"]
    if not g: return {}
    return {**snapshot(g.ai, g.bus, g.eng), "persona": g.persona_of, "lang": g.lang}

import re as _re
from pathlib import Path as _P
_LABELS = ""                                         # diplomacy render drops province names; re-inject BriefLabelLayer
for _p in _P(__import__("diplomacy").__file__).parent.glob("maps/svg/standard.svg"):
    _m = _re.search(r'<g[^>]*id="BriefLabelLayer".*?</g>', _p.read_text(), _re.S)
    _LABELS = _m.group(0) if _m else ""

@app.get("/api/map", response_class=HTMLResponse)
def gmap():                                          # render real board + province name labels
    if not S["game"]:
        return "<svg/>"
    svg = S["game"].eng.game.render()
    return svg.replace("</svg>", _LABELS + "</svg>") if _LABELS else svg

@app.get("/api/guide")          # abbrev->full/中文 + order syntax tables
def guide():
    cmds = {"H": "Hold 原地", "-": "Move 移动 A PAR-BUR", "S": "Support 支援 A PAR S A MAR-BUR",
            "C": "Convoy 海运 F ENG C A LON-BRE", "B": "Build 造兵 A PAR B", "D": "Disband 拆兵"}
    locs = [f"{a} = {en} / {zh}" for a, (en, zh) in sorted(PROVINCES.items())]
    return {"locs": locs, "cmds": cmds}

@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX


INDEX = """<!doctype html><meta charset=utf-8><title>DiploMind</title>
<style>body{font:13px monospace;margin:1em;max-width:760px}#log{white-space:pre-wrap;border:1px solid #ccc;padding:6px;height:150px;overflow:auto}select{width:100%}.p{color:#c60}#tabs button{font:12px monospace;margin:1px}#tabs .on{background:#c60;color:#fff}</style>
<h2>DiploMind — 你 <b id=h>FRANCE</b></h2>
<button onclick="if(confirm('重开新局?'))nw()">新局</button> <button onclick=guide()>Guide</button>
<b id=ph></b> <span id=md></span> 轮<span id=rd></span> 待发:<span class=p id=pd></span>
<pre id=gv style=display:none;font-size:11px;max-height:160px;overflow:auto></pre>
<div id=map style=border:1px solid #ccc;max-height:420px;overflow:auto></div>
<h3>中心</h3><div id=c></div>
<h3>聊天</h3><div id=tabs></div><button onclick=newp()>+私聊</button><div id=log></div>
<div id=nego><input id=t size=46 placeholder=发言><button id=bs onclick=say(0)>发送</button><button id=bk onclick=say(1)>跳过本轮</button> <span class=p id=st></span></div>
<div id=ord style=display:none><select id=os multiple size=8></select><br><button onclick=sub()>下令并结算</button></div>
<h3>编年史</h3><div id=ch></div>
<h3>内幕(观战/debug)</h3><button onclick=relo()>刷新关系/背叛</button><button onclick=dbg()>看内脏(意图/记忆/暗盘)</button><div id=rel></div><div id=bet></div><pre id=dbgv style=font-size:11px;max-height:160px;overflow:auto></pre>
<script>
let act='群聊',chans={},mphase='',keys='',legal='';     // only touch DOM on change; keep tab/input/selection
function S(el,v){if(el.textContent!=v)el.textContent=v}    // update only on change
async function G(u,m,b){return(await fetch(u,{method:m||'GET',headers:{'Content-Type':'application/json'},body:b&&JSON.stringify(b)})).json()}
function pick(k){act=k;log.textContent=(chans[k]||[]).join('\\n')||'(空)';[...tabs.children].forEach(b=>b.className=b.textContent==k?'on':'')}
async function newp(){let p=prompt('私聊对象(逗号,如 GERMANY,ITALY)');if(!p)return;act=(await G('/api/open','POST',{recipient:p.split(',').map(x=>x.trim())})).channel}
function R(s){S(ph,s.phase);S(md,s.mode);S(rd,s.round);S(h,s.human||'观战');
S(c,Object.entries(s.centers||{}).map(([k,v])=>k+':'+v).join(' '));S(pd,(s.pending||[]).join(',')||'—');
chans=s.channels||{};if(!chans[act])act='群聊';let nk=Object.keys(chans).join(',');
if(nk!=keys){keys=nk;tabs.innerHTML=Object.keys(chans).map(k=>'<button onclick=\\'pick("'+k+'")\\'>'+k+'</button>').join('')}
log.textContent=(chans[act]||[]).join('\\n')||'(空)';[...tabs.children].forEach(b=>b.className=b.textContent==act?'on':'');
nego.style.display=s.mode=='ORDERS'?'none':'';ord.style.display=s.mode=='ORDERS'?'':'none';
S(md,s.mode=='ORDERS'?'下令阶段·待下令: '+(s.order_pending||[]).join(',')||'下令阶段':s.mode);
bs.disabled=bk.disabled=t.disabled=!s.your_turn;
S(st,s.your_turn?'可发言':(s.staged?'⏳待投递: '+s.staged:'✓已发/跳过,等其他玩家'));   // staged until all submit
let nl=(s.legal||[]).join(',');if(nl!=legal){legal=nl;os.innerHTML=(s.legal||[]).map(o=>'<option>'+o+'</option>').join('');sent=false;os.disabled=false;ord.querySelector('button').disabled=false}  // new orders phase unlocks
if(s.phase!=mphase){mphase=s.phase;fetch('/api/map').then(r=>r.text()).then(x=>map.innerHTML=x);G('/api/chronicle').then(d=>ch.textContent=d.text)}}
async function nw(){act='群聊';keys='';legal='';R(await G('/api/new','POST',{}))}   // human/lang from config
async function guide(){if(gv.style.display!='none'){gv.style.display='none';return}let d=await G('/api/guide');gv.style.display='';gv.textContent='命令缩写:\\n'+Object.entries(d.cmds).map(([k,v])=>k+' = '+v).join('\\n')+'\\n\\n地名(简写=全名/中文):\\n'+d.locs.join('\\n')}
async function say(sk){if(t.disabled)return;if(!sk&&!t.value.trim()){st.textContent='⚠ 不能发空消息';return}
bs.disabled=bk.disabled=t.disabled=true;st.textContent='发送中…';
let H=h.textContent,scope=act=='群聊'?'broadcast':'private',to=act=='群聊'?[]:act.split('·').filter(x=>x!=H);
let r=await G('/api/say','POST',{scope,recipient:to,content:t.value,skip:!!sk});
if(!r.ok){st.textContent='⚠ '+r.reason;R(r.state)}else{t.value='';R(r.state)}}
let sent=false;async function sub(){let btn=event.target;btn.disabled=os.disabled=sent=true;st.textContent='⏳ 命令已交,结算中…';
await G('/api/orders','POST',{orders:[...os.selectedOptions].map(x=>x.value)})}   // 锁到下一相
async function relo(){if(rel.textContent){rel.textContent='';bet.textContent='';return}let r=await G('/api/relations');rel.textContent='关系: '+Object.entries(r).map(([k,v])=>k+'→{'+Object.entries(v).map(([a,t])=>a+':'+t).join(' ')+'}').join('  ');
let b=await G('/api/betrayals');bet.innerHTML='背叛: '+(b.items.map(x=>x.who+'被'+x.by+x.act+'('+x.yr+')').join(' | ')||'暂无')}
async function dbg(){if(dbgv.textContent){dbgv.textContent='';return}dbgv.textContent=JSON.stringify(await G('/api/snapshot'),null,1)}   // god view: intent/memory/all incl AI-AI private
setInterval(async()=>{R(await G('/api/state'))},2000)</script>"""
