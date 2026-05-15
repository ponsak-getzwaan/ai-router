import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import { ServiceHealthSchema, type ServiceHealth } from "../schemas/health";

export function useServiceHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: async (): Promise<ServiceHealth> => {
      const raw = await apiFetch<unknown>("/admin/health");
      return ServiceHealthSchema.parse(raw);
    },
    refetchInterval: 10_000,
    staleTime: 8_000,
  });
}
