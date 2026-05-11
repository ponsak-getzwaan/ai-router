# ADR 0003: Authentication via Cognito User Pool, JWT validated at API Gateway edge

- **Status**: Accepted
- **Date**: 2026-05-10
- **Deciders**: Project lead (Ponsak)
- **Consulted**: Architecture review (rounds 1 and 2)

---

## Context

Every request entering the router must be authenticated before any pipeline cost is incurred. The router handles potentially sensitive Singapore-context queries (property, MAS-regulated finance, tenancy) where regulatory accountability for *who asked what* is non-optional. User identity must:

- Be verified before any LLM cost is incurred.
- Be propagated through every pipeline layer in a stable, non-PII-bearing form.
- Drive rate limits, banned-user checks, session history scoping, and audit attribution.
- Survive the redaction boundary — the user identifier itself is a structured ID (a UUID), not a PII string.

The candidate authentication mechanisms were:

1. **Amazon Cognito User Pool with JWT access tokens** — managed identity service, JWTs validated at API Gateway.
2. **Federated identity via OIDC** (Auth0, Okta, Azure AD) — external IdP, tokens still JWT.
3. **API keys** — long-lived bearer tokens issued per client.
4. **Mutual TLS** — client certificates.

---

## Decision

**Amazon Cognito User Pool with JWT access tokens, validated at the API Gateway edge.**

The flow:

1. Client authenticates against the Cognito User Pool and receives an RS256-signed JWT access token (60-minute TTL) and a refresh token (30-day TTL, never sent to the API).
2. Client sends API requests with `Authorization: Bearer <access_token>`.
3. **API Gateway validates the JWT signature** against the Cognito JWKS endpoint and checks `exp`, `iss`, `aud`, and `token_use` claims. Validation runs in a dedicated Lambda authoriser.
4. Invalid tokens are rejected at the edge with HTTP 401. **No payload reaches SQS or any pipeline component.**
5. The validated `user_sub` (Cognito UUID) is injected into the API Gateway request context and flows through the pipeline as a field on `PipelineEnvelope`.

Pipeline components consume `user_sub` for:

- **Bouncer** — banned-user check against a Redis allowlist/denylist; rate-limit keys.
- **Classifier** — session history lookup (last 3 turns for pronoun resolution).
- **Strategist** — tier-based vendor selection (e.g. paid tier gets Sonnet, free tier gets Haiku).
- **Orchestrator** — audit record per request.

`user_sub` is the only identifier propagated. **Email, phone, name, and any other Cognito profile attributes are never copied into the pipeline.**

---

## Consequences

### Positive

- **Unauthenticated requests cost nothing.** API Gateway rejects them before any pipeline code runs, before SQS receives a message, before any compute spins up. The blast radius of a credential-stuffing or DoS attempt is bounded to API Gateway's rate limits and Cognito's authentication endpoint.
- **JWT validation is centralised.** Every backend service trusts that `user_sub` in the request context is authentic. No service re-validates the JWT, which means no service can accidentally validate it incorrectly.
- **No long-lived credentials in clients.** Access tokens expire in 60 minutes. Compromised access tokens have a bounded blast radius. Refresh tokens are stored client-side but never sent to the API; they're used only to mint new access tokens via Cognito.
- **`user_sub` is privacy-safe.** It's a Cognito UUID with no PII content, so it can flow through logs, audit records, and the redacted pipeline without triggering the no-PII-in-logs rule.
- **Cognito User Pool is reused for the admin dashboard** (separate ALB listener rule, IP allowlisted). Single identity surface for both end users and admins, with separate IAM roles per audience.
- **Standard, well-documented mechanism.** AWS-native, no third-party dependency, supported by every AWS SDK.

### Negative

- **Cognito feature ceiling.** Cognito User Pools have known limitations around custom auth flows, advanced password policies, and certain enterprise SSO scenarios. If we later need (say) SAML federation with multiple corporate IdPs, Cognito is workable but rougher than a dedicated IdP like Okta.
- **JWT revocation is not real-time.** Once a JWT is issued, it's valid for its full TTL (60 minutes) regardless of whether the user is later banned. The Bouncer's `user_sub` denylist provides real-time revocation at the application level — this is a defence-in-depth layer, not a replacement for short token TTLs.
- **JWKS caching nuance.** API Gateway caches the Cognito JWKS for performance. Key rotation requires care; this is standard JWT infrastructure but worth knowing.
- **Cognito region binding.** The User Pool lives in `ap-southeast-1`. Multi-region failover for authentication is out of scope (the system is single-region by design — see `CLAUDE.md` §11).

### Neutral

- The 60-minute access token TTL is a standard trade-off. Shorter TTLs reduce blast radius but increase Cognito API load from refreshes. 60 minutes is the conventional middle.

---

## Alternatives considered

### A. Federated OIDC via Auth0 / Okta / Azure AD

Considered. The aws-solutions-library guidance for Claude Code itself uses this pattern for federated developer authentication. We rejected it for the user-facing router because:

- We have no existing IdP relationship to federate with — the router is a standalone product, not part of an enterprise's directory.
- A third-party IdP introduces another vendor, another credential, another availability dependency.
- Cognito is sufficient for the user authentication needs at v1. If enterprise SSO becomes a requirement (e.g. for B2B integrations), Cognito User Pools support OIDC federation as a follow-up — that's an additive change, not a redesign.

### B. Long-lived API keys

Rejected. API keys without expiry are a perpetual credential leak risk. They lack user attribution unless paired with a user-management layer (which is what Cognito provides). They lack revocation primitives. The only context where API keys make sense is service-to-service automation, which is not the user-facing scenario.

### C. Mutual TLS

Rejected. The deployment overhead for end users (provisioning certificates per client, rotating them, distributing them) is impractical for a user-facing chat application. mTLS may be appropriate for a future B2B API if that materialises; that would be an additive listener, not a replacement for the user-facing flow.

### D. Validate JWT at the application layer (not API Gateway)

Rejected. Putting JWT validation in a Lambda authoriser at the API Gateway edge means:

- Unauthenticated requests are rejected before SQS, before any compute, before any Bedrock cost.
- Every backend service can trust the request context unconditionally; no service has to re-implement validation correctly.
- A bug in one service's JWT validation cannot create an authentication bypass for other services.

Validating at the application layer would push this responsibility into every layer that needs identity, which is a textbook authentication anti-pattern.

### E. Cognito authoriser type (built-in vs. Lambda)

We chose **Lambda authoriser** over the built-in Cognito authoriser. Reasons:

- The Lambda authoriser can implement the Bouncer's banned-user check at the same layer as JWT validation — banned users get 403 at the edge without ever reaching the pipeline.
- It can attach custom request-context fields (e.g. user tier, region) that downstream layers consume without an extra DB round-trip.
- It's stateless, JWT-only validation against the Cognito JWKS — millisecond execution. The cost is negligible.

---

## References

- `docs/architecture.md` §"Authentication — Amazon Cognito + JWT"
- `CLAUDE.md` §3 non-negotiable #2
- AWS API Gateway Lambda authorizers documentation
- Amazon Cognito User Pools documentation
