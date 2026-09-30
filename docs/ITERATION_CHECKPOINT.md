# Verification checkpoint — 2026-09-30

This source snapshot includes the cloud Classic rebuild, Blender source/assets,
privacy/state-machine fixes, compact context retrieval, real-provider request
options, private server-only key-file references, timer-delta SSE, safe diagnostics,
and readiness gesture guards. Plus remains deferred.

Final checks:
- Python suite: 539 passed; one opt-in native-browser test skipped in the shell
- The skipped readiness test separately passed in real native cloud Chromium
- Frontend Node suite: 21 passed
- Fresh two-human + five-mock-AI + observer browser acceptance: 9 checks passed
- Enabled order-review browser acceptance: 9 checks passed with two simulated review failures
- Real-provider evidence: 60-call context A/B, 18-call order consistency probe,
  the second 50-call mixed-browser 1901 game, and the 17-call tactical review,
  with limitations in linked reports

The last bounded real game finished 1901 and stopped. The convoy diagnostics and optional one-pass tactical review subsequently passed
a small bounded real-provider test. The new server option is off by default and
has not yet been used in another full real game. Illegal orders, tactical mistakes
and inaccurate diplomatic claims remain demonstrated limitations, not solved
capabilities. See `TACTICAL_REVIEW.zh-CN.md`.

Use the project README for local startup. The distributed source contains no
private key, private runtime provider binding, environment directory, seat token,
room save, raw provider output, or Git history. Existing operator configuration
outside the bundle has not been removed. CLI adapters remain experimental and
have not been validated with authenticated Codex/Claude/Qoder executions.
