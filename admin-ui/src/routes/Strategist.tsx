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
import { useStrategistMetrics, type TimeWindow } from "../api/metrics";
import { KpiCard } from "../components/KpiCard";
import { TimeWindowSelector } from "../components/TimeWindowSelector";
import { ErrorBanner } from "../components/ErrorBanner";
import { Spinner } from "../components/Spinner";
import type { StrategistMetrics } from "../schemas/metrics";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function pct(n: number, total: number): string {
  if (total === 0) return "0%";
  return `${((n / total) * 100).toFixed(1)}%`;
}

function emptyChart(msg: string) {
  return (
    <div className="flex h-full min-h-[200px] items-center justify-center rounded-lg border border-dashed">
      <p className="text-sm text-muted-foreground">{msg}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Vendor selection donut
// ---------------------------------------------------------------------------

const VENDOR_COLOURS: Record<string, string> = {
  sonnet: "#6366f1",
  haiku: "#22c55e",
  opus: "#f59e0b",
};

const VENDOR_LABELS: Record<string, string> = {
  sonnet: "Claude Sonnet",
  haiku: "Claude Haiku",
  opus: "Claude Opus",
};

function VendorChart({
  m,
  loading,
}: {
  m: StrategistMetrics | undefined;
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner />
      </div>
    );
  }

  const entries = Object.entries(m?.vendor_counts ?? {}).filter(([, v]) => v > 0);

  if (!m || entries.length === 0) {
    return emptyChart(
      m?.total === 0
        ? "No routing decisions in this window."
        : "No vendor breakdown yet — strategist layer not yet emitting metrics."
    );
  }

  const total = entries.reduce((s, [, v]) => s + v, 0);
  const data = entries
    .sort(([, a], [, b]) => b - a)
    .map(([vendor, count]) => ({
      name: VENDOR_LABELS[vendor] ?? vendor,
      vendor,
      value: count,
      pct: total > 0 ? ((count / total) * 100).toFixed(1) : "0",
    }));

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
          aria-label="Vendor selection breakdown"
        >
          {data.map((entry) => (
            <Cell
              key={entry.vendor}
              fill={VENDOR_COLOURS[entry.vendor] ?? "#94a3b8"}
            />
          ))}
        </Pie>
        <Tooltip
          formatter={(value: number, name: string, props: { payload?: { pct: string } }) => [
            `${value.toFixed(0)} (${props.payload?.pct ?? ""}%)`,
            name,
          ]}
        />
        <Legend />
      </PieChart>
    </ResponsiveContainer>
  );
}

// ---------------------------------------------------------------------------
// Routing path split bar
// ---------------------------------------------------------------------------

function PathChart({
  m,
  loading,
}: {
  m: StrategistMetrics | undefined;
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="flex h-48 items-center justify-center">
        <Spinner />
      </div>
    );
  }

  if (!m || (m.deterministic_route === 0 && m.arbitration_route === 0)) {
    return emptyChart("No path data yet.");
  }

  const data = [
    {
      name: "Deterministic",
      count: m.deterministic_route,
      fill: "#22c55e",
      description: "conf ≥ 0.85 → direct rule lookup",
    },
    {
      name: "Arbitration",
      count: m.arbitration_route,
      fill: "#6366f1",
      description: "Haiku arbitration used",
    },
  ];

  return (
    <ResponsiveContainer width="100%" height={160}>
      <BarChart data={data} layout="vertical" margin={{ left: 8, right: 48 }}>
        <CartesianGrid strokeDasharray="3 3" horizontal={false} />
        <XAxis type="number" tick={{ fontSize: 12 }} />
        <YAxis type="category" dataKey="name" tick={{ fontSize: 12 }} width={90} />
        <Tooltip
          formatter={(value: number, _: string, props: { payload?: { description: string } }) => [
            `${value.toFixed(0)} — ${props.payload?.description ?? ""}`,
            "Requests",
          ]}
        />
        <Bar dataKey="count" radius={[0, 4, 4, 0]}>
          {data.map((d) => (
            <Cell key={d.name} fill={d.fill} />
          ))}
          <LabelList
            dataKey="count"
            position="right"
            style={{ fontSize: 11 }}
            formatter={(v: number) => v.toFixed(0)}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// ---------------------------------------------------------------------------
// Policy engine panel
// ---------------------------------------------------------------------------

function PolicyPanel({
  m,
  loading,
}: {
  m: StrategistMetrics | undefined;
  loading: boolean;
}) {
  const blockRate =
    m && m.total > 0 ? ((m.policy_blocked / m.total) * 100).toFixed(1) : null;
  const fallbackRate =
    m && m.total > 0 ? ((m.fallback_used / m.total) * 100).toFixed(1) : null;

  return (
    <div className="rounded-lg border bg-card p-4">
      <h3 className="mb-3 text-sm font-medium">Policy engine</h3>
      {loading ? (
        <div className="space-y-3">
          {[1, 2].map((i) => (
            <div key={i} className="space-y-1">
              <div className="h-3 w-24 animate-pulse rounded bg-muted" />
              <div className="h-6 w-16 animate-pulse rounded bg-muted" />
            </div>
          ))}
        </div>
      ) : (
        <div className="space-y-4">
          <div>
            <p className="text-xs text-muted-foreground">Vendor vetoed</p>
            <p className="text-2xl font-bold tabular-nums">
              {m ? m.policy_blocked.toFixed(0) : "—"}
              {blockRate && (
                <span className="ml-1 text-sm font-normal text-muted-foreground">
                  ({blockRate}%)
                </span>
              )}
            </p>
            <p className="text-xs text-muted-foreground">
              Policy engine blocked a non-SG vendor for an SG user
            </p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Fallback used</p>
            <p className="text-2xl font-bold tabular-nums">
              {m ? m.fallback_used.toFixed(0) : "—"}
              {fallbackRate && (
                <span className="ml-1 text-sm font-normal text-muted-foreground">
                  ({fallbackRate}%)
                </span>
              )}
            </p>
            <p className="text-xs text-muted-foreground">
              Primary vendor unhealthy; fallback chain activated
            </p>
          </div>
        </div>
      )}
      <p className="mt-4 border-t pt-3 text-xs text-muted-foreground">
        CloudWatch metrics:{" "}
        <code className="rounded bg-muted px-1">PolicyBlocked</code>,{" "}
        <code className="rounded bg-muted px-1">FallbackUsed</code>
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main view
// ---------------------------------------------------------------------------

export function Strategist() {
  const [params] = useSearchParams();
  const window = (params.get("window") ?? "1h") as TimeWindow;

  const { data: m, isLoading, isError, error, refetch } = useStrategistMetrics(window);

  const loading = isLoading && !m;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Strategist</h1>
          <p className="text-sm text-muted-foreground">
            Vendor selection · routing path · policy engine
          </p>
        </div>
        <TimeWindowSelector />
      </div>

      {isError && (
        <ErrorBanner
          message={
            error instanceof Error
              ? error.message
              : "Couldn't load strategist metrics."
          }
          onRetry={() => void refetch()}
        />
      )}

      {/* KPI row */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <KpiCard
          title="Total routed"
          value={m ? m.total.toFixed(0) : null}
          loading={loading}
        />
        <KpiCard
          title="Deterministic"
          value={m ? pct(m.deterministic_route, m.total) : null}
          loading={loading}
        />
        <KpiCard
          title="Arbitration"
          value={m ? pct(m.arbitration_route, m.total) : null}
          loading={loading}
        />
        <KpiCard
          title="Errors"
          value={m ? m.errors.toFixed(0) : null}
          alert={m != null && m.errors > 0}
          alertIcon="▲"
          loading={loading}
        />
      </div>

      {/* Vendor donut + policy panel */}
      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-2 rounded-lg border bg-card p-4">
          <h3 className="mb-1 text-sm font-medium">Vendor selection</h3>
          <p className="mb-3 text-xs text-muted-foreground">
            Which model was chosen by the routing rule and health check
          </p>
          <VendorChart m={m} loading={loading} />
        </div>
        <PolicyPanel m={m} loading={loading} />
      </div>

      {/* Routing path chart */}
      <div className="rounded-lg border bg-card p-4">
        <h3 className="mb-1 text-sm font-medium">Routing path split</h3>
        <p className="mb-4 text-xs text-muted-foreground">
          Deterministic: confidence ≥ 0.85 bypasses Haiku arbitration.
          Arbitration: Haiku selects among candidate vendors.
        </p>
        <PathChart m={m} loading={loading} />
      </div>
    </div>
  );
}
