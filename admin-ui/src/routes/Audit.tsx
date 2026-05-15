import { useState, useMemo } from "react";
import { format } from "date-fns";
import { toZonedTime } from "date-fns-tz";
import { useAuditLog, encodeCursor } from "../api/audit";
import { ErrorBanner } from "../components/ErrorBanner";
import { Skeleton } from "../components/ui/skeleton";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Badge } from "../components/ui/badge";
import type { AuditRecord } from "../schemas/audit";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const SGT = "Asia/Singapore";

function fmtTs(ts: string): string {
  try {
    return format(toZonedTime(new Date(ts), SGT), "yyyy-MM-dd HH:mm:ss");
  } catch {
    return ts;
  }
}

function shortCorr(id: string): string {
  return id.length > 12 ? `${id.slice(0, 8)}…` : id;
}

function shortVendor(v: string | null): string {
  if (!v) return "—";
  return v.split(".").pop()?.replace(/-v\d+:\d+$/, "") ?? v;
}

function boolBadge(val: boolean | null, trueLabel: string, falseLabel: string) {
  if (val === null) return <span className="text-muted-foreground">—</span>;
  return val ? (
    <Badge variant="success">{trueLabel}</Badge>
  ) : (
    <Badge variant="default">{falseLabel}</Badge>
  );
}

// ---------------------------------------------------------------------------
// Detail drawer
// ---------------------------------------------------------------------------

interface DrawerProps {
  record: AuditRecord;
  onClose: () => void;
}

function DetailDrawer({ record, onClose }: DrawerProps) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/30"
        onClick={onClose}
        aria-hidden
      />
      {/* Panel */}
      <div className="relative z-10 flex h-full w-full max-w-md flex-col overflow-y-auto bg-background shadow-xl">
        <div className="flex items-center justify-between border-b px-5 py-4">
          <h2 className="font-semibold">Audit detail</h2>
          <button
            onClick={onClose}
            className="rounded p-1 hover:bg-muted text-muted-foreground hover:text-foreground"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="flex-1 space-y-4 px-5 py-4 text-sm">
          {/* Identity */}
          <Section title="Identity">
            <Row label="Correlation ID">
              <code className="break-all font-mono text-xs">{record.correlation_id}</code>
            </Row>
            <Row label="Timestamp">{fmtTs(record.timestamp)} SGT</Row>
            <Row label="User sub">
              <code className="font-mono text-xs">{record.user_sub}</code>
            </Row>
            <Row label="Session">
              <code className="font-mono text-xs">{record.session_id}</code>
            </Row>
          </Section>

          {/* Redaction */}
          <Section title="Redaction">
            <Row label="Redacted">{record.was_redacted ? "Yes" : "No"}</Row>
            <Row label="Entity count">{record.entity_count}</Row>
            <Row label="Entity types">
              {record.entity_types_redacted.length > 0 ? (
                <div className="flex flex-wrap gap-1">
                  {record.entity_types_redacted.map((t) => (
                    <Badge key={t} variant="default">{t}</Badge>
                  ))}
                </div>
              ) : (
                <span className="text-muted-foreground">None</span>
              )}
            </Row>
          </Section>

          {/* Bouncer */}
          <Section title="Bouncer">
            <Row label="Allowed">{boolBadge(record.bouncer_allowed, "Yes", "Blocked")}</Row>
            <Row label="Escalated">{boolBadge(record.bouncer_escalated, "Yes", "No")}</Row>
          </Section>

          {/* Classification & routing */}
          <Section title="Classification & Routing">
            <Row label="Intent">{record.intent ?? <Dash />}</Row>
            <Row label="Confidence">{record.intent_confidence ?? <Dash />}</Row>
            <Row label="Vendor">{shortVendor(record.vendor)}</Row>
            <Row label="Routing path">{record.routing_path ?? <Dash />}</Row>
            <Row label="Policy blocked">
              {boolBadge(record.policy_blocked, "Yes", "No")}
            </Row>
          </Section>

          {/* Performance & errors */}
          <Section title="Performance">
            <Row label="Total latency">
              {record.total_latency_ms ? `${record.total_latency_ms} ms` : <Dash />}
            </Row>
            <Row label="Error type">
              {record.error_type ? (
                <Badge variant="destructive">{record.error_type}</Badge>
              ) : (
                <Dash />
              )}
            </Row>
          </Section>

          {/* Security notice */}
          <div className="rounded-md border border-muted bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
            Message content is never stored in the audit log. Only entity types and
            counts are shown, per the architecture non-negotiables.
          </div>
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </p>
      <div className="space-y-2 rounded-md border bg-card px-3 py-2">
        {children}
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-0.5">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className="text-right">{children}</span>
    </div>
  );
}

function Dash() {
  return <span className="text-muted-foreground">—</span>;
}

// ---------------------------------------------------------------------------
// Table row
// ---------------------------------------------------------------------------

function AuditRow({
  record,
  onClick,
}: {
  record: AuditRecord;
  onClick: () => void;
}) {
  return (
    <tr
      className="cursor-pointer border-b transition-colors hover:bg-muted/40"
      onClick={onClick}
    >
      <td className="px-4 py-3 text-xs text-muted-foreground">
        {fmtTs(record.timestamp)}
      </td>
      <td className="px-4 py-3 font-mono text-xs" title={record.correlation_id}>
        {shortCorr(record.correlation_id)}
      </td>
      <td className="px-4 py-3 font-mono text-xs" title={record.user_sub}>
        {record.user_sub.length > 12 ? `${record.user_sub.slice(0, 10)}…` : record.user_sub}
      </td>
      <td className="px-4 py-3 text-xs">{record.intent ?? <Dash />}</td>
      <td className="px-4 py-3 text-xs">{shortVendor(record.vendor)}</td>
      <td className="px-4 py-3">
        {record.policy_blocked === true ? (
          <Badge variant="destructive">Blocked</Badge>
        ) : record.error_type ? (
          <Badge variant="warning">{record.error_type}</Badge>
        ) : record.bouncer_allowed === false ? (
          <Badge variant="warning">Bounced</Badge>
        ) : (
          <Badge variant="success">OK</Badge>
        )}
      </td>
      <td className="px-4 py-3 text-right text-xs text-muted-foreground">
        {record.total_latency_ms ? `${record.total_latency_ms} ms` : "—"}
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Pagination state
// ---------------------------------------------------------------------------

interface Page {
  cursor?: string | undefined;
}

// ---------------------------------------------------------------------------
// Main view
// ---------------------------------------------------------------------------

export function Audit() {
  const [searchInput, setSearchInput] = useState("");
  const [correlationId, setCorrelationId] = useState<string | undefined>(undefined);
  const [pages, setPages] = useState<Page[]>([{ cursor: undefined }]);
  const [pageIdx, setPageIdx] = useState(0);
  const [selected, setSelected] = useState<AuditRecord | null>(null);

  const currentCursor = pages[pageIdx]?.cursor;

  const { data, isLoading, isError, error, refetch } = useAuditLog({
    correlationId,
    limit: 50,
    cursor: currentCursor,
  });

  const nextCursor = useMemo(
    () => encodeCursor(data?.last_evaluated_key as Record<string, unknown> | null),
    [data?.last_evaluated_key],
  );

  function handleSearch() {
    const trimmed = searchInput.trim();
    setCorrelationId(trimmed || undefined);
    setPages([{ cursor: undefined }]);
    setPageIdx(0);
  }

  function handleClear() {
    setSearchInput("");
    setCorrelationId(undefined);
    setPages([{ cursor: undefined }]);
    setPageIdx(0);
  }

  function goNext() {
    if (!nextCursor) return;
    const newPages = pages.slice(0, pageIdx + 1);
    newPages.push({ cursor: nextCursor });
    setPages(newPages);
    setPageIdx(pageIdx + 1);
  }

  function goPrev() {
    if (pageIdx === 0) return;
    setPageIdx(pageIdx - 1);
  }

  const loading = isLoading && !data;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Audit Log</h1>
        <p className="text-sm text-muted-foreground">
          Per-request records from DynamoDB. Search by correlation ID or browse
          all recent records. Message content is never stored.
        </p>
      </div>

      {/* Search bar */}
      <div className="flex items-center gap-2">
        <Input
          className="max-w-sm font-mono text-sm"
          placeholder="Search by correlation ID…"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") handleSearch(); }}
        />
        <Button size="sm" onClick={handleSearch}>
          Search
        </Button>
        {correlationId && (
          <Button size="sm" variant="ghost" onClick={handleClear}>
            Clear
          </Button>
        )}
      </div>

      {correlationId && (
        <p className="text-xs text-muted-foreground">
          Filtered by correlation ID:{" "}
          <code className="font-mono">{correlationId}</code>
        </p>
      )}

      {isError && (
        <ErrorBanner
          message={error instanceof Error ? error.message : "Couldn't load audit log."}
          onRetry={() => void refetch()}
        />
      )}

      <div className="overflow-hidden rounded-lg border bg-card">
        <table className="w-full text-sm">
          <thead className="border-b bg-muted/40">
            <tr>
              <th className="px-4 py-3 text-left font-medium text-xs">Timestamp (SGT)</th>
              <th className="px-4 py-3 text-left font-medium text-xs">Correlation ID</th>
              <th className="px-4 py-3 text-left font-medium text-xs">User</th>
              <th className="px-4 py-3 text-left font-medium text-xs">Intent</th>
              <th className="px-4 py-3 text-left font-medium text-xs">Vendor</th>
              <th className="px-4 py-3 text-left font-medium text-xs">Status</th>
              <th className="px-4 py-3 text-right font-medium text-xs">Latency</th>
            </tr>
          </thead>
          <tbody>
            {loading
              ? Array.from({ length: 8 }, (_, i) => (
                  <tr key={i} className="border-b">
                    {Array.from({ length: 7 }, (_, j) => (
                      <td key={j} className="px-4 py-3">
                        <Skeleton className="h-4 w-full" />
                      </td>
                    ))}
                  </tr>
                ))
              : (data?.records ?? []).map((rec) => (
                  <AuditRow
                    key={`${rec.correlation_id}-${rec.timestamp}`}
                    record={rec}
                    onClick={() => setSelected(rec)}
                  />
                ))}
          </tbody>
        </table>

        {!loading && (data?.records ?? []).length === 0 && (
          <div className="flex flex-col items-center justify-center gap-1 py-16 text-center">
            <p className="font-medium">No records found.</p>
            <p className="text-sm text-muted-foreground">
              {correlationId
                ? "No audit entries match this correlation ID."
                : "The audit log is empty."}
            </p>
          </div>
        )}
      </div>

      {/* Pagination */}
      {!loading && (
        <div className="flex items-center justify-between">
          <p className="text-xs text-muted-foreground">
            {data ? `${data.count} record${data.count !== 1 ? "s" : ""} on this page` : ""}
          </p>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={pageIdx === 0}
              onClick={goPrev}
            >
              ← Previous
            </Button>
            <span className="text-xs text-muted-foreground">Page {pageIdx + 1}</span>
            <Button
              size="sm"
              variant="outline"
              disabled={!nextCursor}
              onClick={goNext}
            >
              Next →
            </Button>
          </div>
        </div>
      )}

      {selected && (
        <DetailDrawer record={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
