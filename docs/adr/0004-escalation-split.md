# ADR 0004: Escalation split — Review Log (async audit) vs. Human Handoff (real-time fallback)

- **Status**: Accepted
- **Date**: 2026-05-10
- **Deciders**: Project lead (Ponsak)
- **Consulted**: Architecture review (rounds 1 and 2)

---

## Context

The original architecture had a single concept called "escalation": when any pipeline layer (Bouncer, Classifier, Strategist) returned low confidence, the request was routed to a human review queue. The user's request was held until a human reviewed it.

Architecture review surfaced a structural problem with this design: it conflated **two fundamentally different concerns** under one mechanism.

1. **Real-time user response** — the user is waiting for an answer right now. They cannot wait for a human reviewer (whose response time is measured in minutes to hours, at best). If the pipeline can't decide what to do, the user still needs *some* response — a clarification request, a fallback vendor, or a graceful "I'm not sure, can you rephrase?" — within the latency budget.
2. **Offline human review** — operations and compliance need a record of low-confidence cases for ongoing model improvement, taxonomy refinement, and audit. This is asynchronous; it doesn't have to complete during the user's request.

When these are merged into one queue, the user-facing path becomes blocked on human throughput, which is the wrong design. Most low-confidence cases don't actually need human review to resolve — they need a clarifying question, a safe fallback vendor, or a polite refusal. True hard escalation to a human is rare.

---

## Decision

**Split the single "escalation queue" into two distinct mechanisms with separate concerns and separate latencies.**

### 1. Review Log (asynchronous, DynamoDB)

- Every low-confidence pipeline event is **logged to DynamoDB** with the redacted message, layer of origin, confidence score, and outcome.
- This is **fire-and-forget audit data**. It does not block the user response.
- The admin dashboard's "Escalations" view reads from this log for ongoing review.
- Operators triage entries asynchronously: refine the classifier, add an exemplar to a fast-path embedding, update routing rules, or adjust thresholds.

### 2. Graceful Degradation Ladder (real-time)

When a layer returns low confidence, the user response path follows a ladder, in order:

1. **Hedge** — try the next-most-likely intent / vendor with a tighter timeout.
2. **Clarify** — return a clarifying question to the user ("Did you mean X or Y?"). The user's response re-enters the pipeline with disambiguation context.
3. **Fall back** — route to a safe default vendor with a generic prompt that handles ambiguity well.
4. **Hand off** — only if all of the above fail or are inappropriate (e.g. high-stakes regulated query). This is the **one and only path** that involves a human ticket.

The Hand-Off path emits a ticket to a separate ticketing system (out of scope for this ADR; could be Zendesk, Jira Service Management, or a dedicated SQS queue with a human-tooled UI). The user is told their query has been handed off and is given a reference. The ticket is the contract for human follow-up; the pipeline does not block waiting for it.

Importantly: **Review Log entries are emitted at every step of the ladder.** A request that resolves via "Clarify" still produces a Review Log entry, because the operations team wants to see "we asked the user to clarify because confidence was low" as data for improving the classifier.

---

## Consequences

### Positive

- **Real-time path is never blocked on human review.** The user always gets a response within the request's latency budget, even when confidence is low.
- **Operations gets richer data.** Review Log captures every low-confidence event, not just the cases that escalated to a human. This is a much larger and more useful dataset for taxonomy and classifier refinement.
- **Human review is rare and high-signal.** When a request reaches Hand-Off, it's because the ladder couldn't resolve it. Human reviewers see the genuinely hard cases, not every confidence dip.
- **Each layer of the ladder has a clear, testable behaviour.** "Hedge" has its own timeout. "Clarify" produces a specific response shape. "Fall back" picks a known-safe vendor. "Hand off" emits a ticket. Each can be unit-tested independently.
- **Confidence thresholds become tuning knobs, not policy levers.** Lowering the threshold no longer means "more humans get paged"; it means "more requests use the clarify path." The operational consequence of threshold changes is bounded.

### Negative

- **More moving parts.** Two distinct outputs (Review Log + ticket system) plus a four-step ladder is more surface area than a single queue. We accept this because the original single-queue design was structurally wrong for the workload.
- **Defining "safe fallback vendor" requires care.** A safe default that handles ambiguity well is not the same as the default vendor for any specific intent. The fallback vendor selection is a config decision per domain.
- **Clarify-path UX requires product thinking.** A clarifying question is a user-facing string; it must be well-phrased and not feel like a bug. This is a content/product investment, not just an engineering change.
- **Ticket system is out of scope here.** The ADR commits to the split but doesn't specify the ticketing implementation. That's a follow-up decision.

### Neutral

- The DynamoDB cost of the Review Log is negligible at expected scale (<100 KB per entry, 365-day retention).

---

## Alternatives considered

### A. Keep the single escalation queue, accept that real-time users wait for humans

Rejected. This bakes human review latency into every low-confidence user response. Median human response is minutes; users tolerate seconds. The UX is unacceptable.

### B. Single queue with a fast-path "clarify or fall back" check before queuing

Considered. The check would route some low-confidence cases away from the queue and resolve them inline. This is essentially the ladder, but with the queue acting as the catch-all rather than a separate hand-off channel. We rejected it because the queue then has dual semantics (real-time fallback target + async audit log) and the queue's storage and retention requirements differ between the two uses.

### C. Make every low-confidence case go to clarify by default, no human path at all

Rejected. There are queries (regulated financial advice, legal questions where the user appears to be in distress, edge cases involving safety) where the right answer is a human, not a clarification or a fallback vendor. The ladder explicitly preserves Hand-Off as the last rung for these cases.

### D. Hard-code different escalation behaviour per layer

Rejected. The ladder applies uniformly across layers: Bouncer low confidence, Classifier low confidence, and Strategist low confidence all funnel through the same hedge → clarify → fall back → hand off sequence. The layer of origin is logged for analytics but doesn't change the resolution logic. A uniform ladder is simpler to operate and reason about.

---

## Open questions

These are deliberately left for follow-up rather than locked in here:

- **Ticketing system choice** — Zendesk, JSM, internal tooling, or a custom SQS-backed UI. The ADR commits to "a ticket system exists"; the specific one is a separate decision.
- **Clarify-path response templates** — the wording and shape of clarifying questions per domain. This is product/content work.
- **Fall-back vendor configuration** — which vendor + prompt combination is the "safe default" for each top-level domain. Locked once the intent taxonomy is finalised (`docs/intent-taxonomy.md`).
- **Hand-Off SLA** — the user-facing commitment ("we'll get back to you within X hours"). Operational, not architectural.

---

## References

- `docs/architecture.md` §"Layer 1", §"Layer 2", §"Layer 3", §"Admin Dashboard"
- `CLAUDE.md` §3 non-negotiable #8 ("escalate, don't guess")
- `docs/intent-taxonomy.md` — fallback vendor configuration depends on this
