"""Web 前端 — 全员对等轮次同步: 你发/跳, 6AI 自主并发, 谁没发可见, 满N轮/静默转下令。
CC 测不了浏览器→端点 TestClient 测, 手测见 RESULTS.md。地图 SVG 二期。"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

DEBUG = bool(os.getenv("DIPLOMIND_DEBUG"))     # off: hide trust/internals (inner thoughts); on: show

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .chronicle import book
from .debugpanel import snapshot
from .names import PROVINCES
from .session import Session

app = FastAPI(title="DiploMind")
S: dict = {"game": None}


PRE = Path(__file__).parent.parent / "conf" / "presets"

@app.get("/api/menu")        # main menu: presets + saves; no auto game (start screen)
def menu():
    pres = {p.stem: json.loads(p.read_text()) for p in PRE.glob("*.json")} if PRE.exists() else {}
    return {"presets": pres, "saves": Session.list_saves()}


class NewReq(BaseModel):
    human: str | None = "__cfg__"; lang: str | None = None; preset: str | None = None

class SayReq(BaseModel):
    scope: str = "broadcast"; recipient: list[str] = []; content: str = ""; skip: bool = False

class OrdReq(BaseModel):
    orders: list[str] = []


@app.post("/api/new")
async def new(r: NewReq):
    personas = None
    if r.preset and (PRE / f"{r.preset}.json").exists():
        personas = json.loads((PRE / f"{r.preset}.json").read_text()).get("personas")
    S["game"] = Session(r.human, lang=r.lang, personas=personas)
    asyncio.ensure_future(S["game"].begin_phase())
    return S["game"].state()

@app.post("/api/menu_back")      # back to main menu (no config changes mid-game)
def menu_back():
    S["game"] = None; return {"mode": "MENU"}

@app.get("/api/state")
def state():
    s = S["game"].state() if S["game"] else {"mode": "MENU", "phase": "-"}
    s["debug"] = DEBUG; return s

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
    if not res.get("build"):                         # build phase: human still ordering, don't start negotiation
        asyncio.ensure_future(S["game"].begin_phase())
    return res

@app.post("/api/save")
def save(name: str = "auto"):
    return S["game"].save(name)

@app.post("/api/load")
async def load(name: str = "auto"):
    S["game"] = Session.load(name); await S["game"].begin_phase(); return S["game"].state()

@app.get("/api/chronicle")
def chron():
    return {"text": book(S["game"].chronicle) if S["game"] else ""}

@app.get("/api/relations")        # relations: trust (debug only)
def relations():
    g = S["game"]; return {c: {k: v.trust for k, v in a.mem.relations.items()} for c, a in g.ai.items()} if g and DEBUG else {}

@app.get("/api/betrayals")         # betrayal highlights (debug only)
def betrayals():
    g = S["game"]
    if not DEBUG: return {"items": []}
    return {"items": [{"who": c, "by": a.actor, "act": a.action, "yr": a.round}
                      for c, ag in (g.ai.items() if g else []) for a in ag.mem.actions if a.betray]}

@app.get("/api/snapshot")          # debug god view: persona+intent+memory+private (debug only)
def snap():
    g = S["game"]
    if not g or not DEBUG: return {}
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

import json as _json
_I18N = _P(__file__).parent / "i18n"
@app.get("/api/i18n/{lang}")     # external UI text files; add a language = add a json file
def i18n(lang: str):
    f = _I18N / f"{lang}.json"
    return _json.loads(f.read_text()) if f.exists() else _json.loads((_I18N / "en.json").read_text())

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
<style>body{font:13px monospace;margin:1em;max-width:760px}#log{white-space:pre-wrap;border:1px solid #ccc;padding:6px;height:150px;overflow:auto}select{width:100%}.p{color:#c60}#tabs button{font:12px monospace;margin:1px}#tabs .on{background:#c60;color:#fff}.v{display:none}</style>
<div id=menu><h1>DiploMind</h1><button onclick=toSetup()>新游戏 New Game</button><h3>继续 Continue</h3><div id=saves></div></div>
<div id=setup class=v><h2>新游戏</h2>扮演 <select id=hsel><option>AUSTRIA<option>ENGLAND<option selected>FRANCE<option>GERMANY<option>ITALY<option>RUSSIA<option>TURKEY<option value="">观战/Spectate</select>
语言 <select id=lsel><option value=zh-Hans>简体中文<option value=en>English</select> 预设 <select id=psel></select>
<button onclick=nw()>开始 Start</button> <button onclick=toMenu()>返回</button></div>
<div id=game class=v><h2>DiploMind — <span id=youl>你</span> <b id=h></b></h2>
<button onclick=save()>存档 Save</button> <button onclick=toMenu()>主菜单</button> <button onclick=guide()>Guide</button>
<b id=ph></b> <span id=md></span> 轮<span id=rd></span> 待发:<span class=p id=pd></span>
<pre id=gv style=display:none;font-size:11px;max-height:160px;overflow:auto></pre>
<div id=map style=border:1px solid #ccc;max-height:420px;overflow:auto></div>
<h3>中心</h3><div id=c></div>
<h3>聊天</h3><div id=tabs></div><span id=pk></span><button onclick=newp()>开私聊</button><div id=log></div>
<div id=nego><input id=t size=46 placeholder=发言><button id=bs onclick=say(0)>发送</button><button id=bk onclick=say(1)>跳过</button> <span class=p id=st></span></div>
<div id=ord style=display:none><div id=os style=max-height:160px;overflow:auto;border:1px solid #ccc;padding:4px></div>已选: <span id=osel class=p></span><br><button onclick=sub()>下令并结算</button></div>
<h3>编年史</h3><div id=ch></div>
<div id=inside class=v><button onclick=relo()>关系/背叛</button><button onclick=dbg()>看内脏</button><div id=rel></div><div id=bet></div><pre id=dbgv style=font-size:11px;max-height:160px;overflow:auto></pre></div></div>
<script>
let act='群聊',chans={},mphase='',keys='',legal='',sent=false,L={},seen={},unread={};
function S(el,v){if(el.textContent!=v)el.textContent=v}
async function G(u,m,b){return(await fetch(u,{method:m||'GET',headers:{'Content-Type':'application/json'},body:b&&JSON.stringify(b)})).json()}
function show(v){for(let x of ['menu','setup','game'])document.getElementById(x).className=x==v?'':'v'}
async function toMenu(){show('menu');let m=await G('/api/menu');await G('/api/menu_back','POST');
saves.innerHTML=(m.saves.length?m.saves:['(无)']).map(s=>'<button onclick=\\'ld("'+s+'")\\'>'+s+'</button>').join(' ');
psel.innerHTML='<option value="">随机</option>'+Object.entries(m.presets).map(([k,v])=>'<option value='+k+'>'+(v.name||k)+'</option>').join('')}
function toSetup(){show('setup')}
async function ld(n){L=await G('/api/i18n/zh-Hans');ui();show('game');R(await G('/api/load?name='+n,'POST'))}
function pick(k){act=k;unread[k]=0;seen[k]=(chans[k]||[]).length;log.textContent=(chans[k]||[]).join('\\n')||'(空)';[...tabs.children].forEach(b=>b.className=b.textContent.replace(' ✦','')==k?'on':'')}
async function newp(){let to=[...pk.querySelectorAll(':checked')].map(c=>c.value);if(!to.length)return;let ch=(await G('/api/open','POST',{recipient:to})).channel;pk.querySelectorAll(':checked').forEach(c=>c.checked=false);keys='';pick(ch)}
function R(s){if(s.mode=='MENU')return;inside.className=s.debug?'':'v';S(ph,s.phase);S(rd,s.round);S(h,s.human||'观战');
S(c,Object.entries(s.centers||{}).map(([k,v])=>k+':'+v).join(' '));S(pd,(s.pending||[]).join(',')||'—');
if(!pk.children.length)pk.innerHTML=Object.keys(s.centers||{}).filter(k=>k!=s.human).map(k=>'<label><input type=checkbox value='+k+'>'+k.slice(0,3)+'</label> ').join('');
chans=s.channels||{};if(!chans[act])act='群聊';let nk=Object.keys(chans).join(',');
for(let k in chans){let n=chans[k].length;if(k!=act&&seen[k]!=undefined&&n>seen[k])unread[k]=1;}
if(nk!=keys){keys=nk;tabs.innerHTML=Object.keys(chans).map(k=>'<button onclick=\\'pick("'+k+'")\\'>'+k+'</button>').join('')}
[...tabs.children].forEach(b=>{let k=b.textContent.replace(/ ✦/,'');b.textContent=k+(unread[k]?' ✦':'')});
log.textContent=(chans[act]||[]).join('\\n')||'(空)';seen[act]=(chans[act]||[]).length;[...tabs.children].forEach(b=>b.className=b.textContent.replace(' ✦','')==act?'on':'');
nego.style.display=s.mode=='ORDERS'?'none':'';ord.style.display=s.mode=='ORDERS'?'':'none';
S(md,s.mode=='ORDERS'?L.ord+': '+(s.order_pending||[]).join(','):s.mode);
bs.disabled=bk.disabled=t.disabled=!s.your_turn;S(st,s.your_turn?L.sp:(s.staged&&s.staged!='已发0/3'?'⏳已发'+s.sent+'/3,等其他玩家':'⏳ AI思考中…'));
let nl=(s.legal||[]).join(',');if(nl!=legal){legal=nl;os.innerHTML=(s.legal||[]).map(o=>'<label><input type=checkbox value="'+o+'" onchange=oupd()> '+o+'</label><br>').join('');osel.textContent='';sent=false;ord.querySelector('button').disabled=false}
if(s.phase!=mphase){mphase=s.phase;fetch('/api/map').then(r=>r.text()).then(x=>map.innerHTML=x);G('/api/chronicle').then(d=>ch.textContent=d.text)}}
function ui(){youl.textContent=L.you;bs.textContent=L.send;bk.textContent=L.skip;ord.querySelector('button').textContent=L.sub}
async function nw(){L=await G('/api/i18n/'+lsel.value);ui();show('game');act='群聊';keys='';legal='';pk.innerHTML='';R(await G('/api/new','POST',{human:hsel.value,lang:lsel.value,preset:psel.value}))}
async function save(){let n=prompt('存档名',new Date().toISOString().slice(0,16));if(n)await G('/api/save?name='+n,'POST')}
async function guide(){if(gv.style.display!='none'){gv.style.display='none';return}let d=await G('/api/guide');gv.style.display='';gv.textContent='命令:\\n'+Object.entries(d.cmds).map(([k,v])=>k+' = '+v).join('\\n')+'\\n\\n地名:\\n'+d.locs.join('\\n')}
async function say(sk){if(t.disabled)return;if(sk&&!confirm('跳过本轮不发言?'))return;if(!sk&&!t.value.trim()){st.textContent='⚠空';return}bs.disabled=bk.disabled=t.disabled=true;st.textContent='…';
let H=h.textContent,scope=act=='群聊'?'broadcast':'private',to=act=='群聊'?[]:act.split('·').filter(x=>x!=H);
let r=await G('/api/say','POST',{scope,recipient:to,content:t.value,skip:!!sk});if(!r.ok){st.textContent='⚠ '+r.reason;R(r.state)}else{t.value='';R(r.state)}}
function oupd(){osel.textContent=[...os.querySelectorAll(':checked')].map(c=>c.value).join('; ')||'(无)'}
async function sub(){let o=[...os.querySelectorAll(':checked')].map(x=>x.value);if(!o.length&&!confirm('未选命令, 全部单位将原地?'))return;let b=event.target;b.disabled=sent=true;st.textContent=L.settle;await G('/api/orders','POST',{orders:o})}
async function relo(){if(rel.textContent){rel.textContent='';bet.textContent='';return}let r=await G('/api/relations');rel.textContent='关系: '+Object.entries(r).map(([k,v])=>k+'→'+JSON.stringify(v)).join(' ');let b=await G('/api/betrayals');bet.textContent='背叛: '+(b.items.map(x=>x.who+'被'+x.by+x.act).join(' | ')||'无')}
async function dbg(){if(dbgv.textContent){dbgv.textContent='';return}dbgv.textContent=JSON.stringify(await G('/api/snapshot'),null,1)}
toMenu();setInterval(async()=>{let s=await G('/api/state');if(s.mode!='MENU')R(s)},2000)</script>"""
