import { formatDistanceToNow } from "date-fns";
import type { ServiceHealth } from "../schemas/health";
import { Skeleton } from "./ui/skeleton";

const LAYERS = [
  { name: "Orchestrator", key: null },
  { name: "Bouncer", key: null },
  { name: "Classifier", key: null },
  { name: "Strategist", key: null },
  { name: "Adapter", key: null },
  { name: "DynamoDB", key: "dynamodb" as const },
  { name: "Redis", key: "redis" as const },
  { name: "SQS", key: "sqs" as const },
] satisfies Array<{
  name: string;
  key: keyof Pick<ServiceHealth, "dynamodb" | "redis" | "sqs"> | null;
}>;

type Status = "ok" | "degraded" | "unavailable" | "not_configured" | "unknown";

function StatusDot({ status }: { status: Status }) {
  const colours: Record<Status, string> = {
    ok: "bg-green-500",
    degraded: "bg-yellow-500",
    unavailable: "bg-red-500",
    not_configured: "bg-gray-400",
    unknown: "bg-gray-300",
  };
  const labels: Record<Status, string> = {
    ok: "Healthy",
    degraded: "Degraded",
    unavailable: "Unavailable",
    not_configured: "Not configured",
    unknown: "Unknown",
  };
  return (
    <span
      className={`inline-block h-2.5 w-2.5 rounded-full ${colours[status]}`}
      aria-label={labels[status]}
      title={labels[status]}
    />
  );
}

interface Props {
  health: ServiceHealth | undefined;
  loading: boolean;
  checkedAt?: string | undefined;
}

export function LayerStatusSidebar({ health, loading, checkedAt }: Props) {
  const resolveStatus = (
    key: keyof Pick<ServiceHealth, "dynamodb" | "redis" | "sqs"> | null
  ): Status => {
    if (!health) return "unknown";
    if (!key) return health.status === "ok" ? "ok" : "degraded";
    const val = health[key];
    if (val === "ok") return "ok";
    if (val === "not_configured") return "not_configured";
    if (val === "unavailable") return "unavailable";
    return "unknown";
  };

  const ago = checkedAt
    ? formatDistanceToNow(new Date(checkedAt), { addSuffix: true })
    : null;

  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-medium">Layer status</h3>
        {ago && (
          <span className="text-xs text-muted-foreground" title={checkedAt}>
            Updated {ago}
          </span>
        )}
      </div>
      <ul className="space-y-2">
        {LAYERS.map(({ name, key }) =>
          loading ? (
            <li key={name} className="flex items-center gap-2">
              <Skeleton className="h-2.5 w-2.5 rounded-full" />
              <Skeleton className="h-4 w-24" />
            </li>
          ) : (
            <li key={name} className="flex items-center gap-2 text-sm">
              <StatusDot status={resolveStatus(key)} />
              <span>{name}</span>
            </li>
          )
        )}
      </ul>
    </div>
  );
}
