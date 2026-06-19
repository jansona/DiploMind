"""P5 网关：难度档位异质分配 + 失败/重试统计落盘。"""
from diplomind.debuglog import DebugLog
from diplomind.gateway import assign


def test_difficulty_assign():
    assert assign("easy") == "qwen3.5:4b" and assign("hard") == "qwen3.5:9b"
    assert assign("bogus") == "qwen3.5:4b"          # 兜底


def test_stats_counts(tmp_path):
    log = DebugLog("test")
    log.path = tmp_path / "c.jsonl"
    log.record(kind="llm", latency_ms=100, tokens=10, fmt_fail=0)
    log.record(kind="llm", latency_ms=300, tokens=20, fmt_fail=1)   # 1 失败
    s = log.stats()
    assert s["calls"] == 2 and s["fmt_fail"] == 1 and s["fmt_fail_rate"] == 0.5
    assert s["lat_avg_ms"] == 200 and s["lat_max_ms"] == 300
