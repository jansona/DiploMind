"""Web 前端骨架 — 地图(中心/单位)、三态聊天、下令、编年史、观战/debug。
本地起，后台跑全 AI 互搏，前端轮询。CC 测不了浏览器→提供手测说明(见 RESULTS.md)。"""
from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .agent import Agent
from .chronicle import book, generate
from .debugpanel import snapshot
from .engine import OperationEngine
from .gateway import Gateway
from .orchestrator import Orchestrator
from .personalities import PERSONAS

ROSTER = ["AUSTRIA", "ENGLAND", "FRANCE", "GERMANY", "ITALY", "RUSSIA", "TURKEY"]
app = FastAPI(title="DiploMind")
STATE: dict = {"chronicle": [], "running": False}


def _new():
    gw = Gateway()
    eng = OperationEngine(ROSTER)
    ags = {c: Agent(c, list(PERSONAS.values())[i], gw) for i, c in enumerate(ROSTER)}
    return eng, ags, Orchestrator(eng, ags)


@app.get("/api/state")
def state():
    e = STATE.get("eng")
    return {"running": STATE["running"], "phase": e.phase() if e else "-",
            "centers": e.centers() if e else {}}


@app.get("/api/snapshot")          # 观战/debug 上帝视角：含意图/记忆/暗盘
def snap():
    if not STATE.get("eng"):
        return {}
    return snapshot(STATE["ags"], STATE["orch"].bus, STATE["eng"])


@app.get("/api/chronicle")         # 仅公开信息
def chron():
    return {"text": book(STATE["chronicle"])}


@app.post("/api/step")
async def step():
    if not STATE.get("eng"):
        STATE["eng"], STATE["ags"], STATE["orch"] = _new()
    STATE["running"] = True
    await STATE["orch"].run_phase()
    STATE["chronicle"].append(generate(STATE["orch"].bus, STATE["eng"].phase(), STATE["eng"].centers()))
    STATE["running"] = False
    return state()


@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX


INDEX = """<!doctype html><meta charset=utf-8><title>DiploMind</title>
<style>body{font:14px monospace;margin:1em}#m{white-space:pre-wrap}button{margin:4px}</style>
<h2>DiploMind 观战</h2><button onclick=step()>下一相</button><span id=ph></span>
<h3>中心</h3><div id=c></div><h3>编年史</h3><div id=m></div>
<script>
async function ref(){let s=await(await fetch('/api/state')).json();ph.textContent=s.phase;
c.textContent=Object.entries(s.centers).map(([k,v])=>k+':'+v).join('  ');
m.textContent=(await(await fetch('/api/chronicle')).json()).text;}
async function step(){await fetch('/api/step',{method:'POST'});ref();}
ref();</script>"""
