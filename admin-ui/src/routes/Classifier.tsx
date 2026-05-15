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
import { useClassifierMetrics, type TimeWindow } from "../api/metrics";
import { KpiCard } from "../components/KpiCard";
import { TimeWindowSelector } from "../components/TimeWindowSelector";
import { ErrorBanner } from "../components/ErrorBanner";
import { Spinner } from "../components/Spinner";
import type { ClassifierMetrics } from "../schemas/metrics";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function pct(numerator: number, denominator: number): string {
  if (denominator === 0) return "0%";
  return `${((numerator / denominator) * 100).toFixed(1)}%`;
}

function emptyChart(message: string) {
  return (
    <div className="flex h-full min-h-[200px] items-center justify-center rounded-lg border border-dashed">
      <p className="text-sm text-muted-foreground">{message}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Path split donut
// ---------------------------------------------------------------------------

const PATH_COLOURS = {
  "Fast path": "#22c55e",
  "Deep path": "#6366f1",
  Escalated: "#f59e0b",
};

function PathSplitChart({
  m,
  loading,
}: {
  m: ClassifierMetrics | undefined;
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner />
      </div>
    );
  }
  if (!m || m.total === 0) return emptyChart("No classifier data for this window.");

  const data = [
    { name: "Fast path", value: m.fast_path },
    { name: "Deep path", value: m.deep_path },
    { name: "Escalated", value: m.escalated },
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
          aria-label="Classifier path split"
        >
          {data.map((entry) => (
            <Cell
              key={entry.name}
              fill={PATH_COLOURS[entry.name as keyof typeof PATH_COLOURS] ?? "#94a3b8"}
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
// Intent distribution bar chart
// ---------------------------------------------------------------------------

// Palette cycles for however many intents exist
const INTENT_PALETTE = [
  "#6366f1",
  "#22c55e",
  "#f59e0b",
  "#ef4444",
  "#0ea5e9",
  "#8b5cf6",
  "#ec4899",
  "#14b8a6",
];

function IntentChart({
  m,
  loading,
}: {
  m: ClassifierMetrics | undefined;
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner />
      </div>
    );
  }

  const entries = Object.entries(m?.intent_counts ?? {});
  if (!m || entries.length === 0) {
    return emptyChart(
      m?.total === 0
        ? "No classifier data for this window."
        : "No intent breakdown available yet."
    );
  }

  // Sort descending by count
  const data = entries
    .sort(([, a], [, b]) => b - a)
    .map(([intent, count], i) => ({
      intent: intent.replace(/_/g, " "),
      count,
      fill: INTENT_PALETTE[i % INTENT_PALETTE.length] ?? "#94a3b8",
      pct: m.total > 0 ? ((count / m.total) * 100).toFixed(1) : "0",
    }));

  const barHeight = 36;
  const chartHeight = Math.max(200, data.length * barHeight + 40);
  // Longest intent label drives the Y-axis width
  const labelWidth = Math.min(
    180,
    Math.max(80, Math.max(...data.map((d) => d.intent.length)) * 7)
  );

  return (
    <ResponsiveContainer width="100%" height={chartHeight}>
      <BarChart data={data} layout="vertical" margin={{ left: 8, right: 48 }}>
        <CartesianGrid strokeDasharray="3 3" horizontal={false} />
        <XAxis type="number" tick={{ fontSize: 12 }} />
        <YAxis
          type="category"
          dataKey="intent"
          tick={{ fontSize: 12 }}
          width={labelWidth}
        />
        <Tooltip
          formatter={(value: number, _name: string, props: { payload?: { pct: string } }) =>
            [`${value.toFixed(0)} (${props.payload?.pct ?? ""}%)`, "Requests"]
          }
        />
        <Bar dataKey="count" radius={[0, 4, 4, 0]}>
          {data.map((d) => (
            <Cell key={d.intent} fill={d.fill} />
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
// Main view
// ---------------------------------------------------------------------------

export function Classifier() {
  const [params] = useSearchParams();
  const window = (params.get("window") ?? "1h") as TimeWindow;

  const { data: m, isLoading, isError, error, refetch } = useClassifierMetrics(window);

  const loading = isLoading && !m;

  const fastPct = m ? pct(m.fast_path, m.total) : null;
  const deepPct = m ? pct(m.deep_path, m.total) : null;
  const escalatePct = m ? pct(m.escalated, m.total) : null;
  const intentCount = m ? Object.keys(m.intent_counts).length : null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Classifier</h1>
          <p className="text-sm text-muted-foreground">
            Embedding fast path · Sonnet deep path · intent distribution
          </p>
        </div>
        <TimeWindowSelector />
      </div>

      {isError && (
        <ErrorBanner
          message={
            error instanceof Error
              ? error.message
              : "Couldn't load classifier metrics."
          }
          onRetry={() => void refetch()}
        />
      )}

      {/* KPI row */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <KpiCard
          title="Total classified"
          value={m ? m.total.toFixed(0) : null}
          loading={loading}
        />
        <KpiCard
          title="Fast path"
          value={fastPct}
          loading={loading}
        />
        <KpiCard
          title="Deep path"
          value={deepPct}
          loading={loading}
        />
        <KpiCard
          title="Escalated"
          value={escalatePct}
          alert={m != null && m.total > 0 && m.escalated / m.total > 0.1}
          alertIcon="▲"
          loading={loading}
        />
      </div>

      {/* Path split + intent distribution */}
      <div className="grid grid-cols-3 gap-4">
        {/* Path split donut — 1/3 */}
        <div className="rounded-lg border bg-card p-4">
          <h3 className="mb-1 text-sm font-medium">Fast vs deep path</h3>
          <p className="mb-3 text-xs text-muted-foreground">
            Fast path = embedding similarity above threshold.
            Deep path = Sonnet full classification.
          </p>
          <PathSplitChart m={m} loading={loading} />
        </div>

        {/* Intent distribution — 2/3 */}
        <div className="col-span-2 rounded-lg border bg-card p-4">
          <div className="mb-1 flex items-baseline justify-between">
            <h3 className="text-sm font-medium">Intent distribution</h3>
            {intentCount != null && (
              <span className="text-xs text-muted-foreground">
                {intentCount} intent{intentCount !== 1 ? "s" : ""} observed
              </span>
            )}
          </div>
          <p className="mb-4 text-xs text-muted-foreground">
            Ranked by volume over the selected window
          </p>
          <IntentChart m={m} loading={loading} />
        </div>
      </div>

      {/* Confidence note */}
      <div className="rounded-lg border border-dashed bg-card p-4">
        <h3 className="mb-1 text-sm font-medium text-muted-foreground">
          Confidence distribution
        </h3>
        <p className="text-xs text-muted-foreground">
          A per-request confidence histogram requires individual data points from
          the classifier layer. The current{" "}
          <code className="rounded bg-muted px-1">/admin/metrics/classifier</code>{" "}
          endpoint returns aggregate counts only. Add a{" "}
          <code className="rounded bg-muted px-1">ConfidenceHistogram</code>{" "}
          CloudWatch metric to the classifier and expose it here.
        </p>
      </div>
    </div>
  );
}
