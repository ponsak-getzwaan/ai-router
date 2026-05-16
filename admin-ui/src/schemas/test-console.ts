import { z } from "zod";

export const INTENT_DOMAINS = [
  "code_assistance",
  "general_qa",
  "simple_transactional",
  "out_of_scope",
  "ambiguous",
] as const;

export type IntentDomain = (typeof INTENT_DOMAINS)[number];

export const TestConsoleRequestSchema = z.object({
  redacted_message: z.string().min(1).max(4096),
  dry_run: z.boolean().default(true),
  user_sub: z.string().min(1).max(128).default("admin-test-user"),
  session_id: z.string().min(1).max(128).default("admin-test-session"),
  intent_override: z.string().nullable().optional(),
});

export const TestConsoleLayerResultSchema = z.object({
  layer: z.string(),
  latency_ms: z.number(),
  outcome: z.record(z.unknown()),
});

export const TestConsoleResponseSchema = z.object({
  correlation_id: z.string(),
  dry_run: z.boolean(),
  layers: z.array(TestConsoleLayerResultSchema),
  final_vendor: z.string().nullable(),
  total_latency_ms: z.number(),
  error: z.string().nullable(),
});

export type TestConsoleRequest = z.infer<typeof TestConsoleRequestSchema>;
export type TestConsoleLayerResult = z.infer<typeof TestConsoleLayerResultSchema>;
export type TestConsoleResponse = z.infer<typeof TestConsoleResponseSchema>;
