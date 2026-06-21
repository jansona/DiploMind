# DiploMind

[English](README.md)

基于 LLM 的单机《外交》(Diplomacy) 数字版：AI 国家用自然语言谈判、结盟、撒谎、背刺。
你执一个大国对阵 6 个 AI，各有隐藏性格、各自为赢，会记谁守诺谁背刺，局势到了就翻脸。

## 玩法
- **人机**：你执一国，6 个 AI 补齐。
- **混合**：任意几人 + 余下 AI，流程对所有玩家一致。
- **全 AI 观战**：看 7 国打到 18 中心或存活和局。

## 机制
- **轮次同步**：每国每轮一条消息(群发或私聊)，轮末统一投递；全员静默或满 N 轮(默认3,可配)转下令。
  人与 AI 共用流程，只是输入不同(前端 vs LLM)。
- **隐藏性格** 驱动 7 种打法；背叛盟友→信任暴跌+记仇。难度=各国所用模型档位。
- 主菜单：新游戏(选国/语言/预设)或继续(读存档)；信任/意图/暗盘默认隐藏，`DIPLOMIND_DEBUG=1` 才显示。

## 技术栈
- Python 后端，复用 `diplomacy` 引擎做地图与裁决。
- LLM 走本地 **ollama**(默认 `qwen3.5:4b`)；原生 `/api/chat` + 语法约束 JSON + 宽松解析 + 并发闸。
- FastAPI Web(真棋盘、三态聊天、下令、编年史、debug)。

## 本地运行
```bash
ollama serve && ollama pull qwen3.5:4b        # 本地模型
uv sync                                        # 依赖(Python 3.11)
uv run uvicorn diplomind.web:app --port 8731   # 开 http://localhost:8731
DIPLOMIND_DEBUG=1 uv run uvicorn diplomind.web:app   # 开 debug: 显示信任/意图/暗盘(默认关)
uv run pytest                                  # 测试
```

## 许可
AGPLv3 —— based on 开源 [`diplomacy`](https://github.com/diplomacy/diplomacy) 引擎(AGPLv3)，
故全项目同为 AGPLv3。全文见 [LICENSE](LICENSE)。归档开发文档见 [docs/archive/](docs/archive/)。
