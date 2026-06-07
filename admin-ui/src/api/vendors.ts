import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { apiFetch } from "./client";

const VendorModelSchema = z.object({
  id: z.string(),
  label: z.string(),
});

const VendorGroupSchema = z.object({
  region: z.string(),
  region_label: z.string(),
  note: z.string(),
  models: z.array(VendorModelSchema),
});

export const VendorGroupsSchema = z.array(VendorGroupSchema);

export type VendorModel = z.infer<typeof VendorModelSchema>;
export type VendorGroup = z.infer<typeof VendorGroupSchema>;

export function useVendors() {
  return useQuery({
    queryKey: ["vendors"],
    queryFn: async (): Promise<VendorGroup[]> => {
      const raw = await apiFetch<unknown>("/admin/api/vendors");
      return VendorGroupsSchema.parse(raw);
    },
    staleTime: 5 * 60_000, // profiles don't change often — cache for 5 min
  });
}
