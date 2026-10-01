# Bounded real-model test protocol

This protocol was subsequently executed for one full 1901 year on 2026-09-30.
See [the review](REAL_GAME_REVIEW.zh-CN.md) for results and limitations. Further
runs are not automatic. The ordinary visible demo remains on the mock provider.

## Bounded mixed-player browser check

- Two isolated human browser clients, France and Germany, driven by the test
  script; the other five powers use the selected Aliyun model
- Spring and Fall 1901, with two negotiation rounds per movement phase so an AI
  can respond to the human's first delivered message
- Each AI performs attitude update, intent, two negotiations and orders: **50 model
  requests maximum** across the entire test, not a limit per player
- Explicit `enable_thinking: false`, **2,048 output tokens per request**, at most
  **102,400 generated tokens**; input tokens are additional and must be reported
- Maximum concurrency 2, timeout 60 seconds per request, **no retries**
- Only synthetic dialogue, no account data or real private conversations
- Verify private-message separation, human ready/order blocking, received and
  outgoing promises reaching the AI's order context, valid orders and adjudication
- AI retreats/builds and public chronicles use deterministic local logic
- Stop after the complete 1901 year; block Spring 1902 cognition. This is a test
  stopping point, not a claim of an official draw or winner
- Ten-minute wall-clock limit begins only at the user's explicit test start

The dedicated harness enforces the global request counter, no-retry policy,
prompt-byte limit and next-phase stop. The ordinary server's per-decision settings
alone are **not** a global spending cap. The runner's `--configured` mode consumes
only the explicitly approved local credential reference; it does not prompt for
or copy a key. Provider billing also includes input tokens, so
the output-token ceiling is not a currency quote.

## Later strategic-quality check

Only after the server/browser integration passes, compare a small set of fixed
negotiation and betrayal scenarios in thinking mode with an explicitly approved
larger budget. Evaluate evidence-scoped trust, promise consistency, tactical
legality, persona differences and credible reasons for honoring or breaking an
agreement. Do not infer humanlike strategy merely from valid JSON or a single
successful move. Any larger-budget evaluation requires its own stated limits.
