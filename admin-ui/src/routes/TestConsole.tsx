import { useEffect, useRef, useState, type ReactElement } from "react";
import { useForm } from "react-hook-form";
import { apiFetch } from "../api/client";
import { Spinner } from "../components/Spinner";
import { Button } from "../components/ui/button";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { Input } from "../components/ui/input";
import { Badge } from "../components/ui/badge";
import { TestConsoleResponseSchema, type TestConsoleResponse, type TestConsoleLayerResult } from "../schemas/test-console";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ChatEntry {
  id: string;
  userMessage: string;
  pending: boolean;
  result: TestConsoleResponse | null;
  error: string | null;
}

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
// Layer card (used inside collapsible trace)
// ---------------------------------------------------------------------------

function layerBadge(layer: string, outcome: Record<string, unknown>): ReactElement | null {
  const errorType = outcome["error_type"];
  if (typeof errorType === "string") return <Badge variant="destructive">{errorType}</Badge>;
  if (layer === "redactor") {
    const count = outcome["entity_count"];
    return <Badge variant={count ? "warning" : "success"}>{count ? `${String(count)} entities redacted` : "No PII found"}</Badge>;
  }
  if (layer === "bouncer") {
    const allowed = outcome["allowed"];
    return <Badge variant={allowed ? "success" : "destructive"}>{allowed ? "Allowed" : "Blocked"}</Badge>;
  }
  if (layer === "classifier") {
    const intent = outcome["intent"];
    if (typeof intent === "string") return <Badge variant="default">{intent}</Badge>;
  }
  if (layer === "strategist") {
    const blocked = outcome["blocked"];
    const vendor = outcome["primary_vendor"];
    return <Badge variant={blocked ? "destructive" : "success"}>{blocked ? "Blocked" : shortVendor(typeof vendor === "string" ? vendor : null)}</Badge>;
  }
  return null;
}

function LayerCard({ result }: { result: TestConsoleLayerResult }) {
  const [expanded, setExpanded] = useState(false);
  const hasError = typeof result.outcome["error_type"] === "string";
  const badge = layerBadge(result.layer, result.outcome);
  return (
    <div className={`rounded-md border bg-background text-xs ${hasError ? "border-red-200" : ""}`}>
      <div className="flex cursor-pointer items-center gap-2 px-3 py-2" onClick={() => setExpanded((v) => !v)} role="button" aria-expanded={expanded}>
        <span className={`h-2 w-2 shrink-0 rounded-full ${LAYER_COLOR[result.layer] ?? "bg-gray-400"}`} />
        <span className="font-medium">{LAYER_LABEL[result.layer] ?? result.layer}</span>
        {badge}
        <span className="ml-auto text-muted-foreground">{expanded ? "▲" : "▼"}</span>
      </div>
      {expanded && (
        <div className="border-t px-3 py-2">
          <table className="w-full">
            <tbody>
              {Object.entries(result.outcome).map(([k, v]) => (
                <tr key={k} className="border-b last:border-0">
                  <td className="py-1 pr-3 font-mono text-muted-foreground">{k}</td>
                  <td className="py-1 font-mono">{renderOutcomeValue(v)}</td>
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
// Single chat bubble pair
// ---------------------------------------------------------------------------

function ChatBubble({ entry }: { entry: ChatEntry }) {
  const [showTrace, setShowTrace] = useState(false);
  const r = entry.result;

  const lastLayer = r != null ? r.layers[r.layers.length - 1] : null;
  const isBlocked = lastLayer?.layer === "bouncer" && lastLayer?.outcome["allowed"] === false;
  const isEscalated = lastLayer?.layer === "classifier" && lastLayer?.outcome["escalate"] === true;
  const isPolicyBlocked = lastLayer?.layer === "strategist" && lastLayer?.outcome["blocked"] === true;

  return (
    <div className="space-y-2">
      {/* User message — right aligned */}
      <div className="flex justify-end">
        <div className="max-w-[75%] rounded-2xl rounded-tr-sm bg-primary px-4 py-2.5 text-sm text-primary-foreground">
          {entry.userMessage}
        </div>
      </div>

      {/* Assistant / pipeline — left aligned */}
      <div className="flex items-start gap-2">
        <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold text-muted-foreground">
          AI
        </div>

        <div className="max-w-[80%] space-y-1.5">
          {entry.pending ? (
            <div className="flex items-center gap-2 rounded-2xl rounded-tl-sm border bg-card px-4 py-3 text-sm text-muted-foreground">
              <Spinner className="h-3.5 w-3.5" />
              <span>Processing… (up to 30 s)</span>
            </div>
          ) : entry.error ? (
            <div className="rounded-2xl rounded-tl-sm border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
              Request error: {entry.error}
            </div>
          ) : r ? (
            <>
              {/* Response text */}
              <div className="rounded-2xl rounded-tl-sm border bg-card px-4 py-3 text-sm leading-relaxed">
                {r.timed_out ? (
                  <span className="text-muted-foreground italic">
                    Pipeline timed out after 30 s — check Audit Log for{" "}
                    <span className="font-mono text-xs">{r.correlation_id}</span>.
                  </span>
                ) : r.error ? (
                  <span className="text-destructive">Pipeline error: {r.error}</span>
                ) : isBlocked ? (
                  <span className="text-muted-foreground italic">Request was blocked by the Bouncer.</span>
                ) : isEscalated ? (
                  <span className="text-muted-foreground italic">Request escalated for human review.</span>
                ) : isPolicyBlocked ? (
                  <span className="text-muted-foreground italic">Request blocked by compliance policy.</span>
                ) : r.response ? (
                  <pre className="whitespace-pre-wrap font-sans">{r.response}</pre>
                ) : (
                  <span className="text-muted-foreground italic">
                    Routing trace complete — {r.final_vendor ? <>would route to <span className="font-mono text-xs not-italic">{shortVendor(r.final_vendor)}</span></> : "no vendor selected"}.
                  </span>
                )}
              </div>

              {/* Metadata row */}
              <div className="flex flex-wrap items-center gap-2 px-1">
                {!r.timed_out && !r.error && (
                  <span className="text-xs text-muted-foreground">
                    {shortVendor(r.final_vendor)} · {Math.round(r.total_latency_ms / 1000 * 10) / 10} s
                  </span>
                )}
                <span className="font-mono text-xs text-muted-foreground/50">{r.correlation_id.slice(0, 8)}</span>
                {r.layers.length > 0 && (
                  <button
                    onClick={() => setShowTrace((v) => !v)}
                    className="ml-auto text-xs text-muted-foreground underline-offset-2 hover:underline"
                  >
                    {showTrace ? "Hide trace" : "Show trace"}
                  </button>
                )}
              </div>

              {/* Collapsible layer trace */}
              {showTrace && r.layers.length > 0 && (
                <div className="space-y-1 pl-1">
                  {r.layers.map((l, i) => (
                    <LayerCard key={`${l.layer}-${i}`} result={l} />
                  ))}
                </div>
              )}
            </>
          ) : null}
        </div>
      </div>
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
// History persistence (localStorage)
// ---------------------------------------------------------------------------

const HISTORY_KEY = "evidor.testConsole.history";
const MAX_HISTORY = 100;

function loadHistory(): ChatEntry[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as ChatEntry[];
    // Any entry still pending means the page was navigated away mid-request
    return parsed.map((e) =>
      e.pending
        ? { ...e, pending: false, error: "Request interrupted — page was navigated away." }
        : e
    );
  } catch {
    return [];
  }
}

function saveHistory(history: ChatEntry[]): void {
  try {
    const trimmed = history.slice(-MAX_HISTORY);
    localStorage.setItem(HISTORY_KEY, JSON.stringify(trimmed));
  } catch {
    // localStorage quota exceeded — silently ignore
  }
}

// ---------------------------------------------------------------------------
// Main view
// ---------------------------------------------------------------------------

export function TestConsole() {
  const [history, setHistory] = useState<ChatEntry[]>(loadHistory);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Persist history to localStorage on every change
  useEffect(() => {
    saveHistory(history);
  }, [history]);

  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    defaultValues: {
      message: "",
      user_sub: "admin-test-user",
      session_id: "admin-test-session",
      show_overrides: false,
    },
  });

  const showOverrides = watch("show_overrides");

  // Scroll to bottom whenever history changes
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [history]);

  async function onSubmit(values: FormValues) {
    const entryId = crypto.randomUUID();
    const userMessage = values.message.trim();

    // Add pending entry and clear the input immediately
    setHistory((h) => [...h, { id: entryId, userMessage, pending: true, result: null, error: null }]);
    reset({ ...values, message: "" });

    try {
      const raw = await apiFetch<unknown>("/admin/test-console", {
        method: "POST",
        body: JSON.stringify({
          redacted_message: userMessage,
          user_sub: values.user_sub.trim() || "admin-test-user",
          session_id: values.session_id.trim() || "admin-test-session",
        }),
      });
      const result = TestConsoleResponseSchema.parse(raw);
      setHistory((h) => h.map((e) => e.id === entryId ? { ...e, pending: false, result } : e));
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Request failed";
      setHistory((h) => h.map((e) => e.id === entryId ? { ...e, pending: false, error: msg } : e));
    }
  }

  const anyPending = history.some((e) => e.pending);

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col">
      {/* Header */}
      <div className="mb-3 shrink-0">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold">Test Console</h1>
            <p className="text-sm text-muted-foreground">
              Send messages through the real pipeline. Each trace increments Bouncer and Classifier metrics.
            </p>
          </div>
          {history.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setHistory([]);
                localStorage.removeItem(HISTORY_KEY);
              }}
            >
              Clear
            </Button>
          )}
        </div>
      </div>

      {/* Chat history — scrollable */}
      <div className="min-h-0 flex-1 overflow-y-auto rounded-lg border bg-muted/20 px-4 py-4">
        {history.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-muted-foreground">
            <p className="font-medium">No messages yet</p>
            <p className="text-sm">Type a message below and press Send.</p>
          </div>
        ) : (
          <div className="space-y-6">
            {history.map((entry) => (
              <ChatBubble key={entry.id} entry={entry} />
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Input — fixed at bottom */}
      <div className="mt-3 shrink-0 rounded-lg border bg-card p-4">
        <form onSubmit={(e) => void handleSubmit(onSubmit)(e)} className="space-y-3">
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
            <div className="flex gap-3">
              <div className="flex-1 space-y-1">
                <Label htmlFor="user_sub" className="text-xs">user_sub</Label>
                <Input id="user_sub" className="font-mono text-xs" placeholder="admin-test-user" {...register("user_sub", { maxLength: 128 })} />
              </div>
              <div className="flex-1 space-y-1">
                <Label htmlFor="session_id" className="text-xs">session_id</Label>
                <Input id="session_id" className="font-mono text-xs" placeholder="admin-test-session" {...register("session_id", { maxLength: 128 })} />
              </div>
            </div>
          )}

          <div className="flex gap-2">
            <Textarea
              id="message"
              rows={2}
              placeholder="Type a message… (PII is redacted by Presidio before any LLM call)"
              className="resize-none"
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void handleSubmit(onSubmit)();
                }
              }}
              {...register("message", {
                required: "Message is required",
                minLength: { value: 1, message: "Message cannot be empty" },
                maxLength: { value: 4096, message: "Message too long (max 4096 chars)" },
              })}
            />
            <Button type="submit" disabled={isSubmitting || anyPending} className="self-end px-5">
              {anyPending ? <Spinner className="h-4 w-4" /> : "Send"}
            </Button>
          </div>

          {errors.message && (
            <p className="text-xs text-destructive">{errors.message.message}</p>
          )}
        </form>
      </div>
    </div>
  );
}
