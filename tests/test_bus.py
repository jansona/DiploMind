"""收件渲染：自己标“我”、每条带轮次、群聊/私聊区分。"""
from diplomind.bus import MessageBus


def test_inbox_labels():
    b = MessageBus()
    b.post(1, "FRANCE", "broadcast", [], "和平")
    b.post(2, "GERMANY", "private", ["FRANCE"], "结盟")
    b.post(2, "FRANCE", "private", ["ITALY"], "我提议")
    out = b.inbox("FRANCE", 2, include_self=True)
    assert "R1 我(FRANCE)·群发: 和平" in out          # 自己标“我(国家)”+轮次
    assert "R2 GERMANY·私聊@你: 结盟" in out          # 收到私聊
    assert "R2 我(FRANCE)·私聊@ITALY: 我提议" in out   # 自己私聊也带轮次


def test_channels_split():
    b = MessageBus()
    b.post(1, "FRANCE", "broadcast", [], "和平")
    b.post(2, "FRANCE", "private", ["ITALY"], "私局")
    b.post(2, "GERMANY", "private", ["RUSSIA"], "不该看到")
    ch = b.channels("FRANCE")
    assert ch["群聊"] == ["R1 我(FRANCE): 和平"]
    assert ch["FRANCE·ITALY"] == ["R2 我(FRANCE): 私局"]   # 私聊各组合一频道
    assert "GERMANY·RUSSIA" not in ch                      # 无关私局不可见
