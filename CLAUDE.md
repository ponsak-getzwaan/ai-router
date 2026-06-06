# CLAUDE.md — AI Router Project

> **Read this file at the start of every session.** It encodes locked-in decisions, non-negotiables, and known traps for this codebase. When in doubt between this file and your instinct, this file wins. When in doubt between this file and `project-summary.md`, the project summary wins (this file is its operational distillation).

---

## 1. Project at a glance

A multi-layer AI message router on AWS. Five sequential layers: **Bouncer → Intent classifier → Routing strategist → Vendor adapters**, with a **Redactor** wrapping the pipeline and an **Orchestrator** driving it. All LLM calls go through Bedrock. Region is `ap-southeast-1`. Authentication is Cognito + JWT validated at API Gateway.

The full architecture lives in `docs/architecture.md`. Read it before starting any new layer. Decision rationale (the *why* behind the non-negotiables) lives in `docs/adr/`.

### Where the content lives (use this map; don't search)

| If you need... | Read |
|---|---|
| Admin dashboard frontend (React SPA) — tech stack, auth flow, per-view specs, deployment | `docs/admin-dashboard.md` |

If a topic doesn't appear above, it's either in this file (below) or hasn't been decided yet — leave a `# TODO(spec):` and surface in the PR description.

---

## 2. Locked decisions (do not re-litigate)

These were open questions in the project summary. They are now closed.

| Decision | Choice | Notes |
|---|---|---|
| IaC tool | **Terraform** | All infra under `infra/terraform/`. CDK is not used. |
| Python version | **3.12** | Match across all services and Dockerfiles. |
| Dependency manager | **uv** | `uv.lock` committed. No `requirements.txt`. |
| Data validation | **Pydantic v2** | All handoff models inherit from `pydantic.BaseModel`. No dataclasses, no attrs. |
| Vendor adapter library | **LiteLLM, pinned to a known-good version** | Avoid 1.82.7 and 1.82.8 (security advisories). Pin in `pyproject.toml`, do not float. |
| Deployment topology | **Phase 1 of project summary** — every layer is one ECS Fargate service. No Lambda yet. | Phase 2 migration is a future task; do not pre-optimise. |
| Handoff between layers | **Direct async calls within the orchestrator process** (Option A in summary) | Per-layer SQS queues are Phase 3, not now. |
| Bedrock model IDs | **Cross-region inference profiles only** (e.g. `apac.anthropic.claude-3-haiku-20240307-v1:0`) | Raw model IDs fail with "on-demand throughput not supported". Always use the inference profile ARN/ID. |
| Logging | **`structlog` with an allowlist-based context processor** | See §5. |
| Test framework | **pytest + pytest-asyncio** | LocalStack for SQS/DynamoDB, fakeredis for Redis, moto only where LocalStack is awkward. |

If a future task genuinely requires changing one of these, **flag it explicitly in the PR description** rather than silently switching.

---

## 3. Non-negotiables (the system fails review if any of these are violated)

These come straight from `docs/architecture.md` §"Key Principles". Repeated here because they are easy to drift from when generating code:

1. **All LLM calls go through Bedrock.** No `import anthropic`, no `import openai`, no direct OpenAI/Anthropic HTTP clients. Vendor calls go through LiteLLM configured against Bedrock, or `boto3.client("bedrock-runtime")` directly. CI enforces this — see §6.
2. **JWT validated at the edge.** API Gateway authoriser rejects unauthenticated requests. Pipeline code never re-validates the JWT and never trusts an unauthenticated `user_sub`.
3. **Single redaction policy applied uniformly** to every LLM call (Haiku bouncer, Sonnet classifier, vendor Claude). One redaction pass at orchestrator entry. Do not add per-layer redaction. Do not skip redaction "because it's just the bouncer".
4. **Fail-open Bouncer.** A 200ms timeout means the request is **allowed downstream with a logged warning**, not rejected. The natural-feeling code is wrong here. The tests enforce it; if you change the test, you have broken the spec.
5. **Correlation ID threads everything.** Set as a `ContextVar` at orchestrator entry. Do **not** pass `correlation_id` as a function argument through every layer signature — that path leads to spaghetti. Every log line emits it via the structlog processor.
6. **No PII in logs ever.** Use `safe_log()` from `shared/logging.py`. Allowlist-based: only fields in the allowlist are emitted. Never log `error.message`, only `type(error).__name__`. See §5.
7. **Bedrock invocation logging disabled.** Terraform sets `loggingConfig: null` on every Bedrock invocation. Do not enable it "for debugging".
8. **Escalate, don't guess.** If confidence is below the threshold for that layer, route to the human review SQS queue. Do not pick a default vendor when uncertain.
9. **Data residency at the application layer.** Bedrock IAM uses `Resource: *` with no region condition — both `aws:RequestedRegion` and `apac.*` resource ARN restrictions cause `AccessDeniedException` because APAC cross-region inference profiles route internally through other AWS regions and check IAM against the underlying `anthropic.*` foundation model ARNs. Data residency is enforced by **only using `apac.*` inference profile IDs** in all layer configs; do not add a raw `anthropic.*` model ID anywhere in code or config.
10. **Raw message never leaves the Orchestrator.** Only `redacted_message` flows in `PipelineEnvelope` to downstream layers. The raw message is hashed (`raw_message_hash`) for audit but never propagated.

---

## 4. File layout (target)

Generate code into this structure. Do not invent new top-level directories without discussion.

```
bouncer/         classifier/     strategist/     redactor/
adapters/        orchestrator/   mcp_servers/    admin/
presidio_sidecar/                shared/         tests/
infra/terraform/
```

`shared/` holds: `models.py` (all Pydantic handoff types), `logging.py` (`safe_log`, structlog config), `bedrock.py` (Bedrock client factory), `correlation.py` (ContextVar setup), `errors.py` (typed exceptions).

Per-layer file breakdown matches `docs/architecture.md` §"File structure". Stick to it.

---

## 5. Logging — the rule that gets violated most often

Default LLM-generated code writes things like `logger.exception(e)` or `logger.info(f"processing message: {message}")`. **Both leak.** Use this pattern instead:

```python
from shared.logging import safe_log

safe_log.info(
    "bouncer.rule_gate.passed",
    correlation_id=...,        # auto-injected via ContextVar, do not pass manually
    user_sub=user_sub,         # allowlisted
    rule_gate_latency_ms=4.2,  # allowlisted
    # message=raw_text         # WRONG: not in allowlist, would be dropped
)
```

The allowlist lives in `shared/logging.py`. To add a new field, add it to the allowlist explicitly and justify it in the PR. **Errors are logged as type names, not messages:**

```python
except BedrockTimeout as e:
    safe_log.warning("bouncer.haiku.timeout", error_type=type(e).__name__)
    # WRONG: error_message=str(e) — may contain echoed user input
```

---

## 6. CI guardrails (already in `.github/workflows/`)

These checks run on every PR. Don't bypass them.

- **`forbidden-imports`**: greps for `^import (anthropic|openai)` and `^from (anthropic|openai)` outside `tests/`. Fails the build.
- **`pii-in-logs`**: AST-based check that `logging.*` and `print()` are not called with f-strings or `%` formatting that interpolate variables named `message`, `body`, `content`, `prompt`, `text`, `email`, `phone`. Use `safe_log` instead.
- **`tflint` + `checkov`**: Terraform static analysis. Bedrock IAM policy must include the `ap-southeast-1` region condition.
- **`pytest -m "not aws"`**: unit and integration tests run on every PR. AWS-marked tests run on merge to main against a sandbox account.
- **`mypy --strict`**: every module under `bouncer/`, `classifier/`, `strategist/`, `redactor/`, `orchestrator/`, `shared/`. No `# type: ignore` without a justification comment.

---

## 7. Per-layer gotchas

### Bouncer
- **Sequence**: see `docs/architecture.md` §"Layer 1 — Bouncer" → "Sequence". Read it before writing Bouncer code; the fail-open posture is the easiest thing to get wrong.
- The 200ms is the **total** budget across rule gate + Haiku, not per-stage. Rule gate must finish in single-digit ms.
- Fail-open on timeout. The `BounceResult.timed_out` field is `True`, `allowed` is also `True`, and a CloudWatch metric `BouncerTimeout` is incremented.
- Banned-user check uses `user_sub`, never email.

### Classifier
- Fast-path embedding similarity threshold is a config value, not a magic number. Default lives in `classifier/config.py`.
- `resolved_message` is the message **after pronoun resolution**, still redacted. Never store the raw resolved message anywhere.
- MCP tool calls are issued in parallel via `asyncio.gather`, not sequentially. Sequential calls blow the latency budget.

### Strategist
- Vendor health check is **always** issued in parallel with the rule lookup, even on the deterministic path (≥0.85 confidence). The summary is explicit about this.
- The fallback chain is per-intent, not global. `strategist/fallback_chain.py` reads from DynamoDB per intent.
- Policy engine runs **after** vendor selection. Selecting a non-`ap-southeast-1` vendor for an SG user must be blocked by the policy engine, not silently rerouted.

### Redactor
- Presidio is a **persistent ECS Fargate service**, called over VPC-internal HTTP. Do not import Presidio into the orchestrator process. The 200MB spaCy model cannot live in a Lambda.
- Token vault keys: `vault:{correlation_id}:{token}`. TTL 5 minutes. Never longer — that's the security boundary.
- Streaming buffer: 200 chars with 50-char safety margin. The constants live in `redactor/streaming_redactor.py`. Don't tune them without re-running the golden tests.
- Custom Singapore recognisers (`SG_NRIC`, `SG_FIN`, `SG_UEN`) live in `redactor/recognisers.py` and have golden-file tests in `tests/redactor/golden/`. Run those tests after any recogniser change.
- Output leak detector runs on the **restored** vendor response and strips any unexpected PII. The list of "expected" entity types is whatever was in the original input — anything new in the output is treated as a leak.

### Adapters
- LiteLLM config is in `adapters/litellm_adapter.py`. Models are referenced by **inference profile ID**, not raw model ID.
- Streaming is enabled by default. Non-streaming is a flag on the adapter call, not a separate code path.

### Orchestrator
- **Sequence**: see `docs/architecture.md` §"Architecture — the five processing layers" → "End-to-end request sequence". This is the canonical "what runs in what order" for the whole pipeline.
- `correlation_id` is set in `orchestrator/sqs_consumer.py` as the very first action when a message is dequeued. Every downstream call inherits it via `ContextVar`.
- `PipelineEnvelope` is constructed once, after redaction, and is immutable thereafter. If a layer needs to add metadata, it returns a new envelope or a sibling result object.
- Audit logging happens in a `finally` block so it runs on both success and failure paths.

### Admin dashboard
- Read-heavy. The only write surfaces are: routing rule editor, escalation queue actions (approve/reject/requeue), tier overrides. Anything else is a bug.
- IAM role explicitly denies `bedrock:*`, `sqs:SendMessage` on the incoming queue, and `dynamodb:DeleteItem`. The `Deny` is the safety net; the role's `Allow` block is also narrow.
- Test console traces are logged with redacted messages only. The console is **not** a debugging escape hatch for raw input.

---

## 8. Bedrock specifics

- Region: `ap-southeast-1` (Singapore). Hard-coded in IAM policy conditions and in the Bedrock client factory in `shared/bedrock.py`.
- Model IDs (use cross-region inference profiles):
  - Haiku: `apac.anthropic.claude-3-haiku-20240307-v1:0` — for the Bouncer micro-classifier and Strategist arbitration.
  - Sonnet: `global.anthropic.claude-sonnet-4-6` — for deep-path intent classification and default vendor routing. Global cross-region profile, invoked from ap-southeast-1, 10 RPM. Data-residency trade-off: compute may route outside ap-southeast-1 (accepted — no APAC profile exists for this model).
  - Verified active in ap-southeast-1 on 2026-06-07. Do not change without re-verifying via `aws bedrock list-inference-profiles` and a direct test invoke.
  - **TRAP**: `apac.anthropic.claude-sonnet-4-20250514-v1:0` lists as an APAC profile but is LEGACY and returns ResourceNotFoundException — do not use. Claude Sonnet 4.5/4.6 Llama have no APAC profiles. Always test invoke before deploying any new model ID.
- First-time use: each AWS account hitting Anthropic models needs the FTU form submitted once. Console clicks, not Terraform.
- `bedrock-runtime` invocation logging is **disabled**. Application-level logging via `safe_log` is the audit trail.

---

## 9. Testing expectations

- **Unit tests** are mandatory for every layer. Coverage gate: 85% on the layer modules, 100% on `redactor/` (it's the security boundary).
- **Contract tests** validate every Pydantic model in `shared/models.py` round-trips through JSON.
- **Golden-file tests** for the redactor: input message → expected redacted output + expected entity types. Located at `tests/redactor/golden/`.
- **Integration tests** run the full pipeline in-process against LocalStack and fakeredis. Marked `@pytest.mark.integration`.
- **AWS tests** (`@pytest.mark.aws`) run against a sandbox account on merge to main, not on every PR. They cost real money. Don't run them in a loop.

When generating new code, write the test first, see it fail, then write the implementation. This is not optional for the redactor or the bouncer.

---

## 10. What to do when uncertain

- **Spec ambiguity** → re-read `docs/architecture.md`, then check `docs/adr/` for the decision rationale. If still ambiguous, leave a `# TODO(spec):` comment and flag it in the PR description. Do not invent.
- **AWS permission you're not sure exists** → check the actual IAM policy in `infra/terraform/iam.tf`. If it isn't there, the code shouldn't depend on it.
- **A "helpful" optimisation that touches a non-negotiable** → don't. The non-negotiables in §3 outweigh any latency or cost win.
- **A library you'd reach for that isn't pinned in `pyproject.toml`** → propose it in the PR description before adding. Especially anything that talks to an LLM provider directly.

---

## 11. Out of scope for any single session

These are explicitly **not** to be tackled in passing:

- Migrating any layer from ECS to Lambda (Phase 2 work).
- Adding per-layer SQS queues (Phase 3 work).
- Lambda provisioned concurrency tuning (Phase 3 work).
- Multi-region failover. The system is single-region (`ap-southeast-1`) by design for data residency.
- Model fine-tuning or custom evaluation harnesses on Bedrock.
- Anything that would require a new top-level directory in §4.

If a task genuinely needs one of the above, it gets its own design doc and its own PR series.
