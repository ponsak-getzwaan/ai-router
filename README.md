# AI Router

A multi-layer AI message routing system on AWS. Reads messages from a chatbot, screens and classifies them, then dispatches to the appropriate AI vendor based on intent, safety, and business rules.

**Status**: pre-implementation. Architecture is finalised; code generation is in progress.

**Region**: `ap-southeast-1` (Singapore). Single-region by design for data residency.

---

## Quick links

- **`CLAUDE.md`** — operational steering for Claude Code sessions. Read this before generating code.
- **`docs/architecture.md`** — full architecture, layer-by-layer design, handoff contracts, deployment topology.
- **`docs/intent-taxonomy.md`** — intent taxonomy (placeholder; pending finalisation).
- **`docs/adr/`** — architecture decision records explaining *why* key choices were made.
- **`docs/diagrams/`** — editable draw.io source and exported SVG of the system architecture.

---

## Architecture in one paragraph

A request enters via API Gateway (with Cognito JWT validation at the edge) and lands in an SQS queue. The Orchestrator dequeues it, redacts PII through a Presidio sidecar, and drives it through four sequential layers: a **Bouncer** (rule gate + Haiku micro-classifier) that screens for safety, an **Intent classifier** (Bedrock Titan embeddings on the fast path, Sonnet + MCP tools on the deep path) that determines what the user wants, a **Routing strategist** that selects a vendor and applies policy (data residency, compliance), and a **Vendor adapter** layer (LiteLLM over Bedrock) that streams the response back via WebSocket. A correlation ID threads through every layer, and PII never appears in logs or downstream of the Orchestrator.

For the full picture, read `docs/architecture.md`.

---

## Repository layout

```
ai-router/
├── CLAUDE.md                          # steering for Claude Code
├── README.md                          # this file
├── pyproject.toml                     # (to be added)
├── docs/
│   ├── architecture.md                # full architecture
│   ├── intent-taxonomy.md             # intent taxonomy (pending)
│   ├── diagrams/
│   │   ├── architecture.drawio        # editable source
│   │   └── architecture.svg           # exported view
│   └── adr/
│       ├── 0001-bedrock-only.md
│       ├── 0002-presidio-as-sidecar.md
│       ├── 0003-cognito-jwt-at-edge.md
│       └── 0004-escalation-split.md
├── bouncer/                           # Layer 1: safety gate
├── classifier/                        # Layer 2: intent classification
├── strategist/                        # Layer 3: vendor selection + policy
├── adapters/                          # Layer 4: vendor adapters (LiteLLM/Bedrock)
├── redactor/                          # PII redaction (used by orchestrator)
├── orchestrator/                      # SQS consumer, pipeline driver
├── mcp_servers/                       # FastMCP servers exposing tools
├── admin/                             # Admin dashboard backend
├── presidio_sidecar/                  # Presidio HTTP service (ECS Fargate)
├── shared/                            # Cross-cutting utilities (models, logging, bedrock client)
├── tests/                             # pytest suite
└── infra/terraform/                   # Infrastructure-as-code
```

The application code directories are placeholders until the bootstrap PR.

---

## Getting started (developer)

Prerequisites:

- AWS account with Bedrock access in `ap-southeast-1` (Anthropic FTU form submitted).
- Python 3.12, [uv](https://github.com/astral-sh/uv), Docker.
- Terraform ≥ 1.6.
- AWS CLI configured (SSO recommended).

Local development:

```bash
# Install dependencies (once pyproject.toml exists)
uv sync

# Spin up local dependencies (LocalStack, Redis, Presidio sidecar)
docker compose up -d

# Run the test suite
uv run pytest -m "not aws"

# Run the orchestrator locally against LocalStack
uv run python -m orchestrator.main
```

For the full development workflow, see `docs/architecture.md` §"Phased rollout approach".

---

## Working with Claude Code on this repo

This repository is designed to be worked on with Claude Code. The `CLAUDE.md` file at the root encodes locked-in architectural decisions, non-negotiables, and known traps. Every Claude Code session in this directory reads it automatically.

If you change an architectural decision, update `CLAUDE.md` and write a new ADR in the same PR. Stale steering is worse than none.

---

## Key non-negotiables (see `CLAUDE.md` §3 for the full list)

1. All LLM calls go through Bedrock — no direct Anthropic/OpenAI clients.
2. JWT validated at API Gateway edge.
3. Single redaction policy applied uniformly to every LLM call.
4. Bouncer fails open on timeout (200ms budget).
5. Correlation ID threads everything via `ContextVar`.
6. No PII in logs, ever.
7. Bedrock invocation logging disabled.
8. Escalate, don't guess (low-confidence → human review).
9. Data residency enforced at IAM level, not only by policy engine.
10. Raw message never leaves the Orchestrator.

---

## Licence

TBD.
