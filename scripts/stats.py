"""按 tag 汇总最新一次 run 的调用：次数/延迟/token/格式失败，落 CSV。"""
import csv
import json
import sys
from glob import glob
from pathlib import Path

f = sorted(glob("logs/calls-*.jsonl"))[-1]
rows = [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
by: dict[str, list] = {}
for r in rows:
    by.setdefault(r["tag"].split(":")[-1], []).append(r)

out = Path("logs/summary.csv")
with out.open("w", newline="") as fp:
    w = csv.writer(fp)
    w.writerow(["step", "calls", "fail", "fail_rate", "lat_avg_ms", "lat_max_ms", "tok_avg"])
    print(f"{'step':8} {'calls':5} {'fail%':6} {'avg_ms':7} {'max_ms':7} tok")
    for k, v in sorted(by.items()):
        n = len(v); fail = sum(x["fmt_fail"] for x in v); lat = [x["latency_ms"] for x in v]
        row = [k, n, fail, round(fail/n, 2), round(sum(lat)/n), max(lat), round(sum(x["tokens"] for x in v)/n)]
        w.writerow(row); print(f"{k:8} {n:5} {fail/n:6.0%} {row[4]:7} {row[5]:7} {row[6]}")
print(f"-> {out}  (source {f})")
