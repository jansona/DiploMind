"""7 种打法风格 → 5 参数(侵略性/守信度/瞒骗区间/结盟倾向/目标盟友)。注入 system prompt。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Persona:
    name: str            # 风格名
    aggression: str      # 侵略性 高/中/低
    loyalty: str         # 守信度 高/中/低
    betray_window: str   # 瞒骗区间 短/中/长（仅低守信时生效）
    ally_tendency: str   # 结盟倾向 高/中/低
    ally_target: str     # 目标盟友 抱最强/打最强/坑最弱


PERSONAS = {
    "bully": Persona("侵略者", "高", "中", "短", "中", "打最强"),
    "diplomat": Persona("外交家", "低", "高", "长", "高", "抱最强"),
    "backstabber": Persona("背刺者", "中", "低", "短", "高", "抱最强"),
    "opportunist": Persona("机会主义者", "中", "低", "中", "中", "坑最弱"),
    "balancer": Persona("均势者", "中", "中", "中", "高", "打最强"),
    "turtle": Persona("缩头乌龟", "低", "中", "长", "低", "抱最强"),
    "schemer": Persona("操纵者", "中", "低", "中", "高", "坑最弱"),
}


LANGS = {"zh-Hans": "简体中文", "zh-Hant": "繁體中文", "en": "English",
         "ja": "日本語", "ko": "한국어", "de": "Deutsch", "es": "Español"}


def system_prompt(country: str, p: Persona, lang: str = "zh-Hans") -> str:
    name = LANGS.get(lang, "简体中文")
    acts = {"高": "本回合至少一条进攻/扩张令，谈判带威胁", "中": "稳中求进，挑软柿子", "低": "守土为主，少冒进"}
    loy = {"高": "尽量守诺，背叛要值大代价才做", "中": "看利益守诺", "低": "随时可弃约，承诺只为利用"}
    win = {"短": "信任一够立刻翻脸", "中": "中途择机捅刀", "长": "养信任养到关键回合再深捅"}
    return (f"你扮演《外交》(Diplomacy)中的 {country}，打法=「{p.name}」。按性格行事：\n"
            f"- 侵略性{p.aggression}：{acts.get(p.aggression,'')}\n"
            f"- 守信度{p.loyalty}：{loy.get(p.loyalty,'')}；背叛后{win.get(p.betray_window,'')}\n"
            f"- 结盟倾向{p.ally_tendency}(低=独狼少私聊)；目标盟友={p.ally_target}\n"
            f"始终为自己赢(18中心)，不放水。说话前核对记忆：谁欠你承诺、谁言行不一/背刺过你，按守信度决定守诺或翻旧账。"
            f"谈判发言必须用{name}。只输出 JSON。")
