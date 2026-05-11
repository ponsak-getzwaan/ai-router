# ADR 0001: All LLM calls go through Amazon Bedrock

- **Status**: Accepted
- **Date**: 2026-05-10
- **Deciders**: Project lead (Ponsak)
- **Consulted**: Architecture review (rounds 1 and 2)

---

## Context

The router invokes LLMs at three points in the pipeline:

1. **Bouncer Haiku micro-classifier** — a fast safety check on every message that passes the rule gate.
2. **Intent classifier deep path** — Sonnet with MCP tools, used when fast-path embedding similarity is inconclusive.
3. **Vendor adapter layer** — the actual response-generating model the user receives.

Each of these could, in principle, call any LLM provider directly: Anthropic's API, OpenAI, Google, self-hosted models, or Amazon Bedrock. The choice has consequences for billing, compliance, audit, network egress, and IAM design.

The system targets Singapore users and is hosted in `ap-southeast-1`. Data residency is a binding requirement, not a preference. Audit and cost attribution per request are operational requirements from the admin dashboard.

---

## Decision

**All LLM calls go through Amazon Bedrock.** No direct API clients for Anthropic, OpenAI, or any other provider are permitted in production code.

Concretely:

- Vendor adapters use **LiteLLM configured against Bedrock**, or `boto3.client("bedrock-runtime")` directly.
- Model identifiers are **cross-region inference profile IDs** (e.g. `apac.anthropic.claude-haiku-4-5-...`), not raw model IDs.
- IAM policies on every compute role include a `Condition` block locking `aws:RequestedRegion` to `ap-southeast-1`. This is enforced at the IAM layer, not only by application code.
- Bedrock invocation logging is **disabled** on every model call to prevent PII leaking into AWS-managed logs.
- CI enforces the rule: a `forbidden-imports` job greps for `import anthropic` / `import openai` outside the test tree and fails the build.

---

## Consequences

### Positive

- **Single IAM-enforced data residency boundary.** Bedrock requests cannot leave `ap-southeast-1` because the IAM policy condition rejects them. This is stronger than application-level enforcement, which can be bypassed by a code bug.
- **Single billing surface.** All LLM spend appears in AWS Cost Explorer under one service, taggable by ECS service and request correlation ID. No reconciliation across multiple vendor invoices.
- **Single audit path.** CloudTrail captures every `InvokeModel` call. Combined with our application-level audit log, this is sufficient for compliance review without integrating multiple vendor APIs.
- **Single auth model.** AWS IAM is the only credential to manage. No vendor API keys to rotate, store in Secrets Manager, or accidentally commit.
- **Networking simplification.** All LLM traffic stays inside the AWS VPC via Bedrock VPC endpoints. No public internet egress for model calls.
- **Cross-vendor unification.** LiteLLM over Bedrock lets us route to Claude, Llama, or Mistral with the same client code. Adapter changes are config, not code.

### Negative

- **No access to vendors not on Bedrock.** OpenAI's GPT-series, Google Gemini, and others are unreachable. If a future intent is best served by GPT-4o, we cannot route to it without redesigning this boundary.
- **Bedrock-specific constraints.** Modern Claude models on Bedrock require cross-region inference profiles for on-demand throughput. Raw model IDs fail with "on-demand throughput not supported" errors. This adds a small operational burden (pinning the right profile ID per region).
- **Bedrock model availability lag.** New Anthropic models reach the direct Anthropic API before Bedrock. We accept a delay of days to weeks before new model versions are usable.
- **Model access provisioning.** Each AWS account must complete the Anthropic FTU (first-time use) form once. This is a manual console step, not Terraform.

### Neutral

- LiteLLM version pinning becomes a security-sensitive decision. Versions 1.82.7 and 1.82.8 had known advisories; the pin is reviewed in `pyproject.toml`.

---

## Alternatives considered

### A. Mixed: Bedrock for production, Anthropic API for dev/test

Rejected. The whole point of the IAM-level data residency boundary is that there is no escape hatch. Allowing direct Anthropic calls in any environment risks credentials or code paths leaking into production. Developers can use Bedrock locally with personal AWS credentials or a sandbox account.

### B. Direct Anthropic API + a self-managed proxy

Rejected. This would replicate Bedrock's value (audit, region locking, single billing) without Bedrock's operational maturity. The proxy itself would become a critical security component requiring its own audit and hardening.

### C. Multi-vendor (Anthropic API for some calls, Bedrock for others, OpenAI for others)

Rejected for v1. The complexity of multi-vendor credential management, multi-vendor audit trails, and multi-vendor data residency review outweighed the benefit of optionality. Phase 2 may revisit if a specific intent demonstrably needs a non-Bedrock model and the residency story can be made consistent.

### D. Self-hosted models only

Considered for the Bouncer specifically (self-hosted DeBERTa was floated in earlier reviews). Rejected for the Bouncer in favour of Haiku via Bedrock — the operational cost of running a model-hosting tier in addition to Bedrock outweighed the latency win. The current design uses Bedrock Haiku for the Bouncer LLM and Bedrock Titan embeddings for the classifier fast path.

---

## References

- `docs/architecture.md` §"Technology stack", §"Layer 1", §"Layer 4"
- `CLAUDE.md` §3 non-negotiable #1, #7, #9
- AWS Bedrock cross-region inference profiles documentation
