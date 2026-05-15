import { useNavigate } from "react-router-dom";
import { useRoutingRules } from "../api/routing-rules";
import { ErrorBanner } from "../components/ErrorBanner";
import { Skeleton } from "../components/ui/skeleton";
import type { RoutingRule } from "../schemas/routing-rules";

function VendorCell({ value }: { value: string | null }) {
  if (!value) return <span className="text-muted-foreground">—</span>;
  // Show a shortened form of the long inference profile ID
  const short = value.split(".").pop()?.replace(/-v\d+:\d+$/, "") ?? value;
  return (
    <span title={value} className="font-mono text-xs">
      {short}
    </span>
  );
}

function RuleRow({ rule, onClick }: { rule: RoutingRule; onClick: () => void }) {
  return (
    <tr
      className="cursor-pointer border-b transition-colors hover:bg-muted/40"
      onClick={onClick}
    >
      <td className="px-4 py-3 font-mono text-sm font-medium">
        {rule.intent}
      </td>
      <td className="px-4 py-3">
        <VendorCell value={rule.vendor} />
      </td>
      <td className="px-4 py-3">
        <VendorCell value={rule.fallback} />
      </td>
      <td className="px-4 py-3 text-sm text-muted-foreground">
        {rule.description ?? <span className="italic">No description</span>}
      </td>
      <td className="px-4 py-3 text-right">
        <span className="text-xs text-primary">Edit →</span>
      </td>
    </tr>
  );
}

export function RoutingRules() {
  const navigate = useNavigate();
  const { data, isLoading, isError, error, refetch } = useRoutingRules();

  const loading = isLoading && !data;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Routing Rules</h1>
        <p className="text-sm text-muted-foreground">
          Intent → vendor mappings read by the Strategist on every request.
          Changes take effect on the next request (short TTL cache).
        </p>
      </div>

      {/* Two-operator notice */}
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
        <strong>High-stakes write surface.</strong> Editing a rule affects live
        production routing. A diff review step is required before any change is
        applied. Cross-session two-operator enforcement requires a backend
        pending-review table (not yet implemented).
      </div>

      {isError && (
        <ErrorBanner
          message={
            error instanceof Error ? error.message : "Couldn't load routing rules."
          }
          onRetry={() => void refetch()}
        />
      )}

      <div className="overflow-hidden rounded-lg border bg-card">
        <table className="w-full text-sm">
          <thead className="border-b bg-muted/40">
            <tr>
              <th className="px-4 py-3 text-left font-medium">Intent key</th>
              <th className="px-4 py-3 text-left font-medium">Primary vendor</th>
              <th className="px-4 py-3 text-left font-medium">Fallback vendor</th>
              <th className="px-4 py-3 text-left font-medium">Description</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody>
            {loading
              ? Array.from({ length: 4 }, (_, i) => (
                  <tr key={i} className="border-b">
                    {Array.from({ length: 5 }, (_, j) => (
                      <td key={j} className="px-4 py-3">
                        <Skeleton className="h-4 w-full" />
                      </td>
                    ))}
                  </tr>
                ))
              : (data ?? []).map((rule) => (
                  <RuleRow
                    key={rule.intent}
                    rule={rule}
                    onClick={() =>
                      navigate(
                        `/admin/routing-rules/${encodeURIComponent(rule.intent)}`
                      )
                    }
                  />
                ))}
          </tbody>
        </table>

        {!loading && (data ?? []).length === 0 && (
          <div className="flex flex-col items-center justify-center gap-1 py-16 text-center">
            <p className="font-medium">No routing rules configured.</p>
            <p className="text-sm text-muted-foreground">
              Rules are seeded by the Terraform bootstrap script.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
