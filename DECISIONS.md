# 决策日志

模糊处取的合理默认，供晨检复核。

- **2026-06-20 主力模型→qwen3.5:4b**：交接说明指定，9b 太热弃用。网关 DEFAULT_MODEL 改 4b。
- **谈判字段精简**：Message=`type/recipient/content`，死模板+宽松解析(补括号)+retry1+空轮兜底。
- **intent 暂不并入 order**：先保留独立以对比 4b/9b；据失败率再定（阶段一验收项）。
- **三国 demo=ENG/FRA/GER**：接壤冲突最大，测压力。
