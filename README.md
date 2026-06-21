# DiploMind

[中文](README.zh-CN.md)

An LLM-powered digital version of the board game *Diplomacy*, where AI nations
negotiate, form alliances, lie, and betray in natural language. You play one
great power against six AI opponents — each with a hidden persona — that pursue
their own victory, keep memory of who kept promises and who stabbed them, and
turn on you when the board says so.

## Quick start
```bash
ollama serve && ollama pull qwen3.5:4b              # 1. local model
uv sync                                             # 2. deps (Python 3.11)
uv run uvicorn diplomind.web:app --port 8731        # 3. open http://localhost:8731
```
Pick your country + language on the start screen, then play. Config file optional
(`DIPLOMIND_CONFIG=conf/example.json` for non-ollama OpenAI-compatible APIs).

## Play modes
- **Human vs AI** — you take one power, six AI fill the rest.
- **Mixed** — any subset human, the rest AI; the round flow is identical for all.
- **All-AI spectator** — watch seven AI scheme to 18 centers or a survivor draw.

## How it works
- **Synchronous rounds**: every power drafts one message per round (broadcast or
  private), all delivered together; a fully silent round (or the round cap, default 3)
  ends negotiation, then everyone orders. Humans and AIs share the same flow —
  only the input differs (UI vs LLM).
- **Hidden personas** drive 7 play styles; betraying an ally tanks trust and is
  remembered. Difficulty = which model a power runs.

## Tech stack
- Python backend, reuses the `diplomacy` engine for the map/adjudication.
- LLM via local **ollama** (default `qwen3.5:4b`); native `/api/chat` with
  grammar-constrained JSON, lenient parsing, concurrency cap.
- FastAPI web UI (real board, three-channel chat, orders, chronicle, debug).

## Run locally
```bash
ollama serve && ollama pull qwen3.5:4b        # local model
uv sync                                        # deps (Python 3.11)
uv run uvicorn diplomind.web:app --port 8731   # open http://localhost:8731
DIPLOMIND_LANG=ja uv run uvicorn diplomind.web:app   # set negotiation language
uv run pytest                                  # tests
```

## License
AGPLv3 — based on the open-source [`diplomacy`](https://github.com/diplomacy/diplomacy)
engine (AGPLv3), so DiploMind is AGPLv3 too. Full text in [LICENSE](LICENSE).

Docs: archived dev notes (product, architecture, personas, DEMO results) in
[docs/archive/](docs/archive/); `docs/` is reserved for future formal docs.
