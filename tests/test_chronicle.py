"""P7 编年史单测：仅公开信息，私聊不进。"""
from diplomind.bus import MessageBus
from diplomind.chronicle import book, generate


def test_only_public():
    bus = MessageBus()
    bus.post(1, "FRANCE", "broadcast", [], "我主张和平")
    bus.post(1, "GERMANY", "private", ["FRANCE"], "我要背刺你")    # 暗盘
    text = generate(bus, "S1901M", {"FRANCE": 4, "GERMANY": 4})
    assert "和平" in text and "背刺" not in text                  # 私聊不剧透
    assert "S1901M" in text and "FRANCE=4" in text
    assert book(["a", "b"]) == "a\n\nb"
