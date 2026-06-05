import { z } from "zod";

export const TestConsoleRequestSchema = z.object({
  redacted_message: z.string().min(1).max(4096),
  user_sub: z.string().min(1).max(128).default("admin-test-user"),
  session_id: z.string().min(1).max(128).default("admin-test-session"),
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
  timed_out: z.boolean(),
  error: z.string().nullable(),
  response: z.string().nullable().optional(),
});

export type TestConsoleRequest = z.infer<typeof TestConsoleRequestSchema>;
export type TestConsoleLayerResult = z.infer<typeof TestConsoleLayerResultSchema>;
export type TestConsoleResponse = z.infer<typeof TestConsoleResponseSchema>;
