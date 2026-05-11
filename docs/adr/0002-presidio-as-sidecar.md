# ADR 0002: Presidio runs as a persistent ECS Fargate sidecar, not in-process

- **Status**: Accepted
- **Date**: 2026-05-10
- **Deciders**: Project lead (Ponsak)
- **Consulted**: Architecture review (rounds 1 and 2)

---

## Context

PII redaction is mandatory before any message reaches an LLM (see `docs/adr/0004-escalation-split.md` for related context, and `docs/architecture.md` §"PII redaction"). The library chosen is **Microsoft Presidio**, with custom Singapore recognisers for NRIC, FIN, and UEN identifiers.

Presidio depends on a spaCy NLP model. The model is approximately **200 MB** in memory after loading, and loading takes **3–8 seconds** on cold-start. It is not optional — entity recognition requires it.

The router's pipeline has tight latency budgets. The Bouncer alone has a 200ms total budget. Redaction sits ahead of the Bouncer in the pipeline and contributes to overall request latency. The Orchestrator itself is a high-fan-in component handling every incoming request.

The deployment options for Presidio were:

1. **In-process inside the Orchestrator Lambda** — import Presidio as a Python library, load the spaCy model on cold-start.
2. **Container-image Lambda** — package Presidio as a Lambda container image to potentially reduce cold-start.
3. **Persistent ECS Fargate HTTP service** — run Presidio as a sidecar service, called over HTTP from the Orchestrator.

---

## Decision

**Presidio runs as a persistent ECS Fargate HTTP service** in a private subnet of the VPC. The Orchestrator (and any other component needing redaction) calls it over VPC-internal HTTP.

Topology:

```
VPC (ap-southeast-1)
└── Private subnet
    ├── ECS Fargate Service: presidio-sidecar
    │     Container: Presidio HTTP server (port 8080)
    │     Auto-scaling: min 1 task, max N tasks
    │     Health check: GET /health → 200 OK
    │
    ├── Orchestrator (ECS Fargate, Phase 1)
    │     Env: PRESIDIO_URL=http://presidio.internal:8080
    │     Calls: POST /anonymize, POST /restore
    │
    └── AWS Cloud Map (service discovery)
          presidio.internal → ECS task IPs
```

The token vault (Redis ElastiCache) holds redaction tokens with a 5-minute TTL, keyed `vault:{correlation_id}:{token}`. Output redactor looks up and restores tokens after the vendor response.

---

## Consequences

### Positive

- **Model stays warm.** The 200MB spaCy model is loaded once per ECS task and reused across thousands of requests. No per-request model load.
- **Network hop is negligible.** VPC-internal HTTP between Fargate tasks in the same private subnet is consistently 1–2 ms — well within the request latency budget.
- **Independent scaling.** Presidio task count scales on its own metrics (CPU, request rate) independently of Orchestrator scaling. A spike in redaction load doesn't force the Orchestrator to scale.
- **Independent deployment.** The Presidio service can be patched, restarted, or rolled back without touching the Orchestrator. New Singapore recognisers ship as their own deploy.
- **Language-agnostic clients.** Any service in the VPC can call Presidio via HTTP. The admin dashboard's test console, future MCP tools, or non-Python services all work without re-implementing.
- **Resource isolation.** Presidio's memory footprint doesn't compete with the Orchestrator's request handling.

### Negative

- **One more service to operate.** Health checks, auto-scaling rules, alarms, and IAM roles for the Presidio task are additional Terraform surface area.
- **Network failure mode.** If the Presidio service is unreachable, redaction fails. We treat this as a hard fail — the request is rejected, not allowed through unredacted. The alternative (fail-open redaction) is unacceptable per the non-negotiables. Mitigation: minimum 1 task at all times, with rapid auto-scaling and a CloudWatch alarm on health-check failures.
- **Service discovery dependency.** AWS Cloud Map is on the critical path. If Cloud Map fails to resolve `presidio.internal`, redaction fails. Standard AWS reliability is sufficient; we don't add a secondary discovery mechanism.
- **HTTP serialisation overhead.** Each request marshals the message to JSON over the wire and back. At the message sizes we handle (typically <4 KB), this is sub-millisecond and not a concern.

### Neutral

- The token vault is already a separate Redis cluster regardless of where Presidio runs. The sidecar topology doesn't add or remove this dependency.

---

## Alternatives considered

### A. In-process inside the Orchestrator Lambda

Rejected. The 3–8 second cold-start to load the spaCy model would impose that cost on every new Lambda instance. With bursty traffic patterns and the Lambda concurrency model, cold-starts would dominate p99 latency. Worse, the 200MB model would consume Lambda memory that should be available for request handling.

### B. Container-image Lambda

Rejected. Container-image Lambdas reduce some cold-start overhead but do not eliminate the model-load step — the spaCy model still has to be loaded into Python memory after the container starts. Empirically this still costs several seconds on cold-start. The persistent-process model fundamentally fits this workload better than any Lambda variant.

### C. Provisioned concurrency on a regular Lambda

Considered. Provisioned concurrency keeps a configured number of Lambda instances warm. Costs are continuous, comparable to running an ECS task. We rejected this because:

- Provisioned concurrency only mitigates cold-starts; it doesn't help when traffic exceeds the provisioned count and falls back to on-demand cold-starts.
- The operational model (configuring provisioned concurrency, monitoring its utilisation, autoscaling it) is more complex than running an autoscaling ECS service.
- The phased rollout plan keeps everything on ECS Fargate in Phase 1; Presidio fits naturally.

### D. AWS Comprehend instead of Presidio

Considered. AWS Comprehend has a PII detection API that would remove the model-hosting question entirely. Rejected because:

- Comprehend does not support Singapore-specific identifiers (NRIC, FIN, UEN) without custom training.
- Comprehend is a per-request paid API; cost scales linearly with traffic in a way that Fargate doesn't.
- Less flexibility on recogniser logic — Presidio lets us write deterministic regex-based recognisers for Singapore identifiers, with explicit test coverage in `tests/redactor/golden/`.

### E. Bedrock Guardrails as the primary redaction mechanism

Rejected as primary. Bedrock Guardrails are used as **defence in depth on output**, not as the primary input redaction. Reasons:

- Guardrails apply per Bedrock invocation; we want a single redaction pass at the orchestrator entry that all downstream LLM calls inherit.
- Guardrails do not produce a token vault we can use to restore the original entity in the user-facing response.
- The custom Singapore recognisers are a hard requirement and Guardrails do not directly support them.

---

## References

- `docs/architecture.md` §"PII redaction", §"Presidio sidecar deployment"
- `CLAUDE.md` §3 non-negotiable #3, #6, #10
- `CLAUDE.md` §7 "Redactor" gotchas
- Microsoft Presidio documentation
