# Cloud rebuild validation

This branch targets Classic mixed human/AI play. Plus is deferred.

## Automated checks

- Python: 414 tests passed, including core rules, multiplayer identity/privacy,
  room lifecycle, private persistence, stale/idempotent actions, providers,
  persona evidence and secure input smoke-runner contracts
- JavaScript: 8 pure frontend tests passed
- `compileall` and JavaScript syntax checks passed
- `git diff --check` passed
- One dependency warning remains: Starlette's TestClient reports deprecation of
  its httpx integration. This is a test-tool warning, not a game failure

## Real-browser offline acceptance

Executed in the cloud desktop's installed Chromium with separate contexts for
France and Germany, five deterministic heuristic opponents and a public observer.
The tests interact with actual buttons, forms and selectors; API reads provide
independent assertions. No language model credentials are used.

Verified:

1. Real WebGL board and all four Blender GLB assets loaded
2. Setup close/reopen, independent seat identities and nickname escaping
3. Duplicate start rejected without resetting the board
4. Private messages stay staged until round completion and reach only participants
5. 2D map unit selection, per-unit legal commands, editing/removal and 3D order arrows
6. Refresh and offline reconnect preserve identity and local drafts
7. First human submission waits for the other human; withdrawal works before settlement
8. Same-room checkpoint restores pending orders, keeps identities and pauses for review
9. Both humans advance together from S1901M through F1901M and W1901A to S1902M
10. Mobile viewport has no horizontal overflow and retains room navigation/end controls
11. No uncaught browser exceptions

The first browser pass exposed mobile room navigation hidden by desktop-only CSS,
toasts covering the command editor, and excessive continuous 3D rendering. These
were fixed and rerun. Render-on-demand reduced the complete acceptance run to
approximately 31 seconds on the same software-rendered cloud browser.

Reproduce with a server using `conf/mock.json`, then run
`uv run python scripts/e2e_mixed.py`. The latest machine-readable result and
screenshots are generated under `artifacts/e2e/` (not committed).

The additional `scripts/ui_message_race.py` regression reproduced the rapid
private-modal/input race against a mock server, then verified the fix: exactly
once recipient routing, separate channel drafts after refresh, late ACK
isolation, failed-send recovery with stable request identity, and no observer or
wrong-recipient exposure. Browser clicks alone are not treated as delivery ACKs.
Its final seven checks passed in 19.03 seconds. The final core nine-check browser
run passed in 38.65 seconds with no uncaught page exceptions. It also exposed and
fixed delayed setup focus stealing the nickname into the room-code input.

## 3D asset validation

Four genuine GLBs, 368,752 bytes combined, 7,080 triangles. Exported and reimported
through Blender; finite geometry, centered ground bounds, material names and
triangle counts checked. Editable `.blend`, deterministic generator and visual
preview are included. The standard province geometry derives from the same map
package used by adjudication.

## Authorized real-provider compatibility check

On 2026-09-30, a user-triggered cloud-terminal check reached the selected Aliyun
OpenAI-compatible endpoint with `deepseek-v4.1-flash`. The default-thinking run
passed attitude JSON validation, then stopped on the second call's 700-token
output truncation. Provider-reported usage: 4,636 input and 1,076 output tokens.
The report does not retain raw responses, so it cannot establish whether hidden
reasoning or verbose answer text consumed that limit.

The separately approved six-call rerun explicitly disabled thinking and used two
contrasting personas with the same seeded trust state. Both completed intent,
negotiation and order selection, including a final human reply in the order
context. All outputs passed schema checks; all three orders per persona were
engine-legal and accepted. Six calls completed without retry, each in 1.95–3.27
seconds. Provider-reported usage: 14,307 input and 379 output tokens.

These two file-triggered checks total eight requests and 20,398 reported tokens;
this is not a billing quote or a total for any earlier terminal attempts. Only
synthetic game data was sent. The live browser demo remains on its mock provider.

## Bounded real-model year

The later, separately approved application-configured run used two independently
controlled browser seats and five Aliyun AI opponents. It completed Spring and
Fall 1901 plus winter builds, with exactly 50 HTTP requests and no retries.
Reported usage was 146,788 input plus 8,040 output tokens. One OrderSet response
failed the original generic response check and fell back to holds. Its old
metadata cannot establish the exact failure class; future-only diagnostics now
separate failures without retaining raw response text.

The server reached S1902M and stopped at its 600-second limit without starting
1902 cognition. The engine's capped-draw flag is a test-stop marker, not an
official result. AI retreat/build decisions and the test chronicle were local.
See [the evidence-scoped Chinese review](REAL_GAME_REVIEW.zh-CN.md),
[published orders/results](evidence/1901-public-orders.json), and the unchanged
[safe provider metadata](evidence/1901-provider-metadata.json).

## Verification limits

- Offline tests validate gameplay plumbing and heuristic policies. They do not
  prove real LLM intelligence, humanlike diplomacy or entertainment value
- CLI adapter flags, isolation and output handling are tested using subprocess
  fixtures. No authenticated Codex/Claude Code/Qoder CLI was executed
- The bounded real-provider runner is independently tested with fake endpoints
  and passed the compatibility check above. One bounded real-model year was
  played, with documented failures. Strategic strength, believable personality,
  entertainment and post-fix live behavior have not been established
- Server process restart recovery is covered by backend tests; network loss and
  browser reload are additionally covered in the real-browser scenario
- Multiplayer was tested on one server/process. Internet deployment, load testing,
  horizontal scaling, account recovery and unanimous draw voting remain future work
- No remote Git push, pull request or public deployment was performed
