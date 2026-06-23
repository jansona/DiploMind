# DiploMind

[![CI](https://github.com/jansona/DiploMind/actions/workflows/ci.yml/badge.svg)](https://github.com/jansona/DiploMind/actions/workflows/ci.yml)

[English](README.md)

基于 LLM 的《外交》(Diplomacy) 数字版：AI 国家用自然语言谈判、结盟、撒谎、背刺。
你执一个大国，对阵 AI——也可拉朋友各占一国。每个 AI 各有隐藏性格、各自为赢，
会记谁守诺谁背刺，局势到了就翻脸。

![棋盘](docs/img/board.png)

## 快速开始
```bash
uv sync                                             # 依赖(Python 3.11)
uv run uvicorn diplomind.web:app --port 8731        # 开 http://localhost:8731
uv run pytest                                       # 77 测
```
默认 AI 后端为任意 OpenAI 兼容 API（`conf/deepseek.json`）；纯本地可起 ollama 并
`DIPLOMIND_CONFIG=conf/ollama_qwen35_2b.json`。`DIPLOMIND_DEBUG=1` 显示上帝视角(信任/意图/暗盘)。

## 玩法
- **单人对 AI**：你执一国，6 AI 补齐。
- **全 AI 观战**：看 7 国打到 18 中心独胜或中心最多者胜。
- **多人(2–7 人)**：房主建房，他人凭码加入，空位 AI 补满。

## 多人模式
- **房间**：房主建房得 4 位码/邀请链接，可设口令；一服多局。
- **座位**：起昵称认领国家，seat-token 刷新回座；同浏览器两 tab = 两玩家。
- **房主控制**：开局、暂停、踢人(踢出转 AI)、谈判轮计时(90/180/300/关)、结束。
- **实时同步** SSE；局域网直连或临时隧道(如 `cloudflared tunnel --url http://localhost:8731`)。

## 机制
- **轮次同步**：每国每轮最多 3 条(群发/私聊)，轮末统一投递；静默或满轮转下令。
  人/AI 共用流程、仅输入不同(前端 vs LLM)，人与 AI 同时下令、交齐结算。
- **隐藏性格** 驱动 7 种打法；背叛盟友→信任暴跌+记仇。难度=各国模型档位。
- **终局**：18 中心独胜；到年限中心最多者胜(可切"幸存即和")。战报含胜者+中心折线图。

## 技术栈
Python 复用 `diplomacy` 引擎；FastAPI 房间(seat-token/SSE/计时) + 单文件 `ui.html`；结构化 JSON + 宽松解析 + 并发闸。

## 许可
AGPLv3 —— based on 开源 [`diplomacy`](https://github.com/diplomacy/diplomacy) 引擎(AGPLv3)。
全文见 [LICENSE](LICENSE)。开发文档见 [docs/](docs/)。
