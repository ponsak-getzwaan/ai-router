import { useState, type ReactElement } from "react";
import { useForm } from "react-hook-form";
import { useRunTrace } from "../api/test-console";
import { Spinner } from "../components/Spinner";
import { Button } from "../components/ui/button";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { Input } from "../components/ui/input";
import { Badge } from "../components/ui/badge";
import { INTENT_DOMAINS } from "../schemas/test-console";
import type { TestConsoleResponse, TestConsoleLayerResult } from "../schemas/test-console";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const LAYER_COLOR: Record<string, string> = {
  bouncer: "bg-blue-400",
  classifier: "bg-violet-400",
  strategist: "bg-amber-400",
  adapter: "bg-slate-400",
};

const LAYER_LABEL: Record<string, string> = {
  bouncer: "Bouncer",
  classifier: "Classifier",
  strategist: "Strategist",
  adapter: "Adapter",
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
  return JSON.stringify(v);
}

// ---------------------------------------------------------------------------
// Latency breakdown bar
// ---------------------------------------------------------------------------

function LatencyBar({ layers, total }: { layers: TestConsoleLayerResult[]; total: number }) {
  return (
    <div>
      <p className="mb-1 text-xs text-muted-foreground">
        Latency breakdown — total {total} ms
      </p>
      <div className="flex h-3 w-full overflow-hidden rounded-full bg-muted">
        {layers.map((l) => {
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
      <div className="mt-1 flex flex-wrap gap-3">
        {layers.map((l) => (
          <span key={l.layer} className="flex items-center gap-1 text-xs text-muted-foreground">
            <span
              className={`inline-block h-2 w-2 rounded-full ${LAYER_COLOR[l.layer] ?? "bg-gray-400"}`}
            />
            {LAYER_LABEL[l.layer] ?? l.layer}: {l.latency_ms} ms
          </span>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Layer card
// ---------------------------------------------------------------------------

function layerBadge(layer: string, outcome: Record<string, unknown>): ReactElement | null {
  const errorType = outcome["error_type"];
  if (typeof errorType === "string") {
    return <Badge variant="destructive">{errorType}</Badge>;
  }
  const skipped = outcome["skipped"];
  if (skipped !== undefined) {
    return <Badge variant="default">Skipped</Badge>;
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
    if (typeof intent === "string") {
      const overridden = outcome["overridden"];
      return (
        <span className="flex items-center gap-1.5">
          <Badge variant="default">{intent}</Badge>
          {overridden === true && (
            <Badge variant="warning" className="text-xs">overridden</Badge>
          )}
        </span>
      );
    }
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
  const badge = layerBadge(result.layer, result.outcome);
  const hasError = typeof result.outcome["error_type"] === "string";
  const isSkipped = result.outcome["skipped"] !== undefined;

  return (
    <div
      className={`rounded-lg border bg-card ${hasError ? "border-red-200" : isSkipped ? "border-dashed" : ""}`}
    >
      <div
        className="flex cursor-pointer items-center gap-3 px-4 py-3"
        onClick={() => setExpanded((v) => !v)}
        role="button"
        aria-expanded={expanded}
      >
        {/* Layer colour dot */}
        <span
          className={`h-2.5 w-2.5 shrink-0 rounded-full ${LAYER_COLOR[result.layer] ?? "bg-gray-400"}`}
        />
        <span className="font-medium">{LAYER_LABEL[result.layer] ?? result.layer}</span>
        <span className="text-xs text-muted-foreground">{result.latency_ms} ms</span>
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

interface TraceProps {
  result: TestConsoleResponse;
}

function TraceResult({ result }: TraceProps) {
  const finalLayer = result.layers[result.layers.length - 1];
  const stopped =
    finalLayer?.layer === "bouncer" &&
    result.layers.length === 1 &&
    result.layers[0]?.outcome["allowed"] === false;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm font-medium">Trace complete</span>
        <Badge variant={result.error ? "destructive" : "success"}>
          {result.error ? `Error: ${result.error}` : "OK"}
        </Badge>
        {result.dry_run && (
          <Badge variant="default">Dry-run</Badge>
        )}
        <span className="ml-auto font-mono text-xs text-muted-foreground">
          {result.correlation_id}
        </span>
      </div>

      {/* Latency bar */}
      {result.layers.length > 0 && (
        <LatencyBar layers={result.layers} total={result.total_latency_ms} />
      )}

      {/* Layer timeline */}
      <div className="relative space-y-2 pl-4">
        {/* Vertical line */}
        <div className="absolute left-0 top-3 h-[calc(100%-1.5rem)] w-px bg-border" />
        {result.layers.map((l, i) => (
          <LayerCard key={`${l.layer}-${i}`} result={l} />
        ))}
      </div>

      {/* Final result */}
      <div className="rounded-lg border bg-muted/30 px-4 py-3 text-sm">
        {result.error ? (
          <p className="text-destructive">
            Pipeline error: <span className="font-mono">{result.error}</span>
          </p>
        ) : stopped ? (
          <p className="text-muted-foreground">Request was blocked by the Bouncer — no further layers ran.</p>
        ) : result.dry_run ? (
          <p className="text-muted-foreground">
            Dry-run complete. Selected vendor:{" "}
            <span className="font-mono font-medium">{shortVendor(result.final_vendor)}</span>
            . Vendor was not invoked (Phase 1 admin context or dry_run=true).
          </p>
        ) : (
          <p>
            Final vendor:{" "}
            <span className="font-mono font-medium">{shortVendor(result.final_vendor)}</span>
          </p>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Form values
// ---------------------------------------------------------------------------

interface FormValues {
  redacted_message: string;
  dry_run: boolean;
  user_sub: string;
  session_id: string;
  intent_override: string;
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
      redacted_message: "",
      dry_run: true,
      user_sub: "admin-test-user",
      session_id: "admin-test-session",
      intent_override: "",
      show_overrides: false,
    },
  });

  const showOverrides = watch("show_overrides");

  async function onSubmit(values: FormValues) {
    setResult(null);
    try {
      const payload: Parameters<typeof trace.mutateAsync>[0] = {
        redacted_message: values.redacted_message.trim(),
        dry_run: values.dry_run,
        user_sub: values.user_sub.trim() || "admin-test-user",
        session_id: values.session_id.trim() || "admin-test-session",
      };
      if (values.intent_override) payload.intent_override = values.intent_override;
      const res = await trace.mutateAsync(payload);
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
          Trace a message through the pipeline layers without sending to a real user.
          Traces are logged with redacted content only.
        </p>
      </div>

      {/* PII warning */}
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
        <strong>Input must be already-redacted.</strong> Do not paste raw user
        messages or any text containing PII. The test console is not a debugging
        escape hatch for raw input (CLAUDE.md §7).
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* ---- Left pane: input form ---- */}
        <div className="space-y-5 rounded-lg border bg-card p-5">
          <h2 className="font-medium">Input</h2>

          <form
            onSubmit={(e) => void handleSubmit(onSubmit)(e)}
            className="space-y-4"
          >
            {/* Message */}
            <div className="space-y-1.5">
              <Label htmlFor="redacted_message">
                Redacted message <span className="text-destructive">*</span>
              </Label>
              <Textarea
                id="redacted_message"
                rows={6}
                placeholder="e.g. My [NRIC] was used without permission. I need help with my [ACCOUNT_NUMBER]."
                {...register("redacted_message", {
                  required: "Message is required",
                  minLength: { value: 1, message: "Message cannot be empty" },
                  maxLength: { value: 4096, message: "Message too long (max 4096 chars)" },
                })}
              />
              {errors.redacted_message && (
                <p className="text-xs text-destructive">{errors.redacted_message.message}</p>
              )}
            </div>

            {/* Dry-run toggle */}
            <div className="flex items-start gap-3">
              <input
                id="dry_run"
                type="checkbox"
                className="mt-0.5 h-4 w-4 rounded border-input"
                {...register("dry_run")}
              />
              <div>
                <Label htmlFor="dry_run">Dry-run (stop before vendor)</Label>
                <p className="text-xs text-muted-foreground">
                  Always enabled in Phase 1 — admin IAM denies{" "}
                  <code className="font-mono">bedrock:*</code>.
                </p>
              </div>
            </div>

            {/* Optional overrides toggle */}
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
                {/* Intent override — bypasses Classifier deep path (Bedrock denied) */}
                <div className="space-y-1">
                  <Label htmlFor="intent_override" className="text-xs">
                    Intent override
                  </Label>
                  <select
                    id="intent_override"
                    className="w-full rounded-md border border-input bg-background px-3 py-1.5 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                    {...register("intent_override")}
                  >
                    <option value="">— let Classifier decide —</option>
                    {INTENT_DOMAINS.map((d) => (
                      <option key={d} value={d}>{d}</option>
                    ))}
                  </select>
                  <p className="text-xs text-muted-foreground">
                    Skip Classifier and use this intent directly. Required when
                    the fast-path heuristics don&apos;t match (admin IAM denies{" "}
                    <code className="font-mono">bedrock:*</code>).
                  </p>
                </div>

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
                  Running trace…
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
                Enter a redacted message and click "Run trace" to see per-layer results.
              </p>
            </div>
          )}

          {trace.isPending && (
            <div className="flex h-64 flex-col items-center justify-center gap-3 text-muted-foreground">
              <Spinner className="h-6 w-6" />
              <p className="text-sm">Tracing through pipeline…</p>
            </div>
          )}

          {result && !trace.isPending && <TraceResult result={result} />}
        </div>
      </div>
    </div>
  );
}
