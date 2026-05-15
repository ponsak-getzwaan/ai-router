import { useSearchParams } from "react-router-dom";
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  Legend,
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  LabelList,
} from "recharts";
import { useBouncerMetrics, type TimeWindow } from "../api/metrics";
import { KpiCard } from "../components/KpiCard";
import { TimeWindowSelector } from "../components/TimeWindowSelector";
import { ErrorBanner } from "../components/ErrorBanner";
import { Spinner } from "../components/Spinner";
import { Skeleton } from "../components/ui/skeleton";
import type { BouncerMetrics } from "../schemas/metrics";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmt(n: number | null | undefined, decimals = 1): string | null {
  if (n == null) return null;
  return n.toFixed(decimals);
}

function fmtPct(n: number | null | undefined): string | null {
  if (n == null) return null;
  return `${n.toFixed(1)}%`;
}

// ---------------------------------------------------------------------------
// Outcome donut chart
// ---------------------------------------------------------------------------

const OUTCOME_COLOURS: Record<string, string> = {
  Passed: "#22c55e",
  Rejected: "#ef4444",
  Escalated: "#f59e0b",
  "Timed out": "#6366f1",
  Errors: "#94a3b8",
};

function OutcomeChart({ m, loading }: { m: BouncerMetrics | undefined; loading: boolean }) {
  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner />
      </div>
    );
  }

  if (!m || m.total === 0) {
    return (
      <div className="flex h-64 items-center justify-center rounded-lg border border-dashed">
        <p className="text-sm text-muted-foreground">
          No bouncer data for this window.
        </p>
      </div>
    );
  }

  const data = [
    { name: "Passed", value: m.passed },
    { name: "Rejected", value: m.rejected },
    { name: "Escalated", value: m.escalated },
    { name: "Timed out", value: m.timed_out },
    { name: "Errors", value: m.errors },
  ].filter((d) => d.value > 0);

  return (
    <ResponsiveContainer width="100%" height={260}>
      <PieChart>
        <Pie
          data={data}
          cx="50%"
          cy="50%"
          innerRadius={60}
          outerRadius={100}
          paddingAngle={2}
          dataKey="value"
          aria-label="Bouncer outcome breakdown"
        >
          {data.map((entry) => (
            <Cell
              key={entry.name}
              fill={OUTCOME_COLOURS[entry.name] ?? "#94a3b8"}
            />
          ))}
        </Pie>
        <Tooltip
          formatter={(value: number, name: string) => [
            `${value.toFixed(0)} (${m.total > 0 ? ((value / m.total) * 100).toFixed(1) : 0}%)`,
            name,
          ]}
        />
        <Legend />
      </PieChart>
    </ResponsiveContainer>
  );
}

// ---------------------------------------------------------------------------
// Count bar chart
// ---------------------------------------------------------------------------

function CountBarChart({ m, loading }: { m: BouncerMetrics | undefined; loading: boolean }) {
  if (loading) {
    return (
      <div className="flex h-48 items-center justify-center">
        <Spinner />
      </div>
    );
  }

  if (!m || m.total === 0) {
    return (
      <div className="flex h-48 items-center justify-center rounded-lg border border-dashed">
        <p className="text-sm text-muted-foreground">No data</p>
      </div>
    );
  }

  const data = [
    { name: "Passed", count: m.passed, fill: OUTCOME_COLOURS["Passed"] },
    { name: "Rejected", count: m.rejected, fill: OUTCOME_COLOURS["Rejected"] },
    { name: "Escalated", count: m.escalated, fill: OUTCOME_COLOURS["Escalated"] },
    { name: "Timed out", count: m.timed_out, fill: OUTCOME_COLOURS["Timed out"] },
    { name: "Errors", count: m.errors, fill: OUTCOME_COLOURS["Errors"] },
  ];

  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} layout="vertical" margin={{ left: 16, right: 32 }}>
        <CartesianGrid strokeDasharray="3 3" horizontal={false} />
        <XAxis type="number" tick={{ fontSize: 12 }} />
        <YAxis type="category" dataKey="name" tick={{ fontSize: 12 }} width={70} />
        <Tooltip formatter={(v: number) => v.toFixed(0)} />
        <Bar dataKey="count" radius={[0, 4, 4, 0]}>
          {data.map((d) => (
            <Cell key={d.name} fill={d.fill} />
          ))}
          <LabelList dataKey="count" position="right" style={{ fontSize: 11 }} formatter={(v: number) => v.toFixed(0)} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// ---------------------------------------------------------------------------
// Confidence panel
// ---------------------------------------------------------------------------

function ConfidencePanel({ m, loading }: { m: BouncerMetrics | undefined; loading: boolean }) {
  const conf = m?.avg_confidence;
  const pct = conf != null ? conf * 100 : null;

  const barColour =
    pct == null
      ? "bg-muted"
      : pct >= 80
        ? "bg-green-500"
        : pct >= 60
          ? "bg-yellow-500"
          : "bg-red-500";

  return (
    <div className="rounded-lg border bg-card p-4">
      <h3 className="mb-3 text-sm font-medium">Avg confidence score</h3>
      {loading ? (
        <div className="space-y-2">
          <Skeleton className="h-8 w-24" />
          <Skeleton className="h-3 w-full rounded-full" />
        </div>
      ) : pct == null ? (
        <p className="text-2xl font-bold text-muted-foreground">—</p>
      ) : (
        <div className="space-y-2">
          <p className="text-3xl font-bold tabular-nums">{pct.toFixed(1)}%</p>
          {/* Gauge bar */}
          <div
            className="h-3 w-full overflow-hidden rounded-full bg-muted"
            role="progressbar"
            aria-valuenow={pct}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Average confidence"
          >
            <div
              className={`h-full rounded-full transition-all ${barColour}`}
              style={{ width: `${pct}%` }}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            {pct >= 80
              ? "High confidence — bouncer is decisive."
              : pct >= 60
                ? "Moderate confidence — review escalation threshold."
                : "Low confidence — consider retraining or tuning."}
          </p>
        </div>
      )}
      <p className="mt-4 text-xs text-muted-foreground">
        Confidence histogram requires per-request metrics endpoint (future).
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Top rejected patterns placeholder
// ---------------------------------------------------------------------------

function BlockedPatternsPanel() {
  return (
    <div className="rounded-lg border border-dashed bg-card p-4">
      <h3 className="mb-2 text-sm font-medium text-muted-foreground">
        Top blocked patterns
      </h3>
      <p className="text-xs text-muted-foreground">
        Requires a per-pattern breakdown endpoint in{" "}
        <code className="rounded bg-muted px-1">/admin/metrics/bouncer</code>.
        Not yet implemented in the backend.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main view
// ---------------------------------------------------------------------------

export function Bouncer() {
  const [params] = useSearchParams();
  const window = (params.get("window") ?? "1h") as TimeWindow;

  const { data: m, isLoading, isError, error, refetch } = useBouncerMetrics(window);

  const loading = isLoading && !m;

  // Reject rate is 100 - pass_rate (minus escalated/timeout/errors)
  const rejectRatePct =
    m && m.total > 0 ? ((m.rejected / m.total) * 100).toFixed(1) : null;
  const escalateRatePct =
    m && m.total > 0 ? ((m.escalated / m.total) * 100).toFixed(1) : null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Bouncer</h1>
          <p className="text-sm text-muted-foreground">
            Rule gate + Haiku micro-classifier outcomes
          </p>
        </div>
        <TimeWindowSelector />
      </div>

      {isError && (
        <ErrorBanner
          message={
            error instanceof Error
              ? error.message
              : "Couldn't load bouncer metrics."
          }
          onRetry={() => void refetch()}
        />
      )}

      {/* KPI row */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        <KpiCard
          title="Total requests"
          value={m ? m.total.toFixed(0) : null}
          loading={loading}
        />
        <KpiCard
          title="Pass rate"
          value={m ? fmtPct(m.pass_rate_pct) : null}
          loading={loading}
        />
        <KpiCard
          title="Rejected"
          value={rejectRatePct != null ? `${rejectRatePct}%` : null}
          alert={
            rejectRatePct != null && parseFloat(rejectRatePct) > 20
          }
          alertIcon="▲"
          loading={loading}
        />
        <KpiCard
          title="Escalated"
          value={escalateRatePct != null ? `${escalateRatePct}%` : null}
          loading={loading}
        />
        <KpiCard
          title="Timed out"
          value={m ? fmt(m.timed_out, 0) : null}
          alert={m != null && m.timed_out > 0}
          alertIcon="⚠"
          loading={loading}
        />
        <KpiCard
          title="Avg confidence"
          value={
            m?.avg_confidence != null
              ? `${(m.avg_confidence * 100).toFixed(1)}%`
              : null
          }
          loading={loading}
        />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-3 gap-4">
        {/* Outcome donut — 2/3 width */}
        <div className="col-span-2 rounded-lg border bg-card p-4">
          <h3 className="mb-2 text-sm font-medium">Outcome breakdown</h3>
          <p className="mb-4 text-xs text-muted-foreground">
            Distribution of bouncer decisions over the selected window
          </p>
          <OutcomeChart m={m} loading={loading} />
        </div>

        {/* Confidence panel — 1/3 width */}
        <ConfidencePanel m={m} loading={loading} />
      </div>

      {/* Count bar chart + blocked patterns */}
      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-2 rounded-lg border bg-card p-4">
          <h3 className="mb-4 text-sm font-medium">Outcome counts</h3>
          <CountBarChart m={m} loading={loading} />
        </div>
        <BlockedPatternsPanel />
      </div>
    </div>
  );
}
