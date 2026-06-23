"""语言/性格配置 + num_predict: 系统提示带语言, 性格可指定, 输出截断设置。"""
from diplomind.gateway import Gateway
from diplomind.personalities import LANGS, system_prompt
from diplomind.session import POWERS, Session
from diplomind.schemas import Intent


def test_language_in_prompt():
    assert "English" in system_prompt("FRANCE", list(__import__("diplomind.personalities", fromlist=["PERSONAS"]).PERSONAS.values())[0], "en")
    assert len(LANGS) == 7                              # 7 种语言可选


def test_persona_config_fixed():
    s = Session(None, personas={"FRANCE": "bully", "GERMANY": "turtle"})
    assert s.persona_of["FRANCE"] == "侵略者" and s.persona_of["GERMANY"] == "缩头乌龟"


def test_num_predict_cap():
    body = Gateway()._body([{"role": "system", "content": "x"}], Intent)
    assert body["options"]["num_predict"] == 2048      # 够装 reasoning+多命令, 不截成 None
