import { z } from "zod";

export const RoutingRuleSchema = z.object({
  intent: z.string(),
  vendor: z.string(),
  fallback: z.string().nullable(),
  description: z.string().nullable(),
});

export const RoutingRuleUpdateSchema = z.object({
  vendor: z.string().min(1, "Vendor is required").max(200),
  fallback: z.string().max(200).nullable().optional(),
  description: z.string().max(500).nullable().optional(),
});

export type RoutingRule = z.infer<typeof RoutingRuleSchema>;
export type RoutingRuleUpdate = z.infer<typeof RoutingRuleUpdateSchema>;
