import { z } from "zod";

export const AuditRecordSchema = z.object({
  correlation_id: z.string(),
  timestamp: z.string(),
  user_sub: z.string(),
  session_id: z.string(),
  entity_types_redacted: z.array(z.string()),
  entity_count: z.number(),
  was_redacted: z.boolean(),
  bouncer_allowed: z.boolean().nullable(),
  bouncer_escalated: z.boolean().nullable(),
  intent: z.string().nullable(),
  intent_confidence: z.string().nullable(),
  vendor: z.string().nullable(),
  routing_path: z.string().nullable(),
  policy_blocked: z.boolean().nullable(),
  total_latency_ms: z.string().nullable(),
  error_type: z.string().nullable(),
});

export const AuditQuerySchema = z.object({
  records: z.array(AuditRecordSchema),
  count: z.number(),
  last_evaluated_key: z.record(z.unknown()).nullable(),
});

export type AuditRecord = z.infer<typeof AuditRecordSchema>;
export type AuditQuery = z.infer<typeof AuditQuerySchema>;
