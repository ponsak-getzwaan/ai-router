import { useState, type ReactElement } from "react";
import { useForm } from "react-hook-form";
import { useRunTrace } from "../api/test-console";
import { Spinner } from "../components/Spinner";
import { Button } from "../components/ui/button";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { Input } from "../components/ui/input";
import { Badge } from "../components/ui/badge";
import type { TestConsoleResponse, TestConsoleLayerResult } from "../schemas/test-console";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const LAYER_COLOR: Record<string, string> = {
  redactor:   "bg-green-400",
  bouncer:    "bg-blue-400",
  classifier: "bg-violet-400",
  strategist: "bg-amber-400",
  adapter:    "bg-slate-400",
};

const LAYER_LABEL: Record<string, string> = {
  redactor:   "Redactor",
  bouncer:    "Bouncer",
  classifier: "Classifier",
  strategist: "Strategist",
  adapter:    "Adapter",
};

function shortVendor(v: string | null | undefined): string {
  if (!v) return "—";
  return v.split(".").pop()?.replace(/-v\d+:\d+$/, "") ?? v;
}

function renderOutcomeValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "number") return String(v);
  if (typeof v === "string") return v;
  if (Array.isArray(v)) return v.length > 0 ? v.join(", ") : "none";
  return JSON.stringify(v);
}

// ---------------------------------------------------------------------------
// Latency breakdown bar
// ---------------------------------------------------------------------------

function LatencyBar({ layers, total }: { layers: TestConsoleLayerResult[]; total: number }) {
  const timed = layers.filter((l) => l.latency_ms > 0);
  if (timed.length === 0) return null;
  return (
    <div>
      <p className="mb-1 text-xs text-muted-foreground">
        Total pipeline latency: {total} ms
      </p>
      <div className="flex h-3 w-full overflow-hidden rounded-full bg-muted">
        {timed.map((l) => {
          const pct = total > 0 ? (l.latency_ms / total) * 100 : 0;
          return (
            <div
              key={l.layer}
              title={`${LAYER_LABEL[l.layer] ?? l.layer}: ${l.latency_ms} ms`}
              className={`${LAYER_COLOR[l.layer] ?? "bg-gray-400"}`}
              style={{ width: `${pct}%` }}
            />
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Layer badge
// ---------------------------------------------------------------------------

function layerBadge(layer: string, outcome: Record<string, unknown>): ReactElement | null {
  const errorType = outcome["error_type"];
  if (typeof errorType === "string") {
    return <Badge variant="destructive">{errorType}</Badge>;
  }
  if (layer === "redactor") {
    const count = outcome["entity_count"];
    return (
      <Badge variant={count ? "warning" : "success"}>
        {count ? `${String(count)} entities redacted` : "No PII found"}
      </Badge>
    );
  }
  if (layer === "bouncer") {
    const allowed = outcome["allowed"];
    return (
      <Badge variant={allowed ? "success" : "destructive"}>
        {allowed ? "Allowed" : "Blocked"}
      </Badge>
    );
  }
  if (layer === "classifier") {
    const intent = outcome["intent"];
    if (typeof intent === "string") return <Badge variant="default">{intent}</Badge>;
  }
  if (layer === "strategist") {
    const blocked = outcome["blocked"];
    const vendor = outcome["primary_vendor"];
    return (
      <Badge variant={blocked ? "destructive" : "success"}>
        {blocked ? "Blocked" : shortVendor(typeof vendor === "string" ? vendor : null)}
      </Badge>
    );
  }
  return null;
}

function LayerCard({ result }: { result: TestConsoleLayerResult }) {
  const [expanded, setExpanded] = useState(false);
  const hasError = typeof result.outcome["error_type"] === "string";
  const badge = layerBadge(result.layer, result.outcome);

  return (
    <div className={`rounded-lg border bg-card ${hasError ? "border-red-200" : ""}`}>
      <div
        className="flex cursor-pointer items-center gap-3 px-4 py-3"
        onClick={() => setExpanded((v) => !v)}
        role="button"
        aria-expanded={expanded}
      >
        <span
          className={`h-2.5 w-2.5 shrink-0 rounded-full ${LAYER_COLOR[result.layer] ?? "bg-gray-400"}`}
        />
        <span className="font-medium">{LAYER_LABEL[result.layer] ?? result.layer}</span>
        {badge}
        <span className="ml-auto text-xs text-muted-foreground">{expanded ? "▲" : "▼"}</span>
      </div>

      {expanded && (
        <div className="border-t px-4 py-3">
          <table className="w-full text-xs">
            <tbody>
              {Object.entries(result.outcome).map(([k, v]) => (
                <tr key={k} className="border-b last:border-0">
                  <td className="py-1.5 pr-4 font-mono text-muted-foreground">{k}</td>
                  <td className="py-1.5 font-mono">{renderOutcomeValue(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Trace result pane
// ---------------------------------------------------------------------------

function TraceResult({ result }: { result: TestConsoleResponse }) {
  const blocked =
    result.layers.length === 1 &&
    result.layers[0]?.layer === "bouncer" &&
    result.layers[0]?.outcome["allowed"] === false;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm font-medium">Trace complete</span>
        {result.timed_out ? (
          <Badge variant="warning">Timed out — pipeline may still be running</Badge>
        ) : (
          <Badge variant={result.error ? "destructive" : "success"}>
            {result.error ? `Error: ${result.error}` : "OK"}
          </Badge>
        )}
        <span className="ml-auto font-mono text-xs text-muted-foreground">
          {result.correlation_id}
        </span>
      </div>

      <LatencyBar layers={result.layers} total={result.total_latency_ms} />

      {result.layers.length > 0 && (
        <div className="relative space-y-2 pl-4">
          <div className="absolute left-0 top-3 h-[calc(100%-1.5rem)] w-px bg-border" />
          {result.layers.map((l, i) => (
            <LayerCard key={`${l.layer}-${i}`} result={l} />
          ))}
        </div>
      )}

      <div className="rounded-lg border bg-muted/30 px-4 py-3 text-sm">
        {result.timed_out ? (
          <p className="text-muted-foreground">
            Pipeline did not complete within 30 s. The Orchestrator may still be
            processing — check the Audit Log for correlation ID{" "}
            <span className="font-mono">{result.correlation_id}</span>.
          </p>
        ) : result.error ? (
          <p className="text-destructive">
            Pipeline error: <span className="font-mono">{result.error}</span>
          </p>
        ) : blocked ? (
          <p className="text-muted-foreground">Request was blocked by the Bouncer.</p>
        ) : (
          <p>
            Selected vendor:{" "}
            <span className="font-mono font-medium">{shortVendor(result.final_vendor)}</span>
            {". "}Vendor was invoked and the response was de-redacted.
          </p>
        )}
      </div>

      <p className="text-xs text-muted-foreground">
        Latency values are end-to-end (SQS submit → audit written). Per-layer
        latencies are available in CloudWatch logs.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Form values
// ---------------------------------------------------------------------------

interface FormValues {
  message: string;
  user_sub: string;
  session_id: string;
  show_overrides: boolean;
}

// ---------------------------------------------------------------------------
// Main view
// ---------------------------------------------------------------------------

export function TestConsole() {
  const trace = useRunTrace();
  const [result, setResult] = useState<TestConsoleResponse | null>(null);

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<FormValues>({
    defaultValues: {
      message: "",
      user_sub: "admin-test-user",
      session_id: "admin-test-session",
      show_overrides: false,
    },
  });

  const showOverrides = watch("show_overrides");

  async function onSubmit(values: FormValues) {
    setResult(null);
    try {
      const res = await trace.mutateAsync({
        message: values.message.trim(),
        user_sub: values.user_sub.trim() || "admin-test-user",
        session_id: values.session_id.trim() || "admin-test-session",
      });
      setResult(res);
    } catch {
      // error available via trace.error
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Test Console</h1>
        <p className="text-sm text-muted-foreground">
          Send a message through the real pipeline. Each trace increments
          Bouncer and Classifier metrics.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* ---- Left pane: input form ---- */}
        <div className="space-y-5 rounded-lg border bg-card p-5">
          <h2 className="font-medium">Input</h2>

          <form
            onSubmit={(e) => void handleSubmit(onSubmit)(e)}
            className="space-y-4"
          >
            <div className="space-y-1.5">
              <Label htmlFor="message">
                Message <span className="text-destructive">*</span>
              </Label>
              <Textarea
                id="message"
                rows={6}
                placeholder="e.g. Can you help me debug this Python function? It keeps raising a TypeError."
                {...register("message", {
                  required: "Message is required",
                  minLength: { value: 1, message: "Message cannot be empty" },
                  maxLength: { value: 4096, message: "Message too long (max 4096 chars)" },
                })}
              />
              {errors.message && (
                <p className="text-xs text-destructive">{errors.message.message}</p>
              )}
              <p className="text-xs text-muted-foreground">
                PII is safe — Presidio redaction runs before any LLM call.
                The audit log never stores message content.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <input
                id="show_overrides"
                type="checkbox"
                className="h-4 w-4 rounded border-input"
                {...register("show_overrides")}
              />
              <Label htmlFor="show_overrides" className="cursor-pointer text-xs text-muted-foreground">
                Override user_sub / session_id
              </Label>
            </div>

            {showOverrides && (
              <div className="space-y-3 rounded-md border bg-muted/30 px-3 py-3">
                <div className="space-y-1">
                  <Label htmlFor="user_sub" className="text-xs">user_sub</Label>
                  <Input
                    id="user_sub"
                    className="font-mono text-xs"
                    placeholder="admin-test-user"
                    {...register("user_sub", { maxLength: 128 })}
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="session_id" className="text-xs">session_id</Label>
                  <Input
                    id="session_id"
                    className="font-mono text-xs"
                    placeholder="admin-test-session"
                    {...register("session_id", { maxLength: 128 })}
                  />
                </div>
              </div>
            )}

            <Button type="submit" disabled={trace.isPending} className="w-full">
              {trace.isPending ? (
                <span className="flex items-center gap-2">
                  <Spinner className="h-4 w-4" />
                  Waiting for pipeline result…
                </span>
              ) : (
                "Run trace"
              )}
            </Button>

            {trace.isError && (
              <p className="text-xs text-destructive">
                {trace.error instanceof Error
                  ? trace.error.message
                  : "Trace failed. Check the backend logs."}
              </p>
            )}
          </form>
        </div>

        {/* ---- Right pane: trace result ---- */}
        <div className="rounded-lg border bg-card p-5">
          <h2 className="mb-4 font-medium">Trace</h2>

          {!result && !trace.isPending && (
            <div className="flex h-64 flex-col items-center justify-center gap-2 text-center">
              <p className="font-medium text-muted-foreground">No trace yet</p>
              <p className="text-sm text-muted-foreground">
                Enter a message and click "Run trace". Results come from the
                audit log after the Orchestrator finishes (up to 30 s).
              </p>
            </div>
          )}

          {trace.isPending && (
            <div className="flex h-64 flex-col items-center justify-center gap-3 text-muted-foreground">
              <Spinner className="h-6 w-6" />
              <p className="text-sm">Message sent — waiting for Orchestrator…</p>
              <p className="text-xs">Up to 30 s. Bouncer → Classifier → Strategist → Vendor</p>
            </div>
          )}

          {result && !trace.isPending && <TraceResult result={result} />}
        </div>
      </div>
    </div>
  );
}
