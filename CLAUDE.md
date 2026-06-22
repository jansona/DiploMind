# DiploMind — AI 外交（Diplomacy）数字版

> 基于 LLM 的单机《外交》桌游：人类对阵会结盟、会撒谎、会背刺的 AI 国家。代号 DiploMind（Diplomacy + Mind）。

> 状态：一期完成(分支 main, 53测+playwright绿)。归档见 docs/archive/PHASE1.md。二期开新会话续。

## 简介
人执一国(可配)+6AI/混合/全AI观战。AI 各有隐藏性格，自然语言谈判/结盟/背刺，记仇兑现；难度=各国模型档位。人/AI 共用同一回合流程，仅输入源不同（前端 vs LLM）。

## 核心约束
- 全开源 AGPLv3（复用 diplomacy 引擎；借鉴 AI_Diplomacy 仅借结构，勿拷代码）。
- 规则在引擎(diplomacy 裁决冲突=bounce)，决策在 Agent；非法下令=hold+记日志。
- AI 始终为自己赢，不放水；难度只由模型档位决定。
- 谈判=轮次同步非实时，每国每轮≤3条(多channel)，全员静默或满 N 轮(配置rounds)转下令。
- 记忆只读纪律：消息是输入，只有玩家自己写自己记忆，不改他人。

## Commit 规范
- **commit message 一律英文**，遵循 Conventional Commits：`type(scope): summary`。
- type：`feat` 新功能、`fix` 修 bug、`refactor` 重构、`test` 测试、`docs` 文档、`chore` 杂项、`perf` 性能。
- 例：`feat(gateway): support OpenAI-compatible APIs`、`fix(session): order phase no longer 500s on LLM timeout`。
- 一句话祈使现在时、简洁；正文(可选)说为什么；结尾保留 Co-Authored-By。

## 技术栈
- 后端 Python 3.11 / uv；复用 `diplomacy` 引擎；FastAPI Web。
- LLM=任意 OpenAI 兼容 API(默认本地 ollama 4b)。ollama 走原生 `/api/chat`+format约束+think:false；openai 走 `/chat/completions`。宽松JSON解析+并发闸+超时容错+num_predict截尾。勿用 ollama `/v1`(不认 think,慢35×)。
- 配置 `conf/*.json`(DIPLOMIND_CONFIG)：base_url/api_key/model/api/rounds/lang/concurrency/timeout/human；DIPLOMIND_DEBUG=1 显内脏。

## 项目结构
- `diplomind/engine.py` 操作引擎：地图/合法走子/裁决/撤退造兵/判胜负/存档
- `diplomind/gateway.py` LLM 网关：ollama 接入、并发限、重试、模型档位
- `diplomind/agent.py` AI 玩家五步：感知/态度/意图/谈判/下令（异步）
- `diplomind/players.py` 人/AI 统一 Player 接口；`session.py` 对局会话(轮次同步/存档)
- `diplomind/memory.py` 记忆：关系/承诺/背叛/diary；`bus.py` 三态消息总线
- `diplomind/orchestrator.py` 年循环；`chronicle.py` 编年史；`debugpanel.py` 观测
- `diplomind/web.py` FastAPI+前端(主菜单/选国/语言/预设/存档/debug)；`personalities.py` 7性格+语言；`config.py` 配置；`names.py` 地名；`chronicle.py` AI年度史；`i18n/` 界面文案；`conf/presets/` 性格预设
- `tests/` 53单元/集成；`scripts/` 真跑+playwright(ui_flow/ui_human)

## 运行
```bash
uv sync; uv run uvicorn diplomind.web:app --port 8731   # 8731 玩/观战
uv run pytest                                           # 测试
DIPLOMIND_MODEL=qwen3.5:2b DIPLOMIND_LANG=en uv run uvicorn diplomind.web:app
```

## 二期 backlog
多人房间/邀请;AI调味到"三局看不穿"实测;整局到胜负节奏;好玩杠杆UI(背叛弹原话/关系连线图/称号);移动端;CI;尾延迟。

## 文档
[docs/archive/](docs/archive/)：PHASE1(一期归档,先读)、产品定义、技术架构、AI性格风格、RESULTS、DECISIONS、DEMO清单。docs/ 留正式文档。
