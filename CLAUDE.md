# DiploMind — AI 外交（Diplomacy）数字版

> 项目代号：**DiploMind**（Diplomacy + Mind，AI 会算计的外交心智）。基于 LLM 的单机《外交》桌游：人类对阵会结盟、会撒谎、会背刺的 AI 国家。

## 接手说明
本目录的设计已定型，后续编码/验证/测试由 **Claude Code** 执行。先读本文件，再读引用文档。

## 文档索引
- [产品定义](产品定义.md) — 定位、模式、规则、AI/难度、沟通、好玩杠杆、成功标准
- [技术架构](技术架构.md) — 9 模块职责+接口、通信模型、AI_Diplomacy 借鉴点
- [AI性格风格](AI性格风格.md) — 7 风格 + 5 参数定义
- [DEMO验证清单](DEMO验证清单.md) — 最小 demo backlog（开工第一步）
- [交接说明](交接说明.md) — 当前任务：降级 4b 复测 + 修谈判格式失败

## 核心约束
- 全项目开源（接受 diplomacy 引擎 AGPLv3）。借鉴 AI_Diplomacy 仅借结构，勿拷代码（非商用许可）。
- 难度=纯模型档位；AI 始终为自己赢，不放水/不故意漏信息。
- 谈判=轮次同步非实时；7国并发；全员一轮静默提前结束。
- 规则在引擎(复用 diplomacy)、决策在 Agent；非法下令=hold+记 error 日志。

## 技术栈
- 后端 Python，复用 `diplomacy` 引擎；LLM 走 OpenAI 兼容；web 前端实时，未来服务器化多端。
- **本地已部署 ollama**；本机 M4 Pro/24GB，主力降 qwen3.5:4b（9b 验证够用但偏吃力/内存涨，4b 减负；27b 高配）。
- LLM 调用：勿用 ollama `format=schema`（9b 上慢35×/挂死），走原生 `/api/chat`+`think:false`+prompt注入字段+宽松JSON提取。
- 上下文截断：仅喂结构化摘要+近3回合，防 KV cache 膨胀。intent 可并入 order 省一次调用。
- 模块：操作引擎/编排器/消息总线/AI玩家/记忆库/LLM网关/Web前端/编年史/可观测Debug。

## 下一步
按 [DEMO验证清单](DEMO验证清单.md) 跑三国一回合，实测每国≈8次调用并发延迟与格式失败率。
