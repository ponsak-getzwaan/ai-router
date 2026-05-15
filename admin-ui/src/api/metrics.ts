import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import {
  PipelineMetricsSchema,
  BouncerMetricsSchema,
  ClassifierMetricsSchema,
  StrategistMetricsSchema,
  type PipelineMetrics,
  type BouncerMetrics,
  type ClassifierMetrics,
  type StrategistMetrics,
} from "../schemas/metrics";

export type TimeWindow = "1h" | "24h" | "7d";

function windowToMinutes(w: TimeWindow): number {
  // Backend max is 1440 min (24h). 7d is capped — backend needs time-series
  // support to return meaningful data beyond one day.
  return w === "1h" ? 60 : 1440;
}

export function usePipelineMetrics(window: TimeWindow) {
  const periodMinutes = windowToMinutes(window);
  return useQuery({
    queryKey: ["metrics", "pipeline", periodMinutes],
    queryFn: async (): Promise<PipelineMetrics> => {
      const raw = await apiFetch<unknown>(
        `/admin/metrics/pipeline?period_minutes=${periodMinutes}`
      );
      return PipelineMetricsSchema.parse(raw);
    },
    refetchInterval: 30_000,
    staleTime: 25_000,
  });
}

export function useBouncerMetrics(window: TimeWindow) {
  const periodMinutes = windowToMinutes(window);
  return useQuery({
    queryKey: ["metrics", "bouncer", periodMinutes],
    queryFn: async (): Promise<BouncerMetrics> => {
      const raw = await apiFetch<unknown>(
        `/admin/metrics/bouncer?period_minutes=${periodMinutes}`
      );
      return BouncerMetricsSchema.parse(raw);
    },
    refetchInterval: 30_000,
    staleTime: 25_000,
  });
}

export function useClassifierMetrics(window: TimeWindow) {
  const periodMinutes = windowToMinutes(window);
  return useQuery({
    queryKey: ["metrics", "classifier", periodMinutes],
    queryFn: async (): Promise<ClassifierMetrics> => {
      const raw = await apiFetch<unknown>(
        `/admin/metrics/classifier?period_minutes=${periodMinutes}`
      );
      return ClassifierMetricsSchema.parse(raw);
    },
    refetchInterval: 30_000,
    staleTime: 25_000,
  });
}

export function useStrategistMetrics(window: TimeWindow) {
  const periodMinutes = windowToMinutes(window);
  return useQuery({
    queryKey: ["metrics", "strategist", periodMinutes],
    queryFn: async (): Promise<StrategistMetrics> => {
      const raw = await apiFetch<unknown>(
        `/admin/metrics/strategist?period_minutes=${periodMinutes}`
      );
      return StrategistMetricsSchema.parse(raw);
    },
    refetchInterval: 30_000,
    staleTime: 25_000,
  });
}
