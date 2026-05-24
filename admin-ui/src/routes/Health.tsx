import { useSearchParams } from "react-router-dom";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { usePipelineMetrics, type TimeWindow } from "../api/metrics";
import { useServiceHealth } from "../api/health";
import { KpiCard } from "../components/KpiCard";
import { TimeWindowSelector } from "../components/TimeWindowSelector";
import { LayerStatusSidebar } from "../components/LayerStatusSidebar";
import { ErrorBanner } from "../components/ErrorBanner";
import { Spinner } from "../components/Spinner";
import type { PipelineMetrics } from "../schemas/metrics";

function fmt(n: number | null | undefined, decimals = 1): string | null {
  if (n == null) return null;
  return n.toFixed(decimals);
}

function requestsPerMinute(m: PipelineMetrics): string | null {
  if (!m.total_requests || !m.period_minutes) return "0";
  return fmt(m.total_requests / m.period_minutes);
}

// The backend returns one aggregate data point per window (not time-series).
// Charts show a single bar/line for the current period.
function toChartData(m: PipelineMetrics) {
  return [
    {
      name: `Last ${m.period_minutes}m`,
      requests: m.total_requests,
      escalated: m.escalation_rate_pct != null
        ? (m.escalation_rate_pct / 100) * m.total_requests
        : 0,
    },
  ];
}

function EmptyChart({ message }: { message: string }) {
  return (
    <div className="flex h-full items-center justify-center rounded-lg border border-dashed">
      <p className="text-sm text-muted-foreground">{message}</p>
    </div>
  );
}

export function Health() {
  const [params] = useSearchParams();
  const window = (params.get("window") ?? "1h") as TimeWindow;

  const metrics = usePipelineMetrics(window);
  const health = useServiceHealth();

  const isLoading = metrics.isLoading && !metrics.data;
  const m = metrics.data;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Pipeline Health</h1>
          <p className="text-sm text-muted-foreground">
            Evidor.ai — ap-southeast-1
          </p>
        </div>
        <TimeWindowSelector />
      </div>

      {/* Error state */}
      {metrics.isError && (
        <ErrorBanner
          message={
            metrics.error instanceof Error
              ? metrics.error.message
              : "Couldn't load pipeline metrics."
          }
          onRetry={() => void metrics.refetch()}
        />
      )}

      {/* KPI cards */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KpiCard
          title="Requests / minute"
          value={m ? requestsPerMinute(m) : null}
          unit="req/min"
          loading={isLoading}
        />
        <KpiCard
          title="p99 latency"
          value={m ? fmt(m.latency_ms.p99, 0) : null}
          unit="ms"
          alert={m?.latency_ms.p99 != null && m.latency_ms.p99 > 2000}
          alertIcon="▲"
          loading={isLoading}
        />
        <KpiCard
          title="Error rate"
          value={m ? fmt(m.error_rate_pct) : null}
          unit="%"
          alert={m?.error_rate_pct != null && m.error_rate_pct > 2}
          alertIcon="▲"
          loading={isLoading}
        />
        <KpiCard
          title="Escalation rate"
          value={m ? fmt(m.escalation_rate_pct) : null}
          unit="%"
          loading={isLoading}
        />
      </div>

      {/* Charts + sidebar */}
      <div className="grid grid-cols-3 gap-4">
        {/* Line chart — requests over time */}
        <div className="col-span-2 rounded-lg border bg-card p-4">
          <h3 className="mb-4 text-sm font-medium">Request volume</h3>
          {isLoading ? (
            <div className="flex h-48 items-center justify-center">
              <Spinner />
            </div>
          ) : !m || m.total_requests === 0 ? (
            <EmptyChart message="No data for this window. Try a longer window or check that the metrics pipeline is running." />
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={toChartData(m)}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip />
                <Legend />
                <Line
                  type="monotone"
                  dataKey="requests"
                  name="Total requests"
                  stroke="hsl(var(--primary))"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="escalated"
                  name="Escalated"
                  stroke="hsl(var(--destructive))"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Layer status sidebar */}
        <LayerStatusSidebar
          health={health.data}
          loading={health.isLoading && !health.data}
          checkedAt={health.data?.checked_at}
        />
      </div>

      {/* Stacked bar chart — latency breakdown */}
      <div className="rounded-lg border bg-card p-4">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-medium">Latency breakdown (p50 / p99)</h3>
          <span className="text-xs text-muted-foreground">
            Per-layer breakdown requires time-series metrics endpoint
          </span>
        </div>
        {isLoading ? (
          <div className="flex h-48 items-center justify-center">
            <Spinner />
          </div>
        ) : !m ? (
          <EmptyChart message="No latency data available." />
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <BarChart
              data={[
                {
                  name: "Aggregate",
                  p50: m.latency_ms.p50 ?? 0,
                  p99: m.latency_ms.p99 ?? 0,
                },
              ]}
            >
              <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
              <XAxis dataKey="name" tick={{ fontSize: 12 }} />
              <YAxis
                tick={{ fontSize: 12 }}
                label={{
                  value: "ms",
                  angle: -90,
                  position: "insideLeft",
                  style: { fontSize: 12 },
                }}
              />
              <Tooltip formatter={(v: number) => `${v.toFixed(0)} ms`} />
              <Legend />
              <Bar
                dataKey="p50"
                name="p50 latency"
                fill="hsl(var(--primary))"
                radius={[4, 4, 0, 0]}
              />
              <Bar
                dataKey="p99"
                name="p99 latency"
                fill="hsl(var(--destructive))"
                radius={[4, 4, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
