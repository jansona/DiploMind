# DiploMind

[English](README.md)

基于 LLM 的单机《外交》(Diplomacy) 数字版：AI 国家用自然语言谈判、结盟、撒谎、背刺。
你执一个大国对阵 6 个 AI，各有隐藏性格、各自为赢，会记谁守诺谁背刺，局势到了就翻脸。

## 快速开始
```bash
ollama serve && ollama pull qwen3.5:4b              # 1. 一个 LLM 后端(本地默认)
uv sync                                             # 2. 依赖(Python 3.11)
uv run uvicorn diplomind.web:app --port 8731        # 3. 开 http://localhost:8731
uv run pytest                                       # 测试
```
主菜单 → 新游戏(选国/语言/预设)或继续(读存档)开玩。`DIPLOMIND_DEBUG=1` 显示上帝视角(信任/意图/暗盘)，默认关。

## 玩法
- **人机**：你执一国，6 个 AI 补齐。
- **全 AI 观战**：看 7 国打到 18 中心或存活和局。
- **混合/多人**(二期)：后端已支持多人，web 暂单客户端。

## 机制
- **轮次同步**：每国每轮最多 3 条消息(群发或私聊)，轮末统一投递；全员静默或满轮转下令。
  人与 AI 共用流程，只是输入不同(前端 vs LLM)。
- **隐藏性格** 驱动 7 种打法；背叛盟友→信任暴跌+记仇。难度=各国所用模型档位。

## LLM 后端(支持任意 OpenAI 兼容 API)
DiploMind 接**任意 OpenAI 兼容 API**，本地 ollama 只是默认。可指向 OpenAI/GLM/阿里云/vLLM 等，用配置文件：
```bash
DIPLOMIND_CONFIG=conf/example.json uv run uvicorn diplomind.web:app --port 8731
```
`conf/*.json`：`base_url`、`api_key`、`model`、`api`(`ollama`|`openai`)、`rounds`、`lang`、
`concurrency`、`timeout`、`human`。参考 `conf/ollama.json` / `conf/example.json`。

## 技术栈
Python 后端复用 `diplomacy` 引擎；FastAPI Web(真棋盘、三态聊天、下令、编年史、debug)；结构化 JSON 输出 + 宽松解析 + 并发闸。

## 许可
AGPLv3 —— based on 开源 [`diplomacy`](https://github.com/diplomacy/diplomacy) 引擎(AGPLv3)，
故全项目同为 AGPLv3。全文见 [LICENSE](LICENSE)。归档开发文档见 [docs/archive/](docs/archive/)。
