import { useMutation } from "@tanstack/react-query";
import { apiFetch } from "./client";
import { TestConsoleResponseSchema, type TestConsoleRequest, type TestConsoleResponse } from "../schemas/test-console";

export function useRunTrace() {
  return useMutation({
    mutationFn: async (body: TestConsoleRequest): Promise<TestConsoleResponse> => {
      const raw = await apiFetch<unknown>("/admin/test-console", {
        method: "POST",
        body: JSON.stringify(body),
      });
      return TestConsoleResponseSchema.parse(raw);
    },
  });
}
