"""Deterministic, zero-cost heuristic opponent for offline play and regression tests.

This is deliberately labelled a simulation, not an LLM. It uses only the board,
its own memories, and the diplomatic record visible to that power.
"""
from __future__ import annotations

from collections import deque
from functools import lru_cache
import hashlib
import json
import re

from diplomacy import Map

from ..context_budget import legal_from_context

POWERS = ("AUSTRIA", "ENGLAND", "FRANCE", "GERMANY", "ITALY", "RUSSIA", "TURKEY")
CONTEXT_PREFIX = "DIPLOMIND_CONTEXT:"


def context_from(messages: list[dict]) -> dict:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        for line in str(message.get("content", "")).splitlines():
            if line.startswith(CONTEXT_PREFIX):
                try:
                    context = json.loads(line[len(CONTEXT_PREFIX):])
                    if isinstance(context, dict):
                        return context
                except (ValueError, TypeError):
                    pass
    return {}


def _diplomacy(ctx: dict) -> str:
    """Consume the same retrieved current evidence as models, without duplicating prompts."""
    if ctx.get("diplomacy"):
        return ctx["diplomacy"]
    return "\n".join(f"{e.get('speaker', '')}: {e.get('text', '')}"
                     for e in ctx.get("visible_evidence", []) if e.get("phase") == ctx.get("phase"))


def _stable(text: str) -> float:
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:4], "big") / 2**32


def province(loc: str) -> str:
    return loc.upper().split("/")[0]


@lru_cache(maxsize=1)
def _map() -> Map:
    return Map("standard")


@lru_cache(maxsize=4096)
def _distances(unit: str, start: str) -> dict[str, int]:
    """Shortest legal land/sea routes, including multi-coast destinations."""
    board = _map()
    queue = deque([(start.upper(), 0)])
    distances = {start.upper(): 0}
    while queue:
        loc, distance = queue.popleft()
        for nxt in board.abut_list(loc, incl_no_coast=True):
            nxt = nxt.upper()
            if nxt not in distances and board.abuts(unit, loc, "-", nxt):
                distances[nxt] = distance + 1
                queue.append((nxt, distance + 1))
    collapsed = {}
    for loc, distance in distances.items():
        collapsed[province(loc)] = min(distance, collapsed.get(province(loc), 999))
    return collapsed


def choose_orders(ctx: dict) -> list[str]:
    """Choose compatible legal orders; expand, defend threatened homes, support attacks.

    Heuristic only: does not promise optimal play or predict simultaneous orders.
    Never invents an order and never forces a quota of attacks.
    """
    flat = sorted(set(legal_from_context(ctx)))
    country = ctx.get("country", "")
    mine = set(ctx.get("centers", {}).get(country, []))
    owned = {loc: power for power, locs in ctx.get("centers", {}).items() for loc in locs}
    centers = set(ctx.get("supply_centers", []))
    neutral = centers - set(owned)
    units = {province(u.split()[1]): (power, u.lstrip("*"))
             for power, values in ctx.get("units", {}).items() for u in values if len(u.split()) >= 2}
    own_locs = {loc for loc, (power, _) in units.items() if power == country}
    persona = ctx.get("persona", "opportunist")
    profile = ctx.get("behavioral_profile", {})
    honor = profile.get("honor", .75 if persona in ("diplomat", "turtle") else .4)
    risk = profile.get("risk", .5)
    ambition = profile.get("ambition", .6)
    betrayal_threshold = profile.get("betrayal_threshold", .6)
    survival = profile.get("survival_priority", .9)
    transcript = _diplomacy(ctx)
    relations = ctx.get("relations", {})
    ally = ctx.get("intent", {}).get("ally", "")
    seed = country + ctx.get("phase", "") + persona
    groups: dict[str, list[str]] = {}
    for order in flat:
        parts = order.split()
        if len(parts) >= 3:
            groups.setdefault(province(parts[1]), []).append(order)
    # No access to others' orders: infer immediate threats only from public positions.
    threats = {loc: sum(bool(_map().abuts(u.split()[0], u.split()[1], "-", loc))
                        for owner, u in units.values() if owner != country) for loc in groups}
    targets = list(centers - mine)
    chosen: dict[str, str] = {}
    reserved: set[str] = set()
    candidates: dict[str, list[tuple[float, str]]] = {}
    for loc, options in groups.items():
        ranked = []
        for order in options:
            parts = order.split(); verb = parts[2]; score = -15.0
            if verb in ("-", "R"):
                dest = province(parts[3]); occupant = units.get(dest)
                distances = _distances(parts[0], parts[3])
                remaining = min((distances.get(t, 99) for t in targets), default=0)
                neutral_distance = min((distances.get(t, 99) for t in neutral), default=99)
                score = 14 - min(remaining, 10) * 2.5
                if neutral_distance < 8: score += 12 / (neutral_distance + 1)
                if dest in neutral: score += 13 + ambition * 12
                elif dest in centers and dest not in mine: score += 16
                if dest in mine: score -= 7
                if occupant and occupant[0] != country: score -= 10 + (1 - risk) * 20
                if occupant and occupant[0] == country: score -= 35
                owner = owned.get(dest)
                trust = relations.get(owner, {}).get("trust", 0)
                # A stated alliance matters to cautious personas, not an unconditional rule.
                if owner == ally:
                    # Benefit must outweigh lost cooperation, principles, and the
                    # player's own betrayal threshold. Survival can change utility.
                    survival_pressure = max(0, threats[loc] - 1) * survival * 8
                    score -= max(0, honor * 20 + betrayal_threshold * 20 - survival_pressure)
                if trust > 20: score -= honor * trust / 3
                if trust < -20: score += profile.get("grudge", .5) * min(8, -trust / 12)
                if persona == "bully" and owner and owner != country: score += 8
                if persona == "turtle" and loc in mine and threats[loc]: score -= 25
                # Human/AI demilitarized-zone proposals change honest personas' priorities.
                if dest in transcript.upper() and re.search(r"(?i)DMZ|demilitar|非军事|不进|不要进入", transcript):
                    score -= honor * 38
                for promise in ctx.get("commitments", []):
                    if dest in promise.get("content", "").upper() and re.search(
                            r"(?i)DMZ|demilitar|non.aggression|不进|不入|互不侵犯", promise.get("content", "")):
                        score -= honor * 32 + betrayal_threshold * 16
                if " VIA" in order: score -= 30  # no uncoordinated convoy guess
            elif verb == "H":
                score = 1 + (20 if loc in mine and threats[loc] else 0)
                if persona == "turtle": score += 6
                # Spring occupation does not capture a center. Stay through the
                # autumn adjudication rather than wandering away before ownership.
                if ctx.get("phase", "").startswith("F") and loc in centers - mine: score += 45
            elif verb == "B": score = 25 + (3 if parts[0] == "A" else 0)
            elif verb == "D": score = -10
            elif verb == "S": score = -3  # upgrade to useful support after moves are chosen
            score += _stable(seed + order)
            ranked.append((score, order))
        candidates[loc] = sorted(ranked, reverse=True)
    # Choose strongest expansion first so our own units do not bounce in a neutral center.
    for loc in sorted(groups, key=lambda l: (-candidates[l][0][0], l)):
        for _, order in candidates[loc]:
            parts = order.split()
            dest = province(parts[3]) if parts[2] in ("-", "R") else loc
            if dest in reserved: continue
            chosen[loc] = order; reserved.add(dest); break
        if loc not in chosen:
            hold = next((o for o in groups[loc] if o.endswith(" H")), None)
            if hold: chosen[loc] = hold
    # Convert lower-value redundant moves/holds into support for contested friendly moves.
    for attacker_loc, move in list(chosen.items()):
        p = move.split()
        if len(p) < 4 or p[2] != "-": continue
        dest = province(p[3]); enemy = units.get(dest)
        contested = bool(enemy and enemy[0] != country)
        contested |= sum(bool(_map().abuts(u.split()[0], u.split()[1], "-", dest))
                         for owner, u in units.values() if owner != country) > 0
        if not contested: continue
        for helper_loc in sorted(groups):
            if helper_loc == attacker_loc: continue
            support = next((o for o in groups[helper_loc]
                            if o.split()[2:] == ["S", p[0], p[1], "-", p[3]]), None)
            current = chosen.get(helper_loc, "").split()
            if not support or not current: continue
            if current[2] == "-" and province(current[3]) in neutral: continue
            if current[2] in ("H", "-") and not (helper_loc in mine and threats[helper_loc] > 1):
                chosen[helper_loc] = support; break
    return list(chosen.values())


class MockProvider:
    def complete(self, messages: list[dict], schema, tag: str = "") -> dict:
        ctx = context_from(messages)
        power = ctx.get("country", tag.split(":")[0])
        persona = ctx.get("persona", "opportunist")
        others = [c for c in POWERS if c != power]
        legal_moves = choose_orders(ctx)
        neutral = set(ctx.get("neutral_centers", []))
        grabs = [province(o.split()[3]) for o in legal_moves if " - " in o and province(o.split()[3]) in neutral]
        neighbors = {"FRANCE": "GERMANY", "GERMANY": "ENGLAND", "ENGLAND": "FRANCE",
                     "ITALY": "AUSTRIA", "AUSTRIA": "RUSSIA", "RUSSIA": "TURKEY", "TURKEY": "AUSTRIA"}
        ally = ctx.get("intent", {}).get("ally") or neighbors.get(power, others[0] if others else "")
        if schema.__name__ == "OrderSet":
            return {"reasoning": "Offline heuristic: pursue reachable centers, avoid friendly collisions, coordinate support and defend exposed homes.",
                    "intentional_self_standoffs": [],
                    "unit_plan": [{"unit": " ".join(o.split()[:2]), "order": o} for o in legal_moves], "orders": legal_moves}
        if schema.__name__ == "Intent":
            return {"goal": "争取可达中心并保卫本土；按局势兑现互保", "ally": ally,
                    "target": "", "grab": grabs[:2], "move_turn": 0}
        if schema.__name__ == "AttitudeUpdate":
            relations = ctx.get("relations", {})
            scores = {p: max(-100, min(100, relations.get(p, {}).get("trust", 0))) for p in others}
            attitudes = {p: relations.get(p, {}).get("attitude", "尚待用行动验证") for p in others}
            grudge = ctx.get("behavioral_profile", {}).get("grudge", .5)
            for evidence in ctx.get("action_evidence", []):
                actor = evidence.get("actor")
                if actor in scores and evidence.get("source") == "public_result" and evidence.get("betray"):
                    scores[actor] = min(scores[actor], -round(30 + 60 * grudge))
                    attitudes[actor] = "公开行动伤害过我；恢复信任需要新的可验证合作"
            # A third-party accusation is preserved as an unverified claim, not
            # converted into a factual trust penalty by this offline heuristic.
            return {"scores": scores, "attitudes": attitudes}
        if schema.__name__ == "Message":
            transcript = _diplomacy(ctx)
            correspondents = re.findall(r"(?:R\d+\s+)?(AUSTRIA|ENGLAND|FRANCE|GERMANY|ITALY|RUSSIA|TURKEY)[·:]", transcript)
            partner = next((c for c in reversed(correspondents) if c != power), ally)
            target = grabs[0] if grabs else next((province(o.split()[3]) for o in legal_moves if " - " in o), "边界")
            en = ctx.get("lang") == "en"
            variants = {
                "bully": [f"我要争取 {target}。{partner}，帮我守侧翼，我们各取一个中心。", f"{partner}，让我们把兵力集中在一条战线上；我不想把这季浪费在互相弹回。"],
                "diplomat": [f"{partner}，我计划向 {target} 推进，愿意谈一季互不侵犯。你需要哪支部队的支援？", f"我听到了你的条件。{partner}，请确认具体支援命令，我们用行动建立信任。"],
                "backstabber": [f"{partner}，这季先稳住共同边界。我把注意力放在 {target}，希望你也给我一点空间。", f"我们的约定仍有价值，{partner}。先告诉我你打算去哪，我再确定能给的支援。"],
                "opportunist": [f"{target} 是眼下最划算的机会。{partner}，你能提供什么支援？我愿意交换情报。", f"{partner}，我更愿意拿稳一个中心，而不是空耗兵力。我们谈个双方都能兑现的交换。"],
                "balancer": [f"{partner}，别让领先者轻松扩张。我会争取 {target}，也愿意讨论互相支援。", f"我们需要制衡领先的一方。{partner}，先协调边界，再决定谁负责主攻。"],
                "turtle": [f"{partner}，我的底线是本土安全。只要边界稳定，我愿意讨论 {target} 的安排。", f"我不急着开第二条战线。{partner}，确认互不侵犯后我们再谈支援。"],
                "schemer": [f"{partner}，如果另一条战线牵制住对手，{target} 就有机会。我们私下协调一下。", f"{partner}，我愿意分享扩张窗口。你先确认站位，我再告诉你哪一处最值得争取。"],
            }
            index = 1 if transcript else 0
            content = variants.get(persona, variants["opportunist"])[index]
            if transcript and re.search(r"(?i)betray|背叛|背刺|叛徒", transcript):
                content = f"{partner}，你提到失信；我会先核对公开行动。请说明具体约定和证据，再谈下一步合作。"
            if en:
                tones = {"bully": "I want a firm deal", "diplomat": "Let's make a deal we can both keep",
                         "backstabber": "A quiet border benefits us both", "opportunist": "Let's take the best opening",
                         "balancer": "We should contain the leader", "turtle": "My home centers come first",
                         "schemer": "There may be an opening while our rivals are occupied"}
                content = f"{partner}, {tones.get(persona, 'let us coordinate')}. I am considering {target}; can we agree on specific support?"
                if transcript: content = f"{partner}, {tones.get(persona, 'let us coordinate')}. I have considered the messages; confirm your intended orders and support near {target} before I commit."
            scope = "broadcast" if persona in ("bully", "balancer") and not transcript else "private"
            return {"type": scope, "recipient": [] if scope == "broadcast" else [partner], "content": content}
        if schema.__name__ == "Summary":
            return {"text": "本阶段命令已完成裁决；中心归属以秋季结果为准，公开声明仍需用行动验证。"}
        return {}
