import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";
import {
  EscalationListSchema,
  type EscalationList,
  type EscalationMessage,
} from "../schemas/escalations";

const QUERY_KEY = ["escalations"] as const;

export function useEscalations() {
  return useQuery({
    queryKey: QUERY_KEY,
    queryFn: async (): Promise<EscalationList> => {
      const raw = await apiFetch<unknown>("/admin/escalations?max_messages=10");
      return EscalationListSchema.parse(raw);
    },
    refetchInterval: (query) =>
      document.visibilityState === "visible" && !query.state.error
        ? 30_000
        : false,
    staleTime: 25_000,
  });
}

function removeFromCache(
  prev: EscalationList | undefined,
  correlationId: string
): EscalationList | undefined {
  if (!prev) return prev;
  return {
    ...prev,
    messages: prev.messages.filter((m) => m.correlation_id !== correlationId),
    queue_depth: Math.max(0, prev.queue_depth - 1),
  };
}

interface ApproveVars {
  message: EscalationMessage;
}

export function useApprove() {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: ({ message }: ApproveVars) =>
      apiFetch(`/admin/escalations/${message.correlation_id}/approve`, {
        method: "POST",
        body: JSON.stringify({ receipt_handle: message.receipt_handle }),
      }),

    onMutate: async ({ message }) => {
      await qc.cancelQueries({ queryKey: QUERY_KEY });
      const prev = qc.getQueryData<EscalationList>(QUERY_KEY);
      qc.setQueryData<EscalationList>(
        QUERY_KEY,
        removeFromCache(prev, message.correlation_id)
      );
      return { prev };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(QUERY_KEY, ctx.prev);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
}

interface RejectVars {
  message: EscalationMessage;
}

export function useReject() {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: ({ message }: RejectVars) =>
      apiFetch(`/admin/escalations/${message.correlation_id}/reject`, {
        method: "POST",
        body: JSON.stringify({ receipt_handle: message.receipt_handle }),
      }),

    onMutate: async ({ message }) => {
      await qc.cancelQueries({ queryKey: QUERY_KEY });
      const prev = qc.getQueryData<EscalationList>(QUERY_KEY);
      qc.setQueryData<EscalationList>(
        QUERY_KEY,
        removeFromCache(prev, message.correlation_id)
      );
      return { prev };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(QUERY_KEY, ctx.prev);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
}

interface RequeueVars {
  message: EscalationMessage;
  annotation: string;
}

export function useRequeue() {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: ({ message, annotation }: RequeueVars) =>
      apiFetch(`/admin/escalations/${message.correlation_id}/requeue`, {
        method: "POST",
        body: JSON.stringify({
          receipt_handle: message.receipt_handle,
          annotation,
        }),
      }),

    onMutate: async ({ message }) => {
      await qc.cancelQueries({ queryKey: QUERY_KEY });
      const prev = qc.getQueryData<EscalationList>(QUERY_KEY);
      qc.setQueryData<EscalationList>(
        QUERY_KEY,
        removeFromCache(prev, message.correlation_id)
      );
      return { prev };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(QUERY_KEY, ctx.prev);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
}
