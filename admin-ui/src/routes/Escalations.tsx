import { useState, useMemo, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { formatDistanceToNow, subHours, subDays, parseISO } from "date-fns";
import { useEscalations, useApprove, useReject, useRequeue } from "../api/escalations";
import type { EscalationMessage } from "../schemas/escalations";
import { ErrorBanner } from "../components/ErrorBanner";
import { Skeleton } from "../components/ui/skeleton";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Checkbox } from "../components/ui/checkbox";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from "../components/ui/dialog";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type DatePreset = "all" | "1h" | "24h" | "7d";
type ActionType = "approve" | "reject" | "requeue";

interface PendingAction {
  type: ActionType;
  messages: EscalationMessage[];
}

// ---------------------------------------------------------------------------
// Filter sidebar
// ---------------------------------------------------------------------------

interface FilterSidebarProps {
  reasons: string[];
  selectedReasons: string[];
  datePreset: DatePreset;
  onReasonsChange: (r: string[]) => void;
  onDatePresetChange: (p: DatePreset) => void;
  onReset: () => void;
}

const DATE_PRESETS: { value: DatePreset; label: string }[] = [
  { value: "all", label: "All time" },
  { value: "1h", label: "Last hour" },
  { value: "24h", label: "Last 24h" },
  { value: "7d", label: "Last 7 days" },
];

function FilterSidebar({
  reasons,
  selectedReasons,
  datePreset,
  onReasonsChange,
  onDatePresetChange,
  onReset,
}: FilterSidebarProps) {
  function toggleReason(r: string) {
    onReasonsChange(
      selectedReasons.includes(r)
        ? selectedReasons.filter((x) => x !== r)
        : [...selectedReasons, r]
    );
  }

  return (
    <aside className="w-60 shrink-0 space-y-6 rounded-lg border bg-card p-4">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Filters</span>
        <button
          onClick={onReset}
          className="text-xs text-muted-foreground hover:text-foreground"
        >
          Reset
        </button>
      </div>

      {/* Date range */}
      <div className="space-y-2">
        <Label className="text-xs uppercase tracking-wide text-muted-foreground">
          Time range
        </Label>
        <div className="space-y-1">
          {DATE_PRESETS.map(({ value, label }) => (
            <button
              key={value}
              onClick={() => onDatePresetChange(value)}
              className={`block w-full rounded px-2 py-1.5 text-left text-sm transition-colors ${
                datePreset === value
                  ? "bg-accent text-accent-foreground font-medium"
                  : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Reason filter */}
      {reasons.length > 0 && (
        <div className="space-y-2">
          <Label className="text-xs uppercase tracking-wide text-muted-foreground">
            Reason
          </Label>
          <div className="space-y-2">
            {reasons.map((r) => (
              <label key={r} className="flex cursor-pointer items-center gap-2">
                <Checkbox
                  checked={selectedReasons.includes(r)}
                  onChange={() => toggleReason(r)}
                />
                <span className="text-sm capitalize">
                  {r.replace(/_/g, " ")}
                </span>
              </label>
            ))}
          </div>
        </div>
      )}
    </aside>
  );
}

// ---------------------------------------------------------------------------
// Confirmation dialog
// ---------------------------------------------------------------------------

interface ConfirmDialogProps {
  pending: PendingAction | null;
  onClose: () => void;
  onConfirm: (annotation: string) => void;
  isLoading: boolean;
}

function ConfirmDialog({ pending, onClose, onConfirm, isLoading }: ConfirmDialogProps) {
  const [text, setText] = useState("");

  if (!pending) return null;

  const count = pending.messages.length;
  const plural = count > 1 ? `${count} escalations` : "this escalation";

  const config = {
    approve: {
      title: `Approve ${plural}?`,
      description:
        "The message will be released to the routing layer with its original intent classification.",
      buttonLabel: count > 1 ? `Approve ${count}` : "Approve",
      buttonVariant: "default" as const,
      needsText: false,
      textLabel: "",
      textPlaceholder: "",
      textMin: 0,
    },
    reject: {
      title: `Reject ${plural}?`,
      description:
        "The message will move to the dead-letter queue and the user will not receive a response.",
      buttonLabel: count > 1 ? `Reject ${count}` : "Reject",
      buttonVariant: "destructive" as const,
      needsText: true,
      textLabel: "Reason for rejection (required, min 10 characters)",
      textPlaceholder: "Describe why this escalation is being rejected…",
      textMin: 10,
    },
    requeue: {
      title: `Requeue ${plural}?`,
      description:
        "The message will return to the escalation queue. The next reviewer will see your annotation.",
      buttonLabel: count > 1 ? `Requeue ${count}` : "Requeue",
      buttonVariant: "outline" as const,
      needsText: false,
      textLabel: "Annotation (optional)",
      textPlaceholder: "Add context for the next reviewer…",
      textMin: 0,
    },
  }[pending.type];

  const canSubmit =
    !config.needsText || text.trim().length >= config.textMin;

  function handleConfirm() {
    if (!canSubmit) return;
    onConfirm(text.trim());
    setText("");
  }

  return (
    <Dialog
      open={pending !== null}
      onOpenChange={(open) => {
        if (!open) {
          setText("");
          onClose();
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{config.title}</DialogTitle>
          <DialogDescription className="pt-1">
            {config.description}
          </DialogDescription>
        </DialogHeader>

        {(config.needsText || pending.type === "requeue") && (
          <div className="space-y-1.5 py-2">
            <Label htmlFor="action-text">{config.textLabel}</Label>
            <Textarea
              id="action-text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={config.textPlaceholder}
              rows={3}
            />
            {config.needsText && text.trim().length > 0 && text.trim().length < config.textMin && (
              <p className="text-xs text-destructive">
                Minimum {config.textMin} characters ({config.textMin - text.trim().length} more needed)
              </p>
            )}
          </div>
        )}

        <DialogFooter className="gap-2 pt-2">
          <DialogClose asChild>
            <Button variant="outline" size="sm" disabled={isLoading}>
              Cancel
            </Button>
          </DialogClose>
          <Button
            variant={config.buttonVariant}
            size="sm"
            onClick={handleConfirm}
            disabled={isLoading || !canSubmit}
          >
            {isLoading ? "Working…" : config.buttonLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Row
// ---------------------------------------------------------------------------

interface RowProps {
  msg: EscalationMessage;
  selected: boolean;
  onSelect: (id: string, checked: boolean) => void;
  onAction: (type: ActionType, msg: EscalationMessage) => void;
}

function EscalationRow({ msg, selected, onSelect, onAction }: RowProps) {
  const [expanded, setExpanded] = useState(false);

  const sentAgo = msg.sent_at
    ? formatDistanceToNow(parseISO(msg.sent_at), { addSuffix: true })
    : "—";

  return (
    <>
      <tr
        className={`border-b transition-colors hover:bg-muted/40 ${selected ? "bg-accent/30" : ""}`}
      >
        <td className="w-8 px-3 py-3">
          <Checkbox
            checked={selected}
            onChange={(e) => onSelect(msg.correlation_id, e.target.checked)}
            aria-label={`Select ${msg.correlation_id}`}
          />
        </td>
        <td className="px-3 py-3">
          <button
            className="font-mono text-xs text-primary hover:underline"
            onClick={() => setExpanded((v) => !v)}
            title={msg.correlation_id}
          >
            {msg.correlation_id.slice(0, 12)}…
          </button>
        </td>
        <td className="px-3 py-3 text-sm" title={msg.sent_at ?? ""}>
          {sentAgo}
        </td>
        <td className="px-3 py-3">
          {msg.bouncer_reason ? (
            <Badge variant="warning">
              {msg.bouncer_reason.replace(/_/g, " ")}
            </Badge>
          ) : (
            <span className="text-muted-foreground text-xs">—</span>
          )}
        </td>
        <td className="max-w-xs px-3 py-3 text-sm text-muted-foreground">
          <span className="line-clamp-1">{msg.redacted_preview.slice(0, 80)}</span>
        </td>
        <td className="px-3 py-3 text-sm">
          {msg.approximate_receive_count > 1 && (
            <Badge variant="destructive">×{msg.approximate_receive_count}</Badge>
          )}
        </td>
        <td className="px-3 py-3">
          <div className="flex gap-1">
            <Button
              size="sm"
              variant="outline"
              onClick={() => onAction("approve", msg)}
            >
              Approve
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onAction("requeue", msg)}
            >
              Requeue
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onAction("reject", msg)}
              className="text-destructive hover:text-destructive"
            >
              Reject
            </Button>
          </div>
        </td>
      </tr>
      {expanded && (
        <tr className="border-b bg-muted/20">
          <td colSpan={7} className="px-6 py-4">
            <div className="space-y-3 text-sm">
              <div>
                <span className="font-medium">Correlation ID: </span>
                <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
                  {msg.correlation_id}
                </code>
              </div>
              <div>
                <span className="font-medium">User sub: </span>
                <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
                  {msg.user_sub}
                </code>
              </div>
              <div>
                <span className="font-medium">Session: </span>
                <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
                  {msg.session_id}
                </code>
              </div>
              {msg.entity_types.length > 0 && (
                <div className="flex items-center gap-2">
                  <span className="font-medium">Entities redacted:</span>
                  {msg.entity_types.map((et) => (
                    <Badge key={et} variant="default">
                      {et}
                    </Badge>
                  ))}
                </div>
              )}
              <div>
                <p className="mb-1 font-medium">Redacted preview:</p>
                <p className="rounded bg-muted p-2 font-mono text-xs leading-relaxed">
                  {msg.redacted_preview}
                </p>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Main view
// ---------------------------------------------------------------------------

export function Escalations() {
  const [params, setParams] = useSearchParams();
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);

  const datePreset = (params.get("date") ?? "24h") as DatePreset;
  const selectedReasons = params.getAll("reason");

  const { data, isLoading, isError, error, refetch } = useEscalations();

  const approve = useApprove();
  const reject = useReject();
  const requeue = useRequeue();
  const isActing = approve.isPending || reject.isPending || requeue.isPending;

  // Derive unique reasons from current data for filter sidebar
  const allReasons = useMemo(() => {
    const set = new Set<string>();
    for (const m of data?.messages ?? []) {
      if (m.bouncer_reason) set.add(m.bouncer_reason);
    }
    return Array.from(set).sort();
  }, [data]);

  // Client-side filtering
  const filtered = useMemo(() => {
    const msgs = data?.messages ?? [];

    const cutoff: Date | null =
      datePreset === "1h"
        ? subHours(new Date(), 1)
        : datePreset === "24h"
          ? subHours(new Date(), 24)
          : datePreset === "7d"
            ? subDays(new Date(), 7)
            : null;

    return msgs.filter((m) => {
      if (cutoff && m.sent_at && parseISO(m.sent_at) < cutoff) return false;
      if (
        selectedReasons.length > 0 &&
        (!m.bouncer_reason || !selectedReasons.includes(m.bouncer_reason))
      )
        return false;
      return true;
    });
  }, [data, datePreset, selectedReasons]);

  // Pagination (client-side, page size 25)
  const PAGE_SIZE = 25;
  const page = Math.max(1, Number(params.get("page") ?? "1"));
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const pageItems = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  function setParam(key: string, value: string | null) {
    setParams((prev) => {
      if (value === null) prev.delete(key);
      else prev.set(key, value);
      return prev;
    });
  }

  function setReasons(reasons: string[]) {
    setParams((prev) => {
      prev.delete("reason");
      for (const r of reasons) prev.append("reason", r);
      prev.set("page", "1");
      return prev;
    });
  }

  function resetFilters() {
    setParams({ date: "24h", page: "1" });
  }

  // Selection helpers
  const allPageSelected =
    pageItems.length > 0 && pageItems.every((m) => selectedIds.has(m.correlation_id));
  const somePageSelected =
    pageItems.some((m) => selectedIds.has(m.correlation_id)) && !allPageSelected;

  function toggleSelectAll(checked: boolean) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      for (const m of pageItems) {
        if (checked) next.add(m.correlation_id);
        else next.delete(m.correlation_id);
      }
      return next;
    });
  }

  function toggleSelect(id: string, checked: boolean) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  const selectedMessages = useMemo(
    () => filtered.filter((m) => selectedIds.has(m.correlation_id)),
    [filtered, selectedIds]
  );

  // Action handlers
  function openAction(type: ActionType, msg?: EscalationMessage) {
    const messages = msg ? [msg] : selectedMessages;
    if (messages.length === 0) return;
    setPendingAction({ type, messages });
  }

  const handleConfirm = useCallback(
    async (annotation: string) => {
      if (!pendingAction) return;
      const { type, messages } = pendingAction;

      for (const message of messages) {
        if (type === "approve") await approve.mutateAsync({ message });
        else if (type === "reject") await reject.mutateAsync({ message });
        else await requeue.mutateAsync({ message, annotation: annotation || "No annotation" });
      }

      setSelectedIds(new Set());
      setPendingAction(null);
    },
    [pendingAction, approve, reject, requeue]
  );

  const showLoading = isLoading && !data;

  return (
    <div className="flex h-full flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Escalation Queue</h1>
          {data && (
            <p className="text-sm text-muted-foreground">
              {data.queue_depth} message{data.queue_depth !== 1 ? "s" : ""} in
              queue
            </p>
          )}
        </div>

        {/* Bulk action toolbar — appears when ≥1 row selected */}
        {selectedMessages.length > 0 && (
          <div className="flex items-center gap-2 rounded-lg border bg-card px-3 py-2 shadow-sm">
            <span className="text-sm text-muted-foreground">
              {selectedMessages.length} selected
            </span>
            <Button
              size="sm"
              onClick={() => openAction("approve")}
              disabled={isActing}
            >
              Approve {selectedMessages.length}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => openAction("requeue")}
              disabled={isActing}
            >
              Requeue {selectedMessages.length}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => openAction("reject")}
              disabled={isActing}
              className="text-destructive hover:text-destructive"
            >
              Reject {selectedMessages.length}
            </Button>
            <button
              onClick={() => setSelectedIds(new Set())}
              className="ml-1 text-xs text-muted-foreground hover:text-foreground"
            >
              Clear
            </button>
          </div>
        )}
      </div>

      {/* Error banner */}
      {isError && (
        <ErrorBanner
          message={
            error instanceof Error
              ? error.message
              : "Couldn't load escalation queue."
          }
          onRetry={() => void refetch()}
        />
      )}

      <div className="flex gap-4">
        {/* Filter sidebar */}
        <FilterSidebar
          reasons={allReasons}
          selectedReasons={selectedReasons}
          datePreset={datePreset}
          onReasonsChange={setReasons}
          onDatePresetChange={(p) => {
            setParam("date", p);
            setParam("page", "1");
          }}
          onReset={resetFilters}
        />

        {/* Table */}
        <div className="min-w-0 flex-1 space-y-3">
          <div className="overflow-hidden rounded-lg border bg-card">
            <table className="w-full text-sm">
              <thead className="border-b bg-muted/40">
                <tr>
                  <th className="w-8 px-3 py-3 text-left">
                    <Checkbox
                      checked={allPageSelected}
                      indeterminate={somePageSelected}
                      onChange={(e) => toggleSelectAll(e.target.checked)}
                      aria-label="Select all on page"
                      disabled={pageItems.length === 0}
                    />
                  </th>
                  <th className="px-3 py-3 text-left font-medium">
                    Correlation ID
                  </th>
                  <th className="px-3 py-3 text-left font-medium">Received</th>
                  <th className="px-3 py-3 text-left font-medium">Reason</th>
                  <th className="px-3 py-3 text-left font-medium">Preview</th>
                  <th className="px-3 py-3 text-left font-medium">Retries</th>
                  <th className="px-3 py-3 text-left font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {showLoading
                  ? Array.from({ length: 5 }, (_, i) => (
                      <tr key={i} className="border-b">
                        {Array.from({ length: 7 }, (_, j) => (
                          <td key={j} className="px-3 py-3">
                            <Skeleton className="h-4 w-full" />
                          </td>
                        ))}
                      </tr>
                    ))
                  : pageItems.map((msg) => (
                      <EscalationRow
                        key={msg.correlation_id}
                        msg={msg}
                        selected={selectedIds.has(msg.correlation_id)}
                        onSelect={toggleSelect}
                        onAction={openAction}
                      />
                    ))}
              </tbody>
            </table>

            {/* Empty state */}
            {!showLoading && pageItems.length === 0 && (
              <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
                <p className="text-base font-medium">
                  No pending escalations match your filters. Nice.
                </p>
                <button
                  onClick={resetFilters}
                  className="text-sm text-primary underline-offset-4 hover:underline"
                >
                  View all (clear filters)
                </button>
              </div>
            )}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between text-sm text-muted-foreground">
              <span>
                Page {page} of {totalPages} ({filtered.length} results)
              </span>
              <div className="flex gap-1">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={page <= 1}
                  onClick={() => setParam("page", String(page - 1))}
                >
                  Previous
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={page >= totalPages}
                  onClick={() => setParam("page", String(page + 1))}
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Confirmation dialog */}
      <ConfirmDialog
        pending={pendingAction}
        onClose={() => setPendingAction(null)}
        onConfirm={(annotation) => void handleConfirm(annotation)}
        isLoading={isActing}
      />
    </div>
  );
}
