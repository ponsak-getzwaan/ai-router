import { useState } from "react";
import { Button } from "./ui/button";

interface Props {
  message: string;
  onRetry?: () => void;
  correlationId?: string;
}

export function ErrorBanner({ message, onRetry, correlationId }: Props) {
  const [expanded, setExpanded] = useState(false);

  const reportHref = (() => {
    const subject = encodeURIComponent("Evidor.ai — incident report");
    const body = encodeURIComponent(
      [
        `Timestamp: ${new Date().toISOString()}`,
        `URL: ${window.location.href}`,
        correlationId ? `Correlation ID: ${correlationId}` : "",
        `User-Agent: ${navigator.userAgent}`,
      ]
        .filter(Boolean)
        .join("\n")
    );
    return `mailto:?subject=${subject}&body=${body}`;
  })();

  return (
    <div
      role="alert"
      className="mb-4 rounded-md border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-2">
          <span aria-hidden="true">⚠</span>
          <span>{message}</span>
        </div>
        <div className="flex shrink-0 gap-2">
          {onRetry && (
            <Button variant="outline" size="sm" onClick={onRetry}>
              Retry
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? "Hide details" : "See details"}
          </Button>
          <a href={reportHref} className="contents">
            <Button variant="ghost" size="sm">
              Report incident
            </Button>
          </a>
        </div>
      </div>
      {expanded && (
        <pre className="mt-2 whitespace-pre-wrap text-xs opacity-75">
          {message}
        </pre>
      )}
    </div>
  );
}
