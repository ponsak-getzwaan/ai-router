# Intent Taxonomy

> **Status**: 🟡 **Pending finalisation.** This is the key open decision blocking classifier training and final diagram labelling. Diagrams currently use placeholder intent labels.

---

## Purpose

The intent classifier (Layer 2) categorises every incoming user message into a three-level hierarchy: **domain → intent → sub-intent**. This taxonomy drives:

1. **Routing decisions** — Layer 3 maps each `(domain, intent, sub_intent)` triple to a primary vendor and fallback chain.
2. **Classifier training** — the fast path (Bedrock Titan embeddings) needs labelled exemplars per leaf node; the deep path (Sonnet + MCP) needs the taxonomy as a tool-fetched reference.
3. **Policy engine triggers** — certain intents (e.g. MAS-regulated financial advice, tenancy law) trigger compliance blocks.
4. **Audit and analytics** — the admin dashboard surfaces intent distribution as a primary metric.

The taxonomy is stored in DynamoDB (`intent_taxonomy` table) and fetched by classifier instances via the `get_intent_taxonomy` MCP tool. Changes take effect immediately without redeployment.

---

## Working scaffolding (placeholder — not final)

Until the taxonomy is finalised, code and diagrams use the placeholder labels from `docs/architecture.md` §"Layer 2":

| Domain | Intent | Default vendor |
|---|---|---|
| `general_qa` | (sub-intents TBD) | claude-sonnet |
| `code_assistance` | (sub-intents TBD) | claude-sonnet |
| `simple_transactional` | (sub-intents TBD) | claude-haiku |
| `out_of_scope` | — | escalation |
| `ambiguous` | — | escalation |

These four placeholder domains are sufficient to scaffold the classifier interface, the routing rule schema, and the test fixtures. **They are not the production taxonomy.**

---

## Open questions to resolve

The two domain candidates currently under discussion are:

1. **Property investment** — sub-domains around residential vs. commercial, transaction stages (search/finance/legal/handover), and Singapore-specific concerns (BSD/ABSD, HDB rules, en-bloc, tenancy under URA/HDB regimes).
2. **Enterprise SG business** — sub-domains around incorporation, MAS-regulated financial services, employment law, IP, contracts.

The decisions to make:

- **Are these two separate top-level domains, or sub-domains of a broader Singapore-vertical taxonomy?**
- **What's the granularity at the sub-intent level?** Too shallow and routing is generic; too deep and the classifier has too few exemplars per leaf to train reliably. Target: 3–8 sub-intents per intent, with at least 50 labelled exemplars each for the fast path.
- **Where does the line sit between `general_qa` and a domain-specific intent?** "What is BSD?" vs. "Should I pay BSD on this purchase?" — the second is regulated advice, the first isn't. The taxonomy needs a clear principle for this kind of edge case, not just a list.
- **What triggers the policy engine?** Per intent? Per sub-intent? Per entity present in the message? `docs/adr/0003-cognito-jwt-at-edge.md` and the policy engine section of `docs/architecture.md` §"Layer 3" are the relevant context.
- **How are multi-domain queries handled?** The `multi_domain` flag on `ClassifiedIntent` exists, but the routing semantics for multi-domain intents (split-and-merge? primary-only? escalate?) need to be specified.

---

## Format (once finalised)

The DynamoDB representation will look roughly like:

```json
{
  "domain": "property_investment",
  "intent": "financing",
  "sub_intent": "mortgage_eligibility",
  "primary_vendor": "claude-sonnet-bedrock",
  "fallback_chain": ["claude-haiku-bedrock", "escalation"],
  "policy_flags": ["mas_regulated", "sg_residency_required"],
  "confidence_threshold": 0.65,
  "exemplars_count": 87,
  "last_reviewed": "2026-..."
}
```

Final schema lives in `infra/terraform/dynamodb.tf` once committed.

---

## Process for finalising

1. Draft the full hierarchy in this document, top to bottom, with one-line descriptions per leaf.
2. Validate against a sample of ~200 real or synthetic messages: every message should classify cleanly into exactly one leaf, or fall through to `out_of_scope`/`ambiguous`.
3. Generate seed exemplars per leaf (target: 50+) for fast-path embedding training.
4. Write the seed JSON to `infra/terraform/data/intent_taxonomy.json`.
5. Update the placeholder labels in `docs/architecture.md` and the diagrams.
6. Commit all of the above in a single PR titled `feat(taxonomy): finalise intent hierarchy`.

---

## Until then

Anyone writing classifier code, routing rules, or test fixtures should:

- Use the four placeholder domains above (`general_qa`, `code_assistance`, `simple_transactional`, `out_of_scope` / `ambiguous`).
- Treat the placeholder names as **interface contract**, not final values — anything that hard-codes them outside `tests/fixtures/` needs a `# TODO(taxonomy):` comment.
- Not invent new domains in passing. If a test case doesn't fit the placeholders, that's a signal worth raising in the PR description, not papering over with a new label.
