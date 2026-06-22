"""P1 记忆库单测：背叛降信任、承诺到期失效、长局上下文不膨胀。"""
from diplomind.memory import Memory
from diplomind.schemas import AttitudeUpdate


def test_attitude_update_parses_attitudes():
    """LLM 返回 trust+attitude，二者都解析，态度不再永远中立。"""
    u = AttitudeUpdate(scores={"GERMANY": -50}, attitudes={"GERMANY": "叛徒"})
    assert u.scores["GERMANY"] == -50 and u.attitudes["GERMANY"] == "叛徒"
    nested = AttitudeUpdate(scores={"ITALY": {"trust": 30, "attitude": "盟友"}})   # 兼容嵌套形
    assert nested.scores["ITALY"] == 30


def test_betrayal_lowers_trust():
    m = Memory("FRANCE")
    m.apply_attitude({"GERMANY": {"trust": 40, "attitude": "盟友"}})
    assert m.relation("GERMANY").trust == 40
    m.record_action(2, "GERMANY", "A MUN - BUR", betray=True)
    m.apply_attitude({"GERMANY": {"trust": -50, "attitude": "叛徒"}})   # 模型读背叛后评分
    assert m.relation("GERMANY").trust == -50
    assert any(a.betray for a in m.actions)


def test_commitment_expires():
    m = Memory("FRANCE")
    m.add_commitment("GERMANY", "三回合不打你", rnd=1, turns=3)
    m.add_commitment("ENGLAND", "永久互不侵犯", rnd=1, turns=None)
    for _ in range(3):
        m.tick()
    active = m.active_commitments()
    assert len(active) == 1 and active[0].to == "ENGLAND"          # 三回合的已失效, 永久仍在
    assert m.ledger[0].expired


def test_context_bounded():
    m = Memory("FRANCE")
    for r in range(20):
        m.add_diary(f"R{r}", "x" * 50)
    assert len(m.diary) == 3                # 只留近3回合细节
    assert len(m.summary()) < 1500          # 长局不膨胀
