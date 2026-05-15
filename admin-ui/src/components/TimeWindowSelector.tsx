import { useSearchParams } from "react-router-dom";
import type { TimeWindow } from "../api/metrics";
import { cn } from "../lib/utils";

const WINDOWS: { label: string; value: TimeWindow }[] = [
  { label: "1h", value: "1h" },
  { label: "24h", value: "24h" },
  { label: "7d", value: "7d" },
];

export function TimeWindowSelector() {
  const [params, setParams] = useSearchParams();
  const current = (params.get("window") ?? "1h") as TimeWindow;

  function select(w: TimeWindow) {
    setParams((prev) => {
      prev.set("window", w);
      return prev;
    });
  }

  return (
    <div className="flex gap-1 rounded-lg border bg-muted p-1" role="group" aria-label="Time window">
      {WINDOWS.map(({ label, value }) => (
        <button
          key={value}
          onClick={() => select(value)}
          aria-pressed={current === value}
          className={cn(
            "rounded-md px-3 py-1 text-sm font-medium transition-colors",
            current === value
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
