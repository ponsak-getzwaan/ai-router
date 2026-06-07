import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";
import {
  RoutingRuleSchema,
  type RoutingRule,
  type RoutingRuleUpdate,
} from "../schemas/routing-rules";
import { z } from "zod";

const LIST_KEY = ["routing-rules"] as const;
const ruleKey = (intent: string) => ["routing-rules", intent] as const;

export function useRoutingRules() {
  return useQuery({
    queryKey: LIST_KEY,
    queryFn: async (): Promise<RoutingRule[]> => {
      const raw = await apiFetch<unknown>("/admin/api/routing-rules");
      return z.array(RoutingRuleSchema).parse(raw);
    },
    staleTime: 60_000,
  });
}

export function useRoutingRule(intent: string) {
  return useQuery({
    queryKey: ruleKey(intent),
    queryFn: async (): Promise<RoutingRule> => {
      const raw = await apiFetch<unknown>(`/admin/routing-rules/${encodeURIComponent(intent)}`);
      return RoutingRuleSchema.parse(raw);
    },
    staleTime: 60_000,
  });
}

export function useUpdateRoutingRule(intent: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: RoutingRuleUpdate) =>
      apiFetch<RoutingRule>(`/admin/routing-rules/${encodeURIComponent(intent)}`, {
        method: "PUT",
        body: JSON.stringify({
          vendor: body.vendor,
          fallback: body.fallback ?? null,
          description: body.description ?? null,
        }),
      }),
    onSuccess: (updated) => {
      qc.setQueryData(ruleKey(intent), updated);
      void qc.invalidateQueries({ queryKey: LIST_KEY });
    },
  });
}
