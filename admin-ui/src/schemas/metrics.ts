import { z } from "zod";

export const LatencyPercentilesSchema = z.object({
  p50: z.number().nullable(),
  p99: z.number().nullable(),
  p999: z.number().nullable(),
});

export const PipelineMetricsSchema = z.object({
  period_minutes: z.number(),
  total_requests: z.number(),
  error_rate_pct: z.number().nullable(),
  escalation_rate_pct: z.number().nullable(),
  latency_ms: LatencyPercentilesSchema,
});

export const BouncerMetricsSchema = z.object({
  period_minutes: z.number(),
  total: z.number(),
  passed: z.number(),
  rejected: z.number(),
  escalated: z.number(),
  timed_out: z.number(),
  errors: z.number(),
  pass_rate_pct: z.number().nullable(),
  avg_confidence: z.number().nullable(),
});

export const ClassifierMetricsSchema = z.object({
  period_minutes: z.number(),
  total: z.number(),
  fast_path: z.number(),
  deep_path: z.number(),
  escalated: z.number(),
  intent_counts: z.record(z.string(), z.number()),
});

export const RedactionMetricsSchema = z.object({
  period_minutes: z.number(),
  total_processed: z.number(),
  total_entities_redacted: z.number(),
  entity_type_counts: z.record(z.string(), z.number()),
});

export const StrategistMetricsSchema = z.object({
  period_minutes: z.number(),
  total: z.number(),
  vendor_counts: z.record(z.string(), z.number()),
  policy_blocked: z.number(),
  fallback_used: z.number(),
  deterministic_route: z.number(),
  arbitration_route: z.number(),
  errors: z.number(),
});

export type PipelineMetrics = z.infer<typeof PipelineMetricsSchema>;
export type BouncerMetrics = z.infer<typeof BouncerMetricsSchema>;
export type ClassifierMetrics = z.infer<typeof ClassifierMetricsSchema>;
export type RedactionMetrics = z.infer<typeof RedactionMetricsSchema>;
export type StrategistMetrics = z.infer<typeof StrategistMetricsSchema>;
