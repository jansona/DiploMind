"""Observability — append each LLM call (prompt/response/latency/tokens/retries/fmt-fail) to JSONL."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


class DebugLog:
    def __init__(self, run_id: str | None = None) -> None:
        self.run_id = run_id or time.strftime("%Y%m%d-%H%M%S")
        self.path = LOG_DIR / f"calls-{self.run_id}.jsonl"

    def record(self, **fields: Any) -> None:
        fields["ts"] = time.time()
        fields["run_id"] = self.run_id
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(fields, ensure_ascii=False) + "\n")

    def stats(self) -> dict:
        if not self.path.exists():
            return {}
        rows = [json.loads(l) for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]
        calls = [r for r in rows if r.get("kind") == "llm"]
        n = len(calls) or 1
        lat = [r.get("latency_ms", 0) for r in calls]
        return {
            "calls": len(calls),
            "fmt_fail": sum(r.get("fmt_fail", 0) for r in calls),
            "fmt_fail_rate": round(sum(r.get("fmt_fail", 0) for r in calls) / n, 3),
            "tokens": sum(r.get("tokens", 0) for r in calls),
            "lat_avg_ms": round(sum(lat) / n),
            "lat_max_ms": max(lat, default=0),
        }
