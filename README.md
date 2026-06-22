# DiploMind

[中文](README.zh-CN.md)

An LLM-powered digital version of the board game *Diplomacy*, where AI nations
negotiate, form alliances, lie, and betray in natural language. You play one
great power against six AI opponents — each with a hidden persona — that pursue
their own victory, keep memory of who kept promises and who stabbed them, and
turn on you when the board says so.

## Quick start
```bash
ollama serve && ollama pull qwen3.5:4b              # 1. an LLM backend (local default)
uv sync                                             # 2. deps (Python 3.11)
uv run uvicorn diplomind.web:app --port 8731        # 3. open http://localhost:8731
uv run pytest                                       # tests
```
Main menu → New Game (pick country/language/preset) or Continue (load a save), then play.
`DIPLOMIND_DEBUG=1` reveals the god view (trust/intent/memory/private DMs); off by default.

## Play modes
- **Human vs AI** — you take one power, six AI fill the rest.
- **All-AI spectator** — watch seven AI scheme to 18 centers or a survivor draw.
- **Mixed / multiplayer** (phase 2) — backend supports many humans; web is single-client for now.

## How it works
- **Synchronous rounds**: each power sends up to 3 messages/round (group or private),
  delivered together; a fully silent round (or the round cap) ends negotiation, then
  everyone orders. Humans and AIs share the same flow — only input differs (UI vs LLM).
- **Hidden personas** drive 7 play styles; betraying an ally tanks trust and is remembered.
  Difficulty = which model a power runs.

## LLM backend (any OpenAI-compatible API)
DiploMind talks to **any OpenAI-compatible API**; local ollama is just the default.
Point it at OpenAI, GLM, Aliyun, vLLM, etc. via a config file:
```bash
DIPLOMIND_CONFIG=conf/example.json uv run uvicorn diplomind.web:app --port 8731
```
`conf/*.json`: `base_url`, `api_key`, `model`, `api` (`ollama`|`openai`), `rounds`,
`lang`, `concurrency`, `timeout`, `human`. See `conf/ollama.json` / `conf/example.json`.

## Tech stack
Python backend reusing the `diplomacy` engine; FastAPI web UI (real board, three-channel
chat, orders, chronicle, debug); structured-output JSON with lenient parsing + concurrency cap.

## License
AGPLv3 — based on the open-source [`diplomacy`](https://github.com/diplomacy/diplomacy)
engine (AGPLv3), so DiploMind is AGPLv3 too. Full text in [LICENSE](LICENSE).
Archived dev notes in [docs/archive/](docs/archive/); `docs/` for future formal docs.
