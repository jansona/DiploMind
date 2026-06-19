"""P8 debug 面板单测：按国家/通道筛消息，全内脏 snapshot。"""
from diplomind.agent import Agent
from diplomind.bus import MessageBus
from diplomind.debugpanel import messages, snapshot
from diplomind.engine import OperationEngine
from diplomind.personalities import PERSONAS


def test_filter_messages():
    bus = MessageBus()
    bus.post(1, "FRANCE", "broadcast", [], "群")
    bus.post(1, "GERMANY", "private", ["FRANCE"], "私")
    assert len(messages(bus, scope="private")) == 1
    assert len(messages(bus, country="GERMANY")) == 1
    assert len(messages(bus)) == 2


def test_snapshot_innards():
    eng = OperationEngine(["FRANCE"])
    ags = {"FRANCE": Agent("FRANCE", PERSONAS["bully"], None)}
    snap = snapshot(ags, MessageBus(), eng)
    assert "FRANCE" in snap["agents"] and "centers" in snap and "phase" in snap
