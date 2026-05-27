import { useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { useForm } from "react-hook-form";
import { useRoutingRule, useUpdateRoutingRule } from "../api/routing-rules";
import { RoutingRuleUpdateSchema, type RoutingRuleUpdate, type RoutingRule } from "../schemas/routing-rules";
import { ErrorBanner } from "../components/ErrorBanner";
import { Spinner } from "../components/Spinner";
import { Button } from "../components/ui/button";
import { Label } from "../components/ui/label";
import { NativeSelect } from "../components/ui/select-native";
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
// Approved inference profiles grouped by region
// APAC: verified active in ap-southeast-1 (2026-05-27)
// US:   verified active in us-east-1 (2026-05-27) — ~170ms extra latency
//       Note: US-region calls process data outside SG. Confirm compliance
//       before assigning US models to SG-user intents.
// ---------------------------------------------------------------------------

interface VendorOption { id: string; label: string }
interface VendorGroup  { region: string; note: string; options: VendorOption[] }

const VENDOR_GROUPS: VendorGroup[] = [
  {
    region: "APAC — ap-southeast-1",
    note: "Singapore region · data residency compliant",
    options: [
      { id: "apac.anthropic.claude-sonnet-4-20250514-v1:0",   label: "Claude Sonnet 4 (latest)" },
      { id: "apac.anthropic.claude-3-5-sonnet-20241022-v2:0", label: "Claude 3.5 Sonnet v2" },
      { id: "apac.anthropic.claude-3-5-sonnet-20240620-v1:0", label: "Claude 3.5 Sonnet v1" },
      { id: "apac.anthropic.claude-3-haiku-20240307-v1:0",    label: "Claude 3 Haiku" },
      { id: "apac.amazon.nova-pro-v1:0",                      label: "Amazon Nova Pro" },
      { id: "apac.amazon.nova-lite-v1:0",                     label: "Amazon Nova Lite" },
      { id: "apac.amazon.nova-micro-v1:0",                    label: "Amazon Nova Micro" },
    ],
  },
  {
    region: "US — us-east-1 (+~170ms latency)",
    note: "Data processed outside SG — verify compliance before use",
    options: [
      { id: "us.meta.llama4-maverick-17b-instruct-v1:0",  label: "Meta Llama 4 Maverick 17B" },
      { id: "us.meta.llama4-scout-17b-instruct-v1:0",     label: "Meta Llama 4 Scout 17B" },
      { id: "us.meta.llama3-3-70b-instruct-v1:0",         label: "Meta Llama 3.3 70B" },
      { id: "us.mistral.pixtral-large-2502-v1:0",         label: "Mistral Pixtral Large" },
      { id: "us.amazon.nova-premier-v1:0",                label: "Amazon Nova Premier" },
      { id: "us.deepseek.r1-v1:0",                        label: "DeepSeek R1" },
    ],
  },
];

// ---------------------------------------------------------------------------
// Diff display
// ---------------------------------------------------------------------------

interface Field {
  label: string;
  before: string | null;
  after: string | null;
}

function DiffRow({ field }: { field: Field }) {
  const changed = field.before !== field.after;
  return (
    <div className={`rounded-md p-3 ${changed ? "bg-amber-50 ring-1 ring-amber-200" : "bg-muted/30"}`}>
      <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {field.label}
      </p>
      {changed ? (
        <div className="space-y-1 font-mono text-xs">
          <div className="rounded bg-red-100 px-2 py-1 text-red-800 line-through">
            {field.before ?? "(none)"}
          </div>
          <div className="rounded bg-green-100 px-2 py-1 text-green-800">
            {field.after ?? "(none)"}
          </div>
        </div>
      ) : (
        <p className="font-mono text-xs text-muted-foreground">
          {field.before ?? "(none)"} — unchanged
        </p>
      )}
    </div>
  );
}

function buildDiff(before: RoutingRule, after: RoutingRuleUpdate): Field[] {
  return [
    {
      label: "Primary vendor",
      before: before.vendor,
      after: after.vendor,
    },
    {
      label: "Fallback vendor",
      before: before.fallback ?? null,
      after: after.fallback ?? null,
    },
    {
      label: "Description",
      before: before.description ?? null,
      after: after.description ?? null,
    },
  ];
}

// ---------------------------------------------------------------------------
// Confirmation dialog
// ---------------------------------------------------------------------------

interface ConfirmProps {
  open: boolean;
  intent: string;
  diff: Field[];
  isPending: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

function ConfirmDialog({ open, intent, diff, isPending, onConfirm, onClose }: ConfirmProps) {
  const changed = diff.filter((f) => f.before !== f.after);

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Review changes to "{intent}"</DialogTitle>
          <DialogDescription>
            {changed.length === 0
              ? "No fields have changed."
              : `${changed.length} field${changed.length > 1 ? "s" : ""} will change. This takes effect on the next request.`}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2 py-2">
          {diff.map((field) => (
            <DiffRow key={field.label} field={field} />
          ))}
        </div>

        {/* Two-operator notice */}
        <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          <strong>Two-operator sign-off required in production.</strong>{" "}
          Cross-session enforcement needs a backend pending-review table. Until
          then, confirm that a second operator has reviewed this diff out-of-band
          before applying.
        </div>

        <DialogFooter className="gap-2 pt-2">
          <DialogClose asChild>
            <Button variant="outline" size="sm" disabled={isPending}>
              Cancel
            </Button>
          </DialogClose>
          <Button
            size="sm"
            onClick={onConfirm}
            disabled={isPending || changed.length === 0}
          >
            {isPending ? "Applying…" : "Approve and apply"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Form
// ---------------------------------------------------------------------------

interface FormValues {
  vendor: string;
  fallback: string;
  description: string;
}

interface EditorFormProps {
  rule: RoutingRule;
  intent: string;
}

function EditorForm({ rule, intent }: EditorFormProps) {
  const navigate = useNavigate();
  const update = useUpdateRoutingRule(intent);

  const [pendingDraft, setPendingDraft] = useState<RoutingRuleUpdate | null>(null);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [succeeded, setSucceeded] = useState(false);

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isDirty },
  } = useForm<FormValues>({
    defaultValues: {
      vendor: rule.vendor,
      fallback: rule.fallback ?? "",
      description: rule.description ?? "",
    },
  });

  const watchVendor = watch("vendor");
  const watchFallback = watch("fallback");

  function onSubmit(values: FormValues) {
    const parsed = RoutingRuleUpdateSchema.safeParse({
      vendor: values.vendor.trim(),
      fallback: values.fallback.trim() || null,
      description: values.description.trim() || null,
    });
    if (!parsed.success) return; // field-level errors from register catch this first
    setPendingDraft(parsed.data);
    setApplyError(null);
  }

  async function applyDraft() {
    if (!pendingDraft) return;
    setApplyError(null);
    try {
      await update.mutateAsync(pendingDraft);
      setSucceeded(true);
      setPendingDraft(null);
    } catch (err) {
      setApplyError(err instanceof Error ? err.message : "Apply failed");
      setPendingDraft(null);
    }
  }

  const diff = pendingDraft ? buildDiff(rule, pendingDraft) : [];

  if (succeeded) {
    return (
      <div className="rounded-lg border bg-card p-8 text-center">
        <p className="text-lg font-semibold text-green-700">Rule updated.</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Changes take effect on the next request (short TTL cache on Strategist).
        </p>
        <div className="mt-4 flex justify-center gap-2">
          <Button variant="outline" onClick={() => navigate("/admin/routing-rules")}>
            Back to list
          </Button>
        </div>
      </div>
    );
  }

  return (
    <>
      {applyError && (
        <ErrorBanner message={applyError} onRetry={() => setPendingDraft(pendingDraft)} />
      )}

      <form onSubmit={(e) => void handleSubmit(onSubmit)(e)} className="space-y-5">
        {/* Vendor */}
        <div className="space-y-1.5">
          <Label htmlFor="vendor">
            Primary vendor <span className="text-destructive">*</span>
          </Label>
          <NativeSelect
            id="vendor"
            {...register("vendor", { required: "Required" })}
          >
            {VENDOR_GROUPS.map((group) => (
              <optgroup key={group.region} label={`${group.region} — ${group.note}`}>
                {group.options.map((opt) => (
                  <option key={opt.id} value={opt.id}>
                    {opt.label} — {opt.id}
                  </option>
                ))}
              </optgroup>
            ))}
          </NativeSelect>
          {errors.vendor && (
            <p className="text-xs text-destructive">{errors.vendor.message}</p>
          )}
          {watchVendor?.startsWith("us.") && (
            <p className="text-xs text-amber-700 font-medium">
              US-region model selected — data is processed outside Singapore. Confirm compliance before applying.
            </p>
          )}
        </div>

        {/* Fallback */}
        <div className="space-y-1.5">
          <Label htmlFor="fallback">Fallback vendor</Label>
          <NativeSelect
            id="fallback"
            {...register("fallback")}
          >
            <option value="">— no fallback (escalate to human review) —</option>
            {VENDOR_GROUPS.map((group) => (
              <optgroup key={group.region} label={`${group.region} — ${group.note}`}>
                {group.options.map((opt) => (
                  <option key={opt.id} value={opt.id}>
                    {opt.label} — {opt.id}
                  </option>
                ))}
              </optgroup>
            ))}
          </NativeSelect>
          {errors.fallback && (
            <p className="text-xs text-destructive">{errors.fallback.message}</p>
          )}
          {watchFallback?.startsWith("us.") && (
            <p className="text-xs text-amber-700 font-medium">
              US-region model selected — data is processed outside Singapore. Confirm compliance before applying.
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            Used when the primary vendor fails its health check.
          </p>
        </div>

        {/* Description */}
        <div className="space-y-1.5">
          <Label htmlFor="description">Description</Label>
          <Textarea
            id="description"
            rows={2}
            placeholder="Human-readable note about this rule"
            {...register("description")}
          />
          {errors.description && (
            <p className="text-xs text-destructive">{errors.description.message}</p>
          )}
        </div>

        <div className="flex items-center gap-3 border-t pt-4">
          <Button type="submit" disabled={!isDirty}>
            Review changes
          </Button>
          <Button
            type="button"
            variant="ghost"
            onClick={() => navigate("/admin/routing-rules")}
          >
            Cancel
          </Button>
          {!isDirty && (
            <span className="text-xs text-muted-foreground">
              No changes to review.
            </span>
          )}
        </div>
      </form>

      <ConfirmDialog
        open={pendingDraft !== null}
        intent={intent}
        diff={diff}
        isPending={update.isPending}
        onConfirm={() => void applyDraft()}
        onClose={() => setPendingDraft(null)}
      />
    </>
  );
}

// ---------------------------------------------------------------------------
// Route component
// ---------------------------------------------------------------------------

export function RoutingRuleEditor() {
  const { intent } = useParams<{ intent: string }>();
  const decoded = intent ? decodeURIComponent(intent) : "";

  const { data: rule, isLoading, isError, error, refetch } = useRoutingRule(decoded);

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1.5 text-sm text-muted-foreground">
        <Link
          to="/admin/routing-rules"
          className="hover:text-foreground hover:underline underline-offset-4"
        >
          Routing Rules
        </Link>
        <span>/</span>
        <span className="font-mono text-foreground">{decoded}</span>
      </nav>

      <div>
        <h1 className="text-xl font-semibold">Edit rule: {decoded}</h1>
        <p className="text-sm text-muted-foreground">
          Changes affect live routing immediately after apply.
        </p>
      </div>

      {/* High-stakes banner */}
      <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
        <strong>Production routing rule.</strong> A wrong vendor ID will cause
        all requests classified as "{decoded}" to fail or fall through to the
        fallback chain. Verify the inference profile ID in the Bedrock console
        before saving.
      </div>

      {isLoading && !rule && (
        <div className="flex items-center gap-2 text-muted-foreground">
          <Spinner className="h-4 w-4" />
          <span className="text-sm">Loading rule…</span>
        </div>
      )}

      {isError && (
        <ErrorBanner
          message={error instanceof Error ? error.message : "Couldn't load rule."}
          onRetry={() => void refetch()}
        />
      )}

      {rule && (
        <div className="rounded-lg border bg-card p-6">
          <EditorForm rule={rule} intent={decoded} />
        </div>
      )}
    </div>
  );
}
