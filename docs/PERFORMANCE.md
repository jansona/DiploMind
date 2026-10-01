# Performance checks (2026-09-30)

## Scope and environment

All measurements were offline/mock only. No LLM endpoint or credential was used.
The initial baseline was commit `ccdea3d` plus the then-current worktree; paired
transport comparisons below isolate the changed old/new path in the same process.
Other concurrent context-budget changes mean mock-agent phase timings in the full
baseline/after files must not be attributed to these transport optimizations.

- Python 3.11.16, Linux x86-64, 9 logical CPUs reported to the container
- HTTP server metrics: `httpx.ASGITransport`, in-process; exclude sockets/network
- Browser: native cloud Chromium 151.0.7922.173 over loopback HTTP
- GPU: ANGLE/Vulkan SwiftShader software rendering; no physical-GPU claim
- Browser desktop 1440×1000 and mobile **viewport** 390×844; neither mobile hardware
  nor cellular/CPU-throttled testing
- Browser cold loads disabled HTTP cache; repeated microbenchmarks were warmed
- RSS comes from `/proc/self/statm`, not a memory-leak or long-duration soak test

## Measured changes

### Compact SSE clock/presence updates

A synthetic mature game with 700 public messages × 2,000 characters produced a
1,416,474-byte full SSE frame. Previously a changing timer sent the full history
every second. An unchanged game revision now sends a roughly 150-byte named
`clock` frame, or a keepalive when even the clock/presence is unchanged.

Paired CPU-only fanout (30 ticks; production old serialization versus new generator,
with the one-second wait omitted equally):

| Subscribers | Full-state tick p50/p95 | Compact-clock tick p50/p95 |
| --- | --- | --- |
| 1 | 3.60 / 4.33 ms | 0.019 / 0.057 ms |
| 7 | 24.02 / 28.68 ms | 0.077 / 0.180 ms |
| 20 | 63.38 / 78.90 ms | 0.229 / 0.605 ms |

For 20 subscribers, 30 ticks used 2,046.5 ms versus 9.9 ms CPU and transmitted
849,884,400 versus 90,000 fixture bytes. Initial snapshots and relevant game changes
still send full history. This does **not** bound long-game history or speed up a new
client's first large-history render.

Native browser synthetic events used the actual production EventSource handlers
and delivered 10 timer events 100 ms apart (no busy loop). Median synchronous timer
handling fell from 7.9 ms desktop / 8.35 ms mobile viewport to about 0.2 ms each.
The 700-message DOM, unsent composer draft and selection were retained, and stale
clock revisions were ignored. A separate real mock-room test received one full
snapshot followed by four compact server clock events, with matching UI seconds.

Privacy/lifecycle protections are preserved: each new/reconnected stream builds a
fresh authenticated, seat-filtered snapshot; no cross-seat payload cache exists;
revocation is checked on every tick; active streams refresh seat presence. Async AI
completion advances room revision. Settling/phase/order-readiness fields also
invalidate snapshots while persistence callbacks are intentionally suppressed.

### Public board serialization

`/api/board` already creates only JSON-native public data. Returning `JSONResponse`
directly avoids a second recursive FastAPI encoder pass. The old/new response
bodies are byte-identical; authentication and private API security headers are
covered by a regression test. There is no board-response cache.

Paired ASGI benchmark, same process/engines/payload, 3 interleaved blocks × 5 bursts
per variant after 2 warmup bursts:

| Concurrent rooms | Old board p50/p95 | Direct JSON p50/p95 |
| --- | --- | --- |
| 1 | 5.17 / 7.67 ms | 1.62 / 2.52 ms |
| 7 | 27.55 / 30.04 ms | 7.28 / 9.03 ms |
| 20 | 69.73 / 92.32 ms | 18.78 / 19.73 ms |

At 20 rooms / 300 requests per variant, process CPU was 1,137 versus 310 ms.

## Remaining baseline and limits

Before changes, warm legal-order lookup p50/p95 was 0.004/0.005 ms, fresh state plus
JSON 0.025/0.057 ms, and an all-hold adjudication 0.211/0.337 ms. Board JSON was
106,655 bytes. The 1/7/20-room baseline process reached approximately 89.5 MiB RSS
from 72.1 MiB after imports. Burst-load scheduling/GC caused noisy tail latency.

Cloud software-rendered cold board readiness ranged roughly 1.1–1.6 seconds, with
all four GLBs and all 76 provinces present. FCP was 72–196 ms in observed runs;
startup changes were not consistently directional, so no startup improvement is
claimed. Stable observed frame interval was approximately 16.7 ms; idle main-thread
task time was roughly 54–58 ms per 2.5 seconds. These are local cloud-browser
observations, not internet latency, production capacity, a hardware-mobile score,
a thermal/battery result, or an LLM-latency benchmark.

## Reproduce

From the repository root (existing development dependencies only):

```sh
.venv/bin/python scripts/benchmark_performance.py --output artifacts/performance/baseline.json
.venv/bin/python scripts/benchmark_sse.py
.venv/bin/python scripts/benchmark_board.py
.venv/bin/python scripts/benchmark_server.py
# In another native-browser-capable process, while the explicit-mock server runs:
DIPLOMIND_PERF_URL=http://127.0.0.1:8732 .venv/bin/python scripts/benchmark_browser.py --output artifacts/performance/browser-after.json
DIPLOMIND_E2E_URL=http://127.0.0.1:8732 .venv/bin/python scripts/e2e_mixed.py
```

The isolated server is literal mock configuration and stores only fixture rooms
under `artifacts/performance/isolated-browser-saves`. Stop it after testing. Every
browser script asserts `/api/providers.selected == "mock"` before creating rooms.
The benchmark browser closes its own rooms and contexts; it does not use the demo
browser session. JSON/screenshot outputs are in the ignored `artifacts/performance`
directory. `baseline.json` represents whichever checkout is measured when rerun.

Focused regressions: `tests/test_stream_performance.py`, plus existing board, web,
secure lifecycle, multiseat, rooms, session and concurrency suites (58 passed at the
time of this run); `node --test tests/test_frontend_rules.mjs` (8 passed).

## Real model observations (separate from the offline benchmarks)

The crowded-history matched real A/B used 60 calls and reduced measured input tokens
from 377,913 to 146,507 (61.2%). It is a stress fixture, with only two repeats and
different cache-hit/output behavior; it is not a universal 61% game-cost claim.
The two actual 1901 mixed games used 154,828 and 154,809 total tokens, effectively
the same, with different dialogue/decisions. The second used 147,867 input and
6,942 output tokens. See `CONTEXT_AB_REVIEW.zh-CN.md` and
`REAL_REPLAY_REVIEW.zh-CN.md` for quality failures and test limitations.

Eighteen targeted order-only requests measured nonthinking service median 3.20 s
(max 3.72 s, n=10), versus thinking-low 29.21 s (max 41.37 s, n=8). Output budgets and
fixture mix differed, so this is a practical tradeoff, not a causal estimate.
Normal gameplay remains nonthinking. Session-level queue and serial cognition
steps add waiting beyond per-request service time; reducing those steps is still
a follow-up experiment, not an implemented speedup.

### Conditional tactical review follow-up

A separate matched-candidate run used 17 HTTP calls / 61,473 tokens / 48.6 s.
Twelve initial decisions produced one unacknowledged internal collision; that one
incurred a single 2.42 s review. Four replayed historical bad candidates also used
one review each (roughly 2.5–3.5 s); explicit intentional/foreign-cooperation
controls added zero calls. Clean decisions add no network round trip. This small
experiment measures local coordination, not win rate or entertainment. The normal
server option remains off by default; see `TACTICAL_REVIEW.zh-CN.md`.

The preserved, metered reports currently total **203 requests / 1,024,748 tokens**:
initial compatibility probes (8 / 20,398), first real year (50 / 154,828), context
A/B (60 / 531,179), consistency/thinking probe (18 / 102,061), second real year
(50 / 154,809), and tactical review (17 / 61,473). These are known report totals,
not a claim about account-wide billing or unrecorded early credential attempts.
No currency estimate has been inferred.
