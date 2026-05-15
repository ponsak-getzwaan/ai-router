import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Skeleton } from "./ui/skeleton";

interface Props {
  title: string;
  value: string | null;
  unit?: string;
  alert?: boolean;
  alertIcon?: string;
  loading?: boolean;
}

export function KpiCard({ title, value, unit, alert, alertIcon, loading }: Props) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {loading ? (
          <Skeleton className="h-8 w-24" />
        ) : (
          <div className="flex items-baseline gap-1">
            <span
              className={`text-2xl font-bold tabular-nums ${alert ? "text-destructive" : "text-foreground"}`}
            >
              {value ?? "—"}
            </span>
            {unit && (
              <span className="text-sm text-muted-foreground">{unit}</span>
            )}
            {alert && alertIcon && (
              <span className="ml-1 text-sm" aria-label="Alert">
                {alertIcon}
              </span>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
