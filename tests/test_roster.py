"""玩家配置: 任意国/全AI/多人, 人类绝不被建成AI。"""
from diplomind.players import HumanPlayer
from diplomind.session import POWERS, Session


def test_any_country():
    s = Session("GERMANY"); assert "GERMANY" not in s.ai and len(s.ai) == 6
    assert isinstance(s.players["GERMANY"], HumanPlayer)

def test_all_ai():
    s = Session(None); assert len(s.ai) == 7 and not s.humans

def test_multiple_humans():
    s = Session(["FRANCE", "ITALY"])
    assert set(s.humans) == {"FRANCE", "ITALY"} and len(s.ai) == 5
    assert not ({"FRANCE", "ITALY"} & set(s.ai)) and len(s.persona_of) == 5  # neither built AI / has persona
