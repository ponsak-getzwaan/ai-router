import { z } from "zod";

export const ServiceHealthSchema = z.object({
  status: z.enum(["ok", "degraded", "unavailable"]),
  dynamodb: z.string(),
  redis: z.string(),
  sqs: z.string(),
  checked_at: z.string(),
});

export type ServiceHealth = z.infer<typeof ServiceHealthSchema>;
