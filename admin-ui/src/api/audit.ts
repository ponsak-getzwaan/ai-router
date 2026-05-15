import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import { AuditQuerySchema, type AuditQuery } from "../schemas/audit";

interface AuditParams {
  correlationId?: string | undefined;
  limit?: number | undefined;
  cursor?: string | undefined;
}

function auditKey(params: AuditParams) {
  return ["audit", params] as const;
}

export function useAuditLog(params: AuditParams) {
  return useQuery({
    queryKey: auditKey(params),
    queryFn: async (): Promise<AuditQuery> => {
      const qs = new URLSearchParams();
      if (params.correlationId) qs.set("correlation_id", params.correlationId);
      if (params.limit) qs.set("limit", String(params.limit));
      if (params.cursor) qs.set("cursor", params.cursor);
      const raw = await apiFetch<unknown>(`/admin/audit?${qs.toString()}`);
      return AuditQuerySchema.parse(raw);
    },
    staleTime: 30_000,
  });
}

export function encodeCursor(lastKey: Record<string, unknown> | null | undefined): string | undefined {
  if (!lastKey) return undefined;
  return btoa(JSON.stringify(lastKey));
}
