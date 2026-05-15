# Admin Dashboard

> **Status**: 🟡 **Draft template — review the locked decisions, fill in the five stub views, and customise the auth flow.** Until this is finalised, the admin dashboard SPA is unwriteable in any non-stub sense. The FastAPI backend (already specified in `docs/architecture.md` §"Admin Dashboard") is unaffected — it's already buildable.

This document is the source of truth for the **frontend** of the admin dashboard. The backend spec lives in `docs/architecture.md` and is unchanged. Where this doc and the architecture doc disagree on a frontend concern, this doc wins; where they disagree on a backend concern, architecture.md wins.

See also: `docs/architecture.md` §"Admin Dashboard" (backend, API endpoints, IAM), `docs/adr/0003-cognito-jwt-at-edge.md` (Cognito User Pool design), `CLAUDE.md` §7 "Admin dashboard" (operational gotchas).

---

## Part 1 — Locked decisions

These were open in the architecture; they're closed here. Change them in a PR that updates this section, never silently.

| Decision | Choice | Notes |
|---|---|---|
| Framework | **Vite + React 18** | No Next.js / Remix; no SSR. The dashboard is internal, IP-allowlisted, and behind auth — SEO and initial-load shaving aren't requirements. |
| Language | **TypeScript, strict** | `tsconfig.json` extends `@tsconfig/strictest`. |
| Routing | **React Router v6** | `createBrowserRouter` with a CloudFront SPA fallback. |
| Server state | **TanStack Query v5** | All `/admin/*` API calls go through `useQuery` / `useMutation`. No direct `fetch` in components. |
| Client state | **Zustand** | Only for genuinely cross-component UI state (theme, sidebar open, current correlation_id under inspection). Most state stays in URL params or TanStack Query cache. |
| Components | **shadcn/ui** (copy-in, not npm) | Provides the primitive components (Button, Card, Table, Dialog, etc.). Tailwind underneath. |
| Charts | **Recharts** | Already pinned in `pyproject.toml` for artefact builds; same library client-side. |
| Forms | **react-hook-form + zod** | zod schemas mirror the FastAPI Pydantic models. |
| Date / time | **date-fns** (not Moment, not dayjs) | Tree-shakeable, UTC-safe. All timestamps render in `Asia/Singapore` by default with UTC tooltip. |
| Testing | **Vitest + Testing Library + MSW** | MSW (Mock Service Worker) intercepts `/admin/*` calls in tests. |
| Build output | **Static SPA → S3 → CloudFront** | See Part 5. |

> **TO DECIDE** (optional, not blocking PR 1): error tracking. Sentry, OpenTelemetry, or pipe to CloudWatch RUM? Suggested: nothing in v1, add when first production incident demands it.

---

## Part 2 — Authentication flow

The architecture says "same Cognito User Pool as the main pipeline." That tells the backend what to validate; it doesn't tell the frontend how to acquire a token. **This is the security-sensitive decision; read it carefully.**

### The chosen flow: Cognito Hosted UI redirect, in-memory token only

```
1. User visits https://admin.example.com/  (CloudFront)
2. SPA loads, checks: do I have a valid access token in memory?
   NO → redirect to Cognito Hosted UI:
        https://<pool-domain>.auth.ap-southeast-1.amazoncognito.com/login
        ?client_id=...&response_type=code&redirect_uri=https://admin.example.com/auth/callback
        &scope=openid+email+aws.cognito.signin.user.admin&code_challenge=...&code_challenge_method=S256
3. User authenticates against the User Pool (username + password, MFA if enabled).
4. Cognito redirects to https://admin.example.com/auth/callback?code=...&state=...
5. SPA exchanges code for tokens via POST /oauth2/token (PKCE verifier).
6. SPA receives: access_token, id_token, refresh_token.
7. SPA stores:
     - access_token  → IN MEMORY ONLY (React state via Zustand)
     - id_token      → IN MEMORY ONLY (used for displaying admin email)
     - refresh_token → IN MEMORY ONLY (used to silently refresh access_token)
   None of these touch localStorage, sessionStorage, or cookies.
8. All API calls attach Authorization: Bearer <access_token>.
9. On 401, attempt silent refresh; if refresh fails, redirect to step 2.
```

### Why in-memory only

Storing tokens in `localStorage` or `sessionStorage` exposes them to any XSS vulnerability in the SPA. Storing them in non-HttpOnly cookies has the same problem. Storing them in HttpOnly cookies would solve XSS but requires the backend to participate in cookie issuance, which complicates the API-first design.

In-memory storage means **page refresh logs the admin out**. That's the deliberate trade. For an internal, IP-allowlisted admin tool used by a handful of operators, re-authentication on refresh is acceptable. The same operators would not tolerate this on a consumer product; for this product they will.

> **TO DECIDE** (operational, not architectural): how long should the admin session be before forced re-authentication? Cognito access tokens default to 60 minutes — keep this. Refresh tokens default to 30 days — recommend tightening to 8 hours for the admin pool specifically. This is a User Pool app client config, set in Terraform.

### MFA

> **TO DECIDE**: required or optional for admin users? Strong recommendation: **required, TOTP-based**. The admin dashboard has write surfaces (routing rules, escalation actions) that can affect production routing. Username-and-password is not enough. Configure in the User Pool's "MFA and verifications" section.

### Logout

Logout clears in-memory state and redirects to `https://<pool-domain>.auth.ap-southeast-1.amazoncognito.com/logout?client_id=...&logout_uri=https://admin.example.com/`. Cognito invalidates the session and redirects back to the SPA, which restarts the login flow.

---

## Part 3 — Per-page wireframes

The architecture enumerates seven views. Below: two **fully worked out** as templates (Pipeline Health, Escalation Queue), and five **stubs** to fill in. The two worked-out examples between them exercise every UI pattern the other five need.

### Convention for each view

```
Route:           /admin/<path>
Page title:      <browser tab + breadcrumb>
Layout:          <high-level grid description>
Data sources:    <FastAPI endpoints called, with refresh cadence>
Components:      <list of components, top to bottom>
Empty state:     <what shows when there's no data>
Loading state:   <what shows while initial fetch is pending>
Error state:     <what shows on fetch failure>
Write actions:   <user-initiated mutations, if any>
URL params:      <searchParams the view respects>
Permissions:     <which admin roles see this page>
```

If your view doesn't have a write action, write "(none)". Don't leave the field out — explicit blanks prevent the next person from forgetting to ask.

---

### View 1 (worked example) — Pipeline Health

```
Route:           /admin/health
Page title:      "Pipeline Health — AI Router Admin"
Layout:          Top: 4-column KPI card row.
                 Middle: 2/3 width line chart (left), 1/3 width status sidebar (right).
                 Bottom: full-width stacked bar chart.
Data sources:    GET /admin/metrics/pipeline?window=<1h|24h|7d>
                 Polled via TanStack Query every 30s (refetchInterval).
                 GET /admin/health (the service-health endpoint, not the metric)
                 Polled every 10s.
Components:
  - <KpiCard> × 4:
      "Requests / minute"        — current value + sparkline of last hour
      "p99 latency"              — current value in ms, red if >2000
      "Error rate"               — percentage, red if >2%
      "Escalation rate"          — percentage, no colour threshold (informational)
  - <TimeWindowSelector>         — pill buttons: 1h | 24h | 7d. Updates URL ?window=...
  - <LineChart> (Recharts):
      x-axis = time, y-axis = requests/minute
      Two series: total requests, escalated requests
      Tooltip shows exact count + p50/p99 latency at that bucket
  - <LayerStatusSidebar>:
      One row per layer: Bouncer, Classifier, Strategist, Adapter, Orchestrator
      Each row: green/yellow/red dot + layer name + (on hover) last health-check timestamp
  - <StackedBarChart> (Recharts):
      x-axis = time buckets, y-axis = milliseconds
      Stacked: bouncer_ms, classifier_ms, strategist_ms, adapter_ms
      Click on a bar segment → opens drill-down dialog for that layer + time

Empty state:     "No data for this window. Try a longer window or check that the
                 metrics pipeline is running."
                 Single line, centred where the chart would be. KPI cards show "—".

Loading state:   KPI cards: skeleton bars (shadcn/ui Skeleton component).
                 Charts: <Spinner/> centred in the chart area.
                 Sidebar: skeleton rows.
                 Page is interactive (time window selector works) during loading
                 — TanStack Query keeps stale data visible.

Error state:     Inline error banner at top of page:
                 "Couldn't load pipeline metrics. [Retry] [Report incident]"
                 Existing data (if any) remains visible underneath, dimmed.
                 "Report incident" opens mailto: with correlation_id pre-filled.

Write actions:   (none)

URL params:      ?window=1h | 24h | 7d  (default: 1h)

Permissions:     Any authenticated admin.
```

### View 2 (worked example) — Escalation Queue

```
Route:           /admin/escalations
Page title:      "Escalation Queue — AI Router Admin"
Layout:          Left: filter sidebar (250px).
                 Right: main content — table of pending escalations.
                 Top-right of main content: bulk-action toolbar (appears when ≥1
                   row selected).
Data sources:    GET /admin/escalations?status=pending&page=<n>&filter=<json>
                 Polled every 30s when tab is focused, paused when backgrounded.
                 GET /admin/escalations/{id} (lazy — only when row expanded).

Components:
  - <FilterSidebar>:
      - Date range (last 24h default)
      - Layer of origin (bouncer | classifier | strategist | any)
      - Reason (multi-select, populated from API)
      - Min confidence / max confidence sliders
      All filters update URL searchParams.
  - <DataTable> (built from shadcn/ui Table):
      Columns: select (checkbox), correlation_id (truncated, clickable),
               timestamp (relative + absolute on hover), layer, reason,
               confidence, redacted_preview (first 80 chars), actions
      Rows expandable: clicking the row reveals the full redacted message,
      the BounceResult / ClassifiedIntent / RoutingPlan that triggered it
      (whichever applies), and any annotations from previous reviewers.
  - <Pagination>: page size 25, URL-driven.
  - <BulkActionToolbar> (sticky, top-right when selections exist):
      [Approve N] [Reject N] [Requeue N] [Clear selection]

Empty state:     "No pending escalations match your filters. Nice."
                 Plus a small "view all (including resolved)" link.

Loading state:   <DataTable> shows 5 skeleton rows.
                 Filter sidebar interactive immediately (filters apply on submit).
                 If polling fails silently, leave existing data; surface failure
                 only if user clicks refresh.

Error state:     Banner above the table. Same shape as Pipeline Health.

Write actions:
  - Approve: POST /admin/escalations/{id}/approve
      Confirmation dialog: "Approve this escalation? It will be released to the
        routing layer with the original intent classification."
      Optimistic update: row leaves the pending table immediately. Reverts on error.
  - Reject: POST /admin/escalations/{id}/reject
      Confirmation dialog: "Reject this escalation? It will move to the dead-letter
        queue and the user will not get a response."
      REQUIRES a free-text reason (textarea, min 10 chars). Reason is logged.
      Same optimistic update + revert.
  - Requeue with annotation: POST /admin/escalations/{id}/requeue
      Confirmation dialog with textarea for the annotation (optional).
      Item returns to the queue with the annotation visible to the next reviewer.

URL params:      ?status=pending|resolved|all (default: pending)
                 ?layer=...
                 ?reason=...
                 ?conf_min=0.0&conf_max=1.0
                 ?from=<ISO>&to=<ISO>
                 ?page=<n>

Permissions:     Requires `admin:escalations:read` for view, `admin:escalations:write` for actions.
                 If the user has only :read, action buttons render as disabled with
                 tooltip "You don't have permission to take this action."
```

### The remaining five views (fill in below)

> **TODO**: Use the two worked examples above as the template. Each stub below has the section headers; fill in the contents.

#### View 3 — Bouncer metrics

```
Route:           /admin/bouncer
Page title:      "Bouncer — AI Router Admin"
Layout:          <TODO>
Data sources:    GET /admin/metrics/bouncer
                 <TODO: refresh cadence>
Components:
  - <TODO> stats expected: pass/fail/escalate rates, confidence histogram, top blocked patterns.
  - <TODO>
Empty state:     <TODO>
Loading state:   <TODO>
Error state:     <TODO>
Write actions:   (none)
URL params:      <TODO>
Permissions:     <TODO>
```

#### View 4 — Classifier metrics

```
Route:           /admin/classifier
Page title:      "Classifier — AI Router Admin"
Layout:          <TODO>
Data sources:    GET /admin/metrics/classifier
Components:
  - <TODO> stats expected: intent distribution, fast vs deep path split, confidence distribution.
  - <TODO>
<all other fields TODO>
```

#### View 5 — Strategist metrics

```
Route:           /admin/strategist
Page title:      "Strategist — AI Router Admin"
Layout:          <TODO>
Data sources:    GET /admin/metrics/strategist (not yet specified in architecture.md — define endpoint here)
Components:
  - <TODO> stats expected: vendor selection breakdown, policy engine trigger counts.
  - <TODO>
<all other fields TODO>
```

#### View 6 — Routing rules editor

```
Route:           /admin/routing-rules and /admin/routing-rules/:intentKey
Page title:      "Routing Rules — AI Router Admin"
Layout:          List view + detail/edit view (route-driven, not modal).
Data sources:    GET/PUT /admin/routing-rules/{intent}
Components:
  - <DataTable> of all rules, columns: intent_key, primary_vendor, policy_flags,
    last_modified_by, last_modified_at
  - <RuleEditor> on detail route: form mirroring the routing rule schema from
    docs/routing-rules.md. JSON-shaped — use react-hook-form + zod schema generated
    from the FastAPI Pydantic model.
Write actions:
  - Update: PUT with optimistic-locking ETag. Confirmation dialog REQUIRED — show
    a diff of the old and new rule, name two operators required to approve
    (per docs/routing-rules.md §"Editing rules in production").
<all other fields TODO>

Permissions:     Requires `admin:routing-rules:write`. Read is broader.
                 IMPORTANT: this is the highest-stakes write surface. The two-operator
                 sign-off described in docs/routing-rules.md MUST be enforced
                 here — the UI doesn't permit a single-operator submit. Implement
                 as: first operator drafts and submits → status "pending_review";
                 second operator opens, reviews diff, clicks "approve" → applies.
                 The "approve" button is hidden for the operator who drafted.
```

#### View 7 — Audit log

```
Route:           /admin/audit
Page title:      "Audit Log — AI Router Admin"
Layout:          <TODO> — searchable, filterable, paginated.
Data sources:    GET /admin/audit
Components:
  - Search box: correlation_id, user_sub
  - Filter: date range, intent_key, vendor, policy applied
  - <DataTable>: timestamp, correlation_id, user_sub, intent, vendor, policies_applied, latency
  - Row click: full audit record drawer (right-side panel)
<all other fields TODO>

Permissions:     `admin:audit:read`. No write — audit log is append-only.
                 NEVER renders raw message text or restored entity values.
                 Only entity types and counts, per CLAUDE.md §7 "Admin dashboard"
                 and the non-negotiables.
```

#### View 8 — Test console

```
Route:           /admin/test-console
Page title:      "Test Console — AI Router Admin"
Layout:          Two-pane. Left: input form. Right: trace view.
Data sources:    POST /admin/test-console (initiates a trace)
                 SSE /admin/test-console/stream/{trace_id} (per-layer progress)
Components:
  - Input pane:
      - Textarea for message
      - Selector: dry-run (stop before vendor) | full trace (include vendor response)
      - Tier override (free / paid)
      - Submit button
  - Trace pane:
      - Vertical timeline of layers. Each layer card shows: layer name, latency,
        the input it received (redacted), the output it produced, expand for details.
      - Final response at the bottom (if full trace).
      - Per-layer latency bar across the top, summing to the total.
<all other fields TODO>

Permissions:     `admin:test-console`. Test console traces are logged (per CLAUDE.md
                 §7) with redacted messages only. The console is NOT a debugging
                 escape hatch for raw input.
```

---

## Part 4 — Cross-cutting UI requirements

These apply to every view. Don't duplicate them per view; reference them.

### Empty / loading / error states

Every view that fetches data has these three states. Use the patterns from View 1 and View 2 as templates. Specifically:

- **Empty**: human-language explanation, never just `[]` or a blank canvas. Suggest the next action (try a wider filter, check the upstream service).
- **Loading**: skeleton screens preferred over spinners for known-shape content (tables, KPI cards). Spinners are acceptable for unknown-size content (charts).
- **Error**: inline banner at the top of the page. Three actions, in this order: Retry, See details (expandable), Report incident (mailto with correlation_id).

The "Report incident" pre-fills the email with: timestamp, view URL, correlation_id of the last successful request (if any), browser user-agent, and the error message. **Never** pre-fills the email with API response bodies (might contain operational data).

### Timestamps

All timestamps render in `Asia/Singapore`. Tooltip on hover shows ISO 8601 UTC. Relative times ("2 minutes ago") for events within 24 hours; absolute for older. Use `date-fns/formatRelative` and `date-fns/formatISO`.

### Confirmation dialogs

Every destructive action (anything that's not idempotent and read-only) requires confirmation. Patterns:

- **Low stakes** (requeue an escalation): one-line confirmation dialog, primary button = action verb, secondary = Cancel.
- **Medium stakes** (approve an escalation): confirmation dialog describes the downstream effect ("this will release to the routing layer").
- **High stakes** (edit routing rules): two-operator flow (see View 6), diff displayed, second operator must explicitly approve.

### Keyboard shortcuts

> **TO DECIDE**: should the dashboard support keyboard shortcuts (`/` to focus search, `j`/`k` to navigate rows, etc.)? Recommendation: yes, but as a follow-up PR after the main views ship. Don't block v1 on it.

### Accessibility

WCAG 2.1 AA target. shadcn/ui primitives are accessible by default; the obligation falls to view-level code:

- Every chart has an accessible label and a data-table fallback.
- Every form field has a `<label>`, not just a placeholder.
- Colour is never the only signal — red latency cards also have an icon, not just a colour change.
- Focus management on dialogs, drawers, route changes.

### Dark mode

Out of scope for v1. Use the shadcn/ui CSS variables so adding dark mode later is mechanical.

---

## Part 5 — Deployment

### Build artefact

```
admin-ui/
  package.json
  vite.config.ts          # base path /admin/
  src/
    main.tsx
    App.tsx
    routes/
    components/
    api/                  # TanStack Query hooks, one file per backend resource
    auth/                 # Cognito client, token storage
    schemas/              # zod schemas mirroring backend Pydantic
    test/                 # Vitest + MSW
  dist/                   # build output (gitignored)
```

Build: `cd admin-ui && pnpm install && pnpm build`. Output is in `dist/`.

### Hosting

- **S3 bucket**: `airouter-admin-spa-<account-id>`. Private. Public access blocked.
- **CloudFront distribution**: origin is the S3 bucket via OAC (Origin Access Control, not OAI — OAI is deprecated). Behaviours:
  - Default behaviour: forward to S3.
  - **SPA fallback**: configure CloudFront Functions to rewrite 403/404 from S3 to `/index.html` (otherwise `/admin/routing-rules` returns 404 because there's no `routing-rules.html` in S3).
  - Cache policy: `CachingOptimized` for the `assets/` path (JS/CSS with content-hashed filenames). `CachingDisabled` for `index.html` (so deploys are immediate).
- **Domain**: `admin.<your-domain>`. ACM cert for the domain, attached to CloudFront. Route 53 alias record.
- **IP allowlist**: WAF web ACL attached to CloudFront, IP set restricted to operator IPs / VPN ranges. This is the IP allowlist mentioned in `docs/architecture.md` §"Admin Dashboard".

### CI/CD for the SPA

`.github/workflows/admin-ui-deploy.yml`:

1. On merge to `main`: build, run Vitest, run Playwright smoke tests against a deployed preview.
2. On manual approval (production environment): `aws s3 sync dist/ s3://...` then `aws cloudfront create-invalidation --paths "/index.html"`.

Do NOT auto-deploy to production on merge. Routing rule changes via the admin UI affect production behaviour; the SPA itself shouldn't deploy without human approval.

### Local development

```bash
cd admin-ui
pnpm dev
# Vite dev server on http://localhost:5173
# API calls proxied to http://localhost:8000 (the FastAPI admin backend running locally)
# Auth: use a local Cognito mock or a dev User Pool — see admin-ui/src/auth/README.md
```

> **TO DECIDE**: dev User Pool, mock auth, or both? Recommend a dedicated `airouter-admin-dev` Cognito pool in the sandbox account, populated with test users. Avoids divergence between dev and prod auth code paths.

---

## Part 6 — Testing strategy

Three layers:

### 1. Unit tests (Vitest)

Per component. Test rendering states (empty, loading, error, populated) with mocked TanStack Query data. Test interactions (clicking a row expands it, clicking approve opens the dialog). Use Testing Library's `screen.getByRole` etc., not test IDs.

### 2. Integration tests (Vitest + MSW)

Per view. Spin up the view with MSW intercepting `/admin/*` calls. Test full user flows: load page, apply filter, select rows, click bulk action, confirm dialog, see optimistic update, see toast on success. MSW handlers live in `admin-ui/src/test/handlers.ts` and mirror the FastAPI endpoint contracts.

### 3. End-to-end smoke tests (Playwright)

Run against a deployed preview. Three scenarios at minimum:
- Login via Cognito Hosted UI redirect (using a dedicated test user with a static password — store in GitHub Actions secrets, not in code).
- Navigate to Pipeline Health, verify a KPI card renders a number.
- Navigate to Escalation Queue, verify the table renders with seed data.

E2E is the smallest tier intentionally — most assurance comes from layers 1 and 2.

> **TO DECIDE**: do you need visual regression testing (Percy, Chromatic)? Recommend: no for v1. The dashboard is internal and operators tolerate minor visual drift. Add when (if) the UI starts being used by less-tolerant audiences.

---

## Part 7 — What this template deliberately leaves open

Some decisions are easier to make once the dashboard is in operators' hands. Document them as known unknowns rather than guessing now:

- **Notification system**: should the dashboard surface push-notifications when an escalation arrives, or rely on polling? Decide after first month of operator feedback.
- **Saved filters / saved views**: nice-to-have for the Escalation Queue and Audit Log. Out of scope for v1.
- **Multi-tenant**: if the router ever serves more than one downstream product, the dashboard needs a tenant selector. Punt until that's a real requirement.
- **Mobile**: not supported. Operators use desktop. The Tailwind breakpoints fall back gracefully but no mobile-specific UX work is being done.
- **Internationalisation**: English only. Singapore admins read English; no business case for localisation.

---

## Part 8 — Process for finalising

1. Review Part 1 (locked decisions). Change anything that doesn't fit your team's preferences. Easy now, painful in three weeks.
2. Decide the auth-flow MFA requirement (Part 2). Costs 30 minutes to enable in Cognito; costs hours to retrofit if added later.
3. Fill in the five stub views in Part 3, using View 1 and View 2 as templates. Aim for a paragraph per field, not a page.
4. Decide the dev auth strategy (Part 5). Affects the first admin-UI PR.
5. Commit this document. Open `feat/admin-ui-scaffold` as the first PR — Vite scaffold, auth flow, one rendered view (Pipeline Health). The other six views are follow-up PRs, one or two per PR.

Once Part 3 is filled in, the admin SPA is buildable by Claude Code one view at a time, the same way the backend layers are.
