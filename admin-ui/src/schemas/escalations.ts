import { z } from "zod";

export const EscalationMessageSchema = z.object({
  receipt_handle: z.string(),
  message_id: z.string(),
  correlation_id: z.string(),
  user_sub: z.string(),
  session_id: z.string(),
  redacted_preview: z.string(),
  entity_types: z.array(z.string()),
  bouncer_reason: z.string().nullable(),
  sent_at: z.string().nullable(),
  approximate_receive_count: z.number(),
});

export const EscalationListSchema = z.object({
  messages: z.array(EscalationMessageSchema),
  queue_depth: z.number(),
});

export const EscalationActionSchema = z.object({
  message_id: z.string(),
  action: z.string(),
  correlation_id: z.string(),
  annotation: z.string().nullable(),
});

export type EscalationMessage = z.infer<typeof EscalationMessageSchema>;
export type EscalationList = z.infer<typeof EscalationListSchema>;
export type EscalationAction = z.infer<typeof EscalationActionSchema>;
