# Stage-aware AI context

The AI uses deterministic local retrieval, with **no summarization model calls**. This controls prompt growth without turning diplomatic speech into board facts or forcing any personality to honor/break an agreement.

## Shared mandatory information

Every stage receives current public unit positions (including coasts and dislodgement markers), supply-center ownership/counts, the same saved private behavioral profile, private trust assessments with their assessment phase/evaluated evidence IDs, and recent own adjudication/coordination evidence. Trust assessments and lexical retrieval candidates are explicitly judgments/uncertainties, not public objective facts.

The fixed grounding rules are in the system role. Dialogue remains JSON-escaped user data. Neither retrieval nor the offline opponent reads other countries' pending orders or undelivered private messages.

## Stage limits

Limits are **UTF-8 bytes**, not model-tokenizer counts. They also bound character count. The diagnostic `estimated_tokens_bytes_div_4` is only a rough size estimate; actual provider usage is needed for token/cost comparisons.

| Stage | JSON context limit | Whole system + user prompt limit | Legal information |
| --- | ---: | ---: | --- |
| Attitude | 16,000 | 24,192 | Omitted |
| Intent | 18,000 | 26,192 | Movement/hold/retreat/build preview |
| Negotiation | 20,000 | 28,192 | Same preview; support/convoy list comes at order stage |
| Order | 40,000 | 48,192 | Every legal action, once, stable zero-based IDs |

Small order tables are ordinary arrays. Large tables use a lossless contiguous-prefix encoding when it saves space: `[start_id, prefix, suffixes]`. Each complete command is `prefix + ' ' + suffix`, and its ID is `start_id + suffix_index`. The model may always return a complete command verbatim. A regression with 2,603 legal commands verifies exact round-trip and legal offline orders; its legal payload shrinks from 55,916 to 30,575 bytes.

When a large legal table leaves little room, optional history is reduced before declaring overflow. The latest own adjudication, latest own bounce and latest important private warning are protected; omitted history is counted and a small dialogue window is reserved. Current board/legal facts are never cut to meet a byte quota. An exceptional mandatory-data overflow fails closed rather than silently removing legal choices. The session's existing provider-failure fallback remains in force; this is not a claim that every possible custom map fits these standard-map limits.

## Selection and uncertainty

- Memory retains at most 120 delivered records, reserving up to 32 older private offer/revision candidates against broadcast floods
- Prompt retrieval interleaves recent direct counterparts with relevant older direct candidates, then fills with relevant/recent visible evidence
- Lexical candidate tagging is deliberately incomplete and uncertain: original source ID, phase, scope, participants, `verified=false`, `acceptance=not_inferred`, and `expiry=not_inferred` remain attached
- A retained old proposal does not become an accepted or still-current agreement. Later revisions/refusals are retained as evidence to reconsider it
- Existing explicit ledger entries keep their remaining lifetime/status. Natural-language patterns do not create a binding ledger entry
- Long excerpts retain both ends, have an explicit clipping flag, and retain their source envelope
- Replayed phase history cannot make reinserted old filler appear more recent than final replies
- Exact rendered structured dialogue is removed from the redundant transcript. A new unmatched final inbox is still retained as unverified legacy text
- Memory diary/prose summaries and already-present intents are not repeated in every prompt

Safe `Agent.context_stats[stage]` contains only byte counts, budgets, legal counts/encoding, omission counts and reasons. It does not contain prompt bodies or message text. The prompt itself distinguishes missing/clipped evidence from disproved/resolved commitments.

## Offline measurement

`UV_CACHE_DIR=/tmp/diplomind-uv-cache uv run python scripts/benchmark_context_budget.py --label after --output artifacts/context-budget/after.json`

The matched synthetic baseline was captured before edits. Reports under `artifacts/context-budget/` compare empty opening and crowded diplomatic/bounce scenarios, with board/profile, older direct proposal, final message, unverified accusation, unresolved ledger entry, own bounce/warning and privacy-canary recall checks. These are deterministic coverage checks, **not evidence of stronger play or faster real-provider inference**. Real-model A/B testing must separately check latency, usage, negotiation accuracy and order quality.
