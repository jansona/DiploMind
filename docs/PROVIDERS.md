# Providers and diplomatic AI

## Safe default: offline simulation

`DIPLOMIND_CONFIG=conf/mock.json uv run uvicorn diplomind.web:app --port 8731`

`mock` is a deterministic heuristic opponent, **not an LLM**. It makes no network
or CLI requests and needs no credentials. It chooses only engine-legal orders,
pursues reachable supply centers, keeps autumn occupations, avoids friendly
collisions, defends threatened homes and coordinates support. It is useful for
mixed human/AI games, local demonstrations, and end-to-end tests. It is not an
expert Diplomacy solver and does not promise optimal strategy or eventual solo
victory. Retreats/builds remain the session's engine fallback policy.

Seven personas influence negotiation tone, alliance reliability and tactical risk.
Each AI stores a private, stable seven-trait profile: honor, risk, ambition,
grudge, forgiveness, betrayal threshold and survival priority. Negotiation and
orders use the same profile, and it survives save/load. Traits change utility
judgments; they never impose an attack quota, an always-honest rule, or mandatory
timed betrayal. Classic includes all of this baseline intelligence. Plus is
deferred; an internal configuration seam does not imply a second ruleset.

These are implemented policies and prompt constraints, not evidence of human-level
play. The offline heuristic uses several weights directly and passes every weight
to real providers; it cannot establish the intelligence or entertainment value of
a language model. That needs separately authorized live-provider playtesting.

## Diplomacy actually reaches orders

After committing every negotiation round, including the final round, Session
provides each AI with its own visible current-phase transcript. This includes
its own promises, public messages, and private messages it sent or received.
The same transcript is included when selecting orders. It is never assembled
from another power's private memory or invisible chats.

Memory preserves intent, relationships, submitted orders, public board-result
observations and delivered dialogue across save/load. Dialogue evidence records
speaker, phase and provenance from structured bus envelopes. Speaker names are
never inferred from user-controlled message text, so embedded forged speaker
lines cannot authenticate a different sender. Evidence includes:

- `direct_private`: a private message involving this power
- `public_statement`: a publicly visible statement
- `reported_claim`: an accusation, explicitly unverified
- `public_result`: a result observed on the board; a betrayal label is the AI's
  interpretation of that action relative to its relationship
- `submitted_order`: an order the AI submitted, which is not proof it succeeded

Unverified reports can cause suspicion but must not be treated as proven actions.
Inference is labelled as inference in prompts. Older context is bounded and
summarized, so this is not a verbatim archive of an unlimited game. No new public
reputation score or automatic treaty penalty has been added.

Developer hooks:

- `Agent.observe_messages(phase, records)` for trusted sender/scope envelopes
- `Agent.observe_diplomacy(phase, transcript)` for bounded raw dialogue
- `AIPlayer.decide(engine, inbox=visible_transcript)`
- `Agent.a_decide_orders(engine, inbox=visible_transcript)`
- `await Gateway.aclose()` for deterministic cleanup
- `provider_capabilities(cli_enabled=False)` for passive catalog discovery
- `Gateway.capabilities()` for selected provider and sanitized runtime health

## HTTP models

Configure the server, never a browser seat. Supported transports:

| `api` | Endpoint | Output contract |
| --- | --- | --- |
| `ollama` | Native `/api/chat` | JSON Schema `format`, `think: false`, capped output |
| `openai` | `/chat/completions` appended to configured API base URL | JSON object + Pydantic schema validation |

OpenAI-compatible means Chat Completions compatibility. Providers that lack that
endpoint or reject `response_format` require a separate adapter; compatibility
is not claimed automatically. API keys stay server-side. Do not commit them to
JSON files. Set `DIPLOMIND_API_KEY` and `DIPLOMIND_BASE_URL` through the server's
environment or deployment secret storage. The example config intentionally contains an empty API key; the original recognizable
placeholder was cleared to encourage environment-only configuration. Never paste a
real secret into a tracked example file.

For an explicitly approved persistent private-file binding, set `api_key` to
`null` and `api_key_file` to `<checkout-parent>/diplomind-private/api-key.txt` in
an ignored server config such as `conf/aliyun.local.json`. The application reads
this one pinned POSIX path only when starting a provider. The private directory
must be owned by the runtime user and mode 0700; the file must be a single-link
regular owner-only 0600 file. Symlinks, including ancestor symlinks, are rejected.
The config loader validates the reference without reading the key. Inline and
file credential sources cannot be combined. This is ongoing application access,
not an invitation to expose the service publicly; removing the binding or
revoking the provider key disables future use. Workspace storage lifetime and
backup availability are not guaranteed. No credential file or local binding is
included in the source archive.

OpenAI-compatible providers accept only these server-side `request_options`:
`max_tokens` (integer 1–32,768), `enable_thinking` (boolean), and
`reasoning_effort` (`low`, `high`, or `max`). Unknown keys and wrong types are
rejected; a browser cannot set them. Options are not forwarded to Ollama or CLI
providers. The default output ceiling stays 2,048; leaving thinking options absent preserves the provider's own default.
Support for an accepted option still depends on the selected API/model.

`conf/aliyun.example.json` demonstrates the selected endpoint/model with an empty
key, explicit non-thinking mode, and a 2,048-token output ceiling. It is not the
default config and does not configure a credential. To evaluate thinking mode,
choose its setting and sufficient output budget deliberately. Aliyun documents
thinking as on/high by default for this model; the 700-token compatibility
ceiling was insufficient in one observed thinking-mode request. A bounded
1901 real-model mixed game has now been completed and reviewed; it exposed
strategy and UI weaknesses, and is not a claim of strong or humanlike play.
See [the next bounded game-test proposal](NEXT_REAL_GAME_TEST.md).

Calls have a bounded decision timeout including semaphore queue time and retries.
Authentication/client errors do not retry; malformed output, transient failures
and server errors have at most two retries. Cancellation propagates to the room
lifecycle. Failed decisions return `None`, leaving missing movement orders to
engine-safe holds. This is visible as degraded health/fallback counters, not a
successful AI response. No alternate paid provider is selected automatically.
Logs contain only call metadata and fixed error codes, not response text,
prompts, credentials, endpoint URLs or CLI stderr. HTTP responses are size-checked
before parsing. This is not a streaming download quota.

## Server-local coding agent adapters (experimental)

Provider IDs: `codex`, `claude-code`, `qoder`. They are disabled unless the server
operator explicitly sets `cli_enabled: true` and selects that provider/model.
A browser cannot choose a command, executable path, arguments, working directory,
environment or credentials. Merely opening the capability endpoint never runs a
CLI or tests authentication. Installed does not mean authenticated or ready.

Each Gateway creates a private temporary session directory; each request gets a
fresh working directory and HOME. There is no continuation/session reuse between
countries or rooms. Prompts travel over stdin, never through a shell or as command
flags. Stdout/stderr have bounded size, and timeout/cancellation kills and reaps
the process group on POSIX. Temporary files are removed after the request.

| Adapter | Restricted invocation | Validation status |
| --- | --- | --- |
| Codex | `exec`, read-only sandbox, no approval escalation, ephemeral session, shell/unified exec disabled, web search disabled, fresh home/config, schema output | Official contract reviewed; subprocess doubles tested; no authenticated live run |
| Claude Code | `--restricted`, print JSON, no built-in tools, MCP denied/empty, no user/project settings, one turn, no persistence | Requires current CLI with `--restricted` (docs specify v2.1.248+); subprocess doubles tested; no authenticated live run |
| Qoder | Print JSON, no built-in tools, all tools denied, empty strict MCP config, `dont_ask`, one turn, no persistence | Official headless/permissions contract reviewed; subprocess doubles tested; no authenticated live run |

Older versions can reject flags and fail closed. Do not remove restrictions to
make an old CLI work; update and validate under a dedicated service account.
These permission flags and temporary directories **are not an operating-system
security boundary**. For untrusted multiplayer traffic, run CLI providers in a
restricted OS account/container with no sensitive files or host mounts.

Authentication must be deliberately provisioned by the operator in the server
environment. The runner forwards only the selected provider's supported auth
variables (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`/`CLAUDE_CODE_OAUTH_TOKEN`, or
`QODER_PERSONAL_ACCESS_TOKEN`). It does not read/copy existing login files, reuse
your personal CLI HOME, log in, install anything, or accept credentials from game
messages. Fresh homes intentionally mean an existing desktop CLI login alone
is insufficient. Subscription/API usage terms and possible charges remain the
operator's responsibility. No authenticated CLI was used to validate these
adapters. The separately authorized HTTP compatibility check is recorded in
[VALIDATION.md](VALIDATION.md).

### Official references checked 2026-09-30

- [Codex non-interactive execution](https://developers.openai.com/codex/noninteractive/)
- [Codex CLI reference](https://developers.openai.com/codex/cli/reference/)
- [Codex configuration reference](https://developers.openai.com/codex/config-reference/)
- [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference)
- [Qoder headless operation](https://docs.qoder.com/cli/run-in-scripts)
- [Qoder CLI reference](https://docs.qoder.com/cli/cli-reference)
- [Qoder permission modes](https://docs.qoder.com/cli/permissions)

Qoder is included because its official docs now describe no-tools, strict MCP,
non-interactive and no-persistence controls. It is still experimental until a
separately authorized, correctly provisioned live test confirms the installed
version's behavior.

## Verification

`uv run pytest tests/test_providers.py`

Tests use `httpx.MockTransport` and in-process subprocess doubles, never external
inference. Coverage includes all seven powers' deterministic legal expansion,
varied personas, final-round context, DMZ-sensitive choices, memory round trips,
HTTP status/retry/redaction, malformed output, total timeouts, cancellation,
fixed restricted argv, stdin injection resistance, isolated directories/homes,
output parsing, disabled-provider discovery, process-group cleanup, profile-based
policy divergence, persistent private profiles, claim-versus-public-result trust,
forged-sender resistance and autumn supply-center capture.

## One-shot authorized Aliyun smoke

`scripts/smoke_real_provider.py` is a separate, deliberately narrow harness for the
explicitly selected endpoint/model. It does not modify the game server's config,
discover saved credentials or create a room/save. It writes only an allowlisted status
report to `artifacts/provider-smoke-result.json` with private file permissions, so
completion can be checked without reading the credential-entry terminal.

Run it in a real **cloud terminal**, not a piped command or an assistant shell
execution tool:

```bash
cd /workspace/scratch/ea406f62abda/DiploMind
.venv/bin/python -B scripts/smoke_real_provider.py \
  --base-url https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1 \
  --model deepseek-v4.1-flash
```

The human enters the key directly at the non-echoing `getpass` prompt. Enter starts
the test; Ctrl-C cancels. Missing TTY or failed echo control stops before input.
The program never accepts a key value via CLI arguments, environment or chat.
Core dumps are disabled. With the default prompt, keys remain in process/request memory only; ordinary
Python strings cannot promise cryptographic zeroization, so the process exits
when the one-shot test finishes. Do not enable terminal/input recording.

For the user's explicitly requested file-entry alternative, append
`--key-file ~/.config/diplomind/api-key.txt`.
This single allowlisted path is outside the repository. The user writes the bare
key into that file, saves it, then manually presses Enter in the waiting test
terminal. The runner does not open the file until that confirmation. It requires
an owner-only directory (0700) and regular owner-only file (0600), refuses symlinks
and hard links, and rejects oversized or malformed input. The runner never
prints, modifies or deletes the key file. The file remains until the user
authorizes cleanup; it must not be included in source archives or commits.

The runner honors only the cloud runtime’s explicit `HTTPS_PROXY` (or lowercase
`https_proxy`) route, while leaving general environment discovery disabled. The
transport honors the runtime trusted CA bundle, with TLS verification still enabled.
It does not use `ALL_PROXY`, expose proxy settings, or change the pinned TLS destination. An injected fake transport bypasses networking entirely in tests.

Hard request budget: at most eight calls, `max_tokens=700` per call, 30 seconds per
call, zero retries and no redirects or alternate endpoint/model. The API provider
controls billing; this is a token/request bound, not a currency quote. The runner
stops on the first authentication, transport, format or legal-order failure.

For a narrow non-thinking compatibility rerun, add `--disable-thinking --core-only`.
This sends top-level `enable_thinking: false` and limits the entire run to six
requests: intent, negotiation and orders for each persona, using identical seeded
trust rather than another model-generated attitude update. Output remains capped
at 700 tokens per call, with no retries. The ordinary eight-step harness retains
the provider's default thinking setting unless this option is selected.
[Aliyun's model documentation](https://help.aliyun.com/zh/model-studio/deepseek-api)
states that this model defaults to thinking mode. A 700-token truncation alone
does not establish whether reasoning or verbose answer text consumed the budget.
This small non-thinking check is not an evaluation of full-budget strategic play.

Two contrasting France personas receive the same synthetic visible dialogue,
promise and explicitly unverified accusation. A control private message between
Russia and Turkey is excluded. Each persona runs attitude, intent, negotiation,
then order selection, including its own message and a final delivered reply.
Only allowlisted metadata, engine-legal orders and provider-reported token totals
are printed. Raw model prose, prompts, response bodies, headers and keys are not
printed. The saved status report omits model prose, prompts, headers, keys and even
the synthetic order list; it includes only fixed statuses, bounded counts and usage.
Usage may be absent on failures and cannot be treated as a complete
billing record.

`uv run pytest tests/test_real_provider_smoke.py` verifies the runner against an
in-process fake endpoint. A passed smoke demonstrates connectivity, structured
output and legal order integration, not strategic intelligence or fun gameplay.

## Optional one-pass order review

`order_preflight_review` is a strict server-only boolean, **false by default**.
Add `"order_preflight_review": true` to an operator-controlled server config to
use it for new Web sessions and the batch game entrypoint. It cannot be enabled by
a browser request or a saved game. Existing sessions keep their current policy.
No private credential is involved in changing this boolean.

A clean decision makes no additional call. Deterministic own-order inconsistencies
may trigger at most one extra request, with `retry=0`; ordinary initial-request
retry behavior remains unchanged. The review uses the same gateway/concurrency
and any external global budget. It is not itself an application-wide spending cap.
A failed review preserves usable initial orders, and shutdown still cancels it.
Foreign convoy uncertainty, declared deliberate standoffs and betrayal itself are
not errors to repair. Local config and the current demo have not been enabled by
this source change. See [the measured tactical review](TACTICAL_REVIEW.zh-CN.md).
