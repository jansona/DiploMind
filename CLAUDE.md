# DiploMind — AI 外交（Diplomacy）数字版

> 基于 LLM 的单机《外交》桌游：人类对阵会结盟、会撒谎、会背刺的 AI 国家。代号 DiploMind（Diplomacy + Mind）。

## 简介
人执一国 + 6 AI（或全 AI 观战）。AI 各有隐藏性格，自然语言谈判/结盟/背刺，记仇兑现；难度=各国所用模型档位。人/AI 共用同一回合流程，仅输入源不同（前端 vs LLM）。

## 核心约束
- 全开源 AGPLv3（复用 diplomacy 引擎；借鉴 AI_Diplomacy 仅借结构，勿拷代码）。
- 规则在引擎（复用 diplomacy 裁决），决策在 Agent；非法下令=hold+记日志。
- AI 始终为自己赢，不放水；难度只由模型档位决定。
- 谈判=轮次同步非实时，每国每轮一条，全员静默或满 5 轮转下令。

## 技术栈
- 后端 Python 3.11 / uv；复用 `diplomacy` 引擎；FastAPI Web。
- LLM 走本地 ollama 原生 `/api/chat`（默认 qwen3.5:4b）：`think:false`、format 语法约束、宽松 JSON 解析、并发闸 3、num_predict 截尾。勿用 `/v1`（不认 think，慢 35×）。

## 项目结构
- `diplomind/engine.py` 操作引擎：地图/合法走子/裁决/撤退造兵/判胜负/存档
- `diplomind/gateway.py` LLM 网关：ollama 接入、并发限、重试、模型档位
- `diplomind/agent.py` AI 玩家五步：感知/态度/意图/谈判/下令（异步）
- `diplomind/players.py` 人/AI 统一 Player 接口；`session.py` 对局会话(轮次同步/存档)
- `diplomind/memory.py` 记忆：关系/承诺/背叛/diary；`bus.py` 三态消息总线
- `diplomind/orchestrator.py` 年循环；`chronicle.py` 编年史；`debugpanel.py` 观测
- `diplomind/web.py` FastAPI+前端；`personalities.py` 7 性格+语言
- `tests/` 单元/集成；`scripts/` 真跑+playwright UI 测

## 运行
```bash
uv sync; uv run uvicorn diplomind.web:app --port 8731   # 8731 玩/观战
uv run pytest                                           # 测试
DIPLOMIND_MODEL=qwen3.5:2b DIPLOMIND_LANG=en uv run uvicorn diplomind.web:app
```

## 文档
[docs/](docs/)：产品定义、技术架构、AI性格风格、RESULTS（验证数据）、DEMO验证清单。
