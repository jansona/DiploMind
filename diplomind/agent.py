"""AI 玩家 Agent — 五步，独立调用、可单测。demo 跑 感知→意图→谈判→下令。"""
from __future__ import annotations

from .engine import OperationEngine
from .gateway import Gateway
from .memory import Memory
from .personalities import Persona, system_prompt
from .schemas import AttitudeUpdate, Intent, Message, OrderSet


class Agent:
    def __init__(self, country: str, persona: Persona, gw: Gateway) -> None:
        self.country, self.persona, self.gw = country, persona, gw
        self.mem = Memory(country)
        self.sys = {"role": "system", "content": system_prompt(country, persona)}

    # 1. 感知（不调模型）：棋局+收件+记忆 → 文本
    def perceive(self, eng: OperationEngine, inbox: str = "") -> str:
        g = eng.game
        units = {p: g.powers[p].units for p in eng.active_powers}
        cen = eng.centers()
        return (f"阶段:{eng.phase()} 中心:{cen} 单位:{units}\n"
                f"记忆:{self.mem.summary()}\n收件:\n{inbox or '（无）'}")

    # 2. 更新态度（调模型）：读近况事件评各国信任分，写回记忆
    def update(self, eng: OperationEngine, inbox: str = "") -> AttitudeUpdate | None:
        prompt = self.perceive(eng, inbox) + '\n据近况评各国信任分。scores 为字典: {"国名": -100到100}。'
        out = self.gw.chat([self.sys, {"role": "user", "content": prompt}], AttitudeUpdate, tag=f"{self.country}:attitude")
        if out:
            self.mem.apply_attitude({c: {"trust": t} for c, t in out.scores.items()})
        return out

    # 3. 隐藏意图（调模型）：只喂自己，默认延续上回合微调
    def intent(self, eng: OperationEngine) -> Intent | None:
        prev = f"上回合意图(延续微调):{self.mem.intent}\n" if self.mem.intent else ""
        msgs = [self.sys, {"role": "user", "content": prev + self.perceive(eng) + "\n定本回合隐藏意图。"}]
        out = self.gw.chat(msgs, Intent, tag=f"{self.country}:intent")
        if out:
            self.mem.intent = out.model_dump()
        return out

    NEGO_TPL = ('发一条外交消息。只输出此 JSON，不要解释、不要 markdown：\n'
                '{"type":"broadcast","recipient":[],"content":"…"}\n'
                'broadcast=群发(recipient 留空)；private=私聊(recipient 填国名如 ["GERMANY"])；'
                '无话可说则 content 填""(本轮静默)。')

    # 4. 谈判（每轮调模型）：死模板+精简字段+宽松解析+重试1次，仍坏=空轮
    def negotiate(self, eng: OperationEngine, inbox: str) -> Message | None:
        ctx = self.perceive(eng, inbox) + f"\n意图:{self.mem.intent}\n" + self.NEGO_TPL
        return self.gw.chat([self.sys, {"role": "user", "content": ctx}], Message, tag=f"{self.country}:nego", retry=1)

    def _legal_flat(self, eng: OperationEngine) -> list[str]:
        legal = eng.legal_orders(self.country)
        return sorted({o for v in legal.values() for o in v})

    def _order_prompt(self, eng: OperationEngine, flat: list[str]) -> str:
        n = len(eng.legal_orders(self.country))
        return (self.perceive(eng) + f"\n意图:{self.mem.intent}\n你是 {self.country}，仅指挥自己 {n} 个单位。"
                f"从下列合法命令逐字复制，每单位恰好一条，共 {n} 条放入 orders 数组(只放命令字符串)：\n"
                + "\n".join(flat) + f'\n示例:{{"orders":["{flat[0]}"],"reasoning":"一句话"}}')

    # 5. 下令（回合末调模型）：只从合法表选，非法即 hold
    def decide_orders(self, eng: OperationEngine) -> tuple[OrderSet | None, list[str]]:
        flat = self._legal_flat(eng)
        prompt = self._order_prompt(eng, flat)
        out = self.gw.chat([self.sys, {"role": "user", "content": prompt}], OrderSet, tag=f"{self.country}:order", temp=0.2)
        chosen = [o for o in (out.orders if out else []) if o in set(flat)]  # 非法剔除=hold
        for o in chosen:
            self.mem.record_action(0, self.country, o)
        return out, chosen

    def snapshot(self) -> dict:
        return {"country": self.country, "persona": self.persona.name, "mem": self.mem.snapshot()}

    # --- 异步版（7国并发用）---
    async def a_update(self, eng: OperationEngine, inbox: str = "") -> AttitudeUpdate | None:
        prompt = self.perceive(eng, inbox) + '\n据近况评各国信任分。scores 为字典: {"国名": -100到100}。'
        out = await self.gw.achat([self.sys, {"role": "user", "content": prompt}], AttitudeUpdate, tag=f"{self.country}:attitude")
        if out:
            self.mem.apply_attitude({c: {"trust": t} for c, t in out.scores.items()})
        return out

    async def a_intent(self, eng: OperationEngine) -> Intent | None:
        msgs = [self.sys, {"role": "user", "content": self.perceive(eng) + "\n定本回合隐藏意图。"}]
        out = await self.gw.achat(msgs, Intent, tag=f"{self.country}:intent")
        if out:
            self.mem.intent = out.model_dump()
        return out

    async def a_negotiate(self, eng: OperationEngine, inbox: str) -> Message | None:
        ctx = self.perceive(eng, inbox) + f"\n意图:{self.mem.intent}\n" + self.NEGO_TPL
        return await self.gw.achat([self.sys, {"role": "user", "content": ctx}], Message, tag=f"{self.country}:nego", retry=1)

    async def a_decide_orders(self, eng: OperationEngine) -> tuple[OrderSet | None, list[str]]:
        flat = self._legal_flat(eng)
        prompt = self._order_prompt(eng, flat)
        out = await self.gw.achat([self.sys, {"role": "user", "content": prompt}], OrderSet, tag=f"{self.country}:order", temp=0.2)
        return out, [o for o in (out.orders if out else []) if o in set(flat)]
