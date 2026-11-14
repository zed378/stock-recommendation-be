import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useI18n } from "@/i18n/context";
import { useToast } from "@/components/toastContext";
import { idempotencyKey, traderApi, unwrap, TraderError } from "@/trader/client";
import type { KillResult } from "@/trader/types";

/**
 * What the API requires the confirmation field to say, word for word.
 *
 * The screen asks the person to type FLATTEN, which is easier to type and to
 * mean; these strings are the API's own restatement of the effect, sent so that
 * the guard is in the server and not only in this dialog (docs/07-API-CONTRACTS/00).
 */
const CONFIRMATION = {
  HALT: undefined,
  CANCEL: "CANCEL ALL OPEN ORDERS",
  FLATTEN: "SELL ALL HOLDINGS AT MARKET",
} as const;

export type Tier = keyof typeof CONFIRMATION;

/** A mutation reports what the Trader says happened. It never assumes success. */
function useAfterMutation() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: ["trader"] });
}

export function useKill() {
  const { t } = useI18n();
  const toast = useToast();
  const refresh = useAfterMutation();
  return useMutation<KillResult, TraderError, { tier: Tier; stepUp?: string }>({
    mutationFn: async ({ tier, stepUp }) => {
      const out = await unwrap<KillResult>(
        traderApi.POST("/trader/v1/kill", {
          params: {
            header: {
              "Idempotency-Key": idempotencyKey(),
              ...(stepUp ? { "x-step-up": stepUp } : {}),
            },
          },
          body: { tier, confirmation: CONFIRMATION[tier] },
        }),
      );
      return out.data;
    },
    onSuccess: (result) => toast.show({ title: t("trader.kill.done", { tier: result.tier }), tone: "success" }),
    // Refetch either way: after a failed kill the true state is exactly what the
    // person needs to see next.
    onSettled: () => void refresh(),
  });
}

export function useResume() {
  const { t } = useI18n();
  const toast = useToast();
  const refresh = useAfterMutation();
  return useMutation<unknown, TraderError, { note: string }>({
    mutationFn: ({ note }) =>
      unwrap(
        traderApi.POST("/trader/v1/resume", {
          params: { header: { "Idempotency-Key": idempotencyKey() } },
          body: { note },
        }),
      ),
    onSuccess: () => toast.show({ title: t("trader.resume.done"), tone: "success" }),
    onSettled: () => void refresh(),
  });
}

export function useAcknowledge() {
  const refresh = useAfterMutation();
  return useMutation<unknown, TraderError, { id: string }>({
    mutationFn: ({ id }) =>
      unwrap(
        traderApi.POST("/trader/v1/events/{event_id}/ack", {
          params: { path: { event_id: id }, header: { "Idempotency-Key": idempotencyKey() } },
        }),
      ),
    onSettled: () => void refresh(),
  });
}

export interface ApproveResult {
  state: string;
  sent: boolean;
  detail: string;
  already_decided: boolean;
}

export function useDecide() {
  const refresh = useAfterMutation();
  return useMutation<
    ApproveResult,
    TraderError,
    { identity: string; intentHash: string; decision: "approve" | "deny"; reason?: string }
  >({
    mutationFn: async ({ identity, intentHash, decision, reason }) => {
      const header = { "Idempotency-Key": idempotencyKey() };
      if (decision === "approve") {
        const out = await unwrap<ApproveResult>(
          traderApi.POST("/trader/v1/intents/{identity}/approve", {
            params: { path: { identity }, header },
            body: { intent_hash: intentHash },
          }),
        );
        return out.data;
      }
      const out = await unwrap<{ state: string; already_decided: boolean }>(
        traderApi.POST("/trader/v1/intents/{identity}/deny", {
          params: { path: { identity }, header },
          body: { reason: reason || null },
        }),
      );
      return { ...out.data, sent: false, detail: "" };
    },
    onSettled: () => void refresh(),
  });
}

export function usePromote() {
  const refresh = useAfterMutation();
  return useMutation<{ mode: string }, TraderError, { strategyId: string; note?: string; stepUp?: string }>({
    mutationFn: async ({ strategyId, note, stepUp }) => {
      const out = await unwrap<{ mode: string }>(
        traderApi.POST("/trader/v1/strategies/{strategy_id}/promote", {
          params: {
            path: { strategy_id: strategyId },
            header: {
              "Idempotency-Key": idempotencyKey(),
              ...(stepUp ? { "x-step-up": stepUp } : {}),
            },
          },
          body: { note: note || null },
        }),
      );
      return out.data;
    },
    onSettled: () => void refresh(),
  });
}

export function useDemote() {
  const refresh = useAfterMutation();
  return useMutation<{ mode: string }, TraderError, { strategyId: string; toMode: string; note?: string }>({
    mutationFn: async ({ strategyId, toMode, note }) => {
      const out = await unwrap<{ mode: string }>(
        traderApi.POST("/trader/v1/strategies/{strategy_id}/demote", {
          params: {
            path: { strategy_id: strategyId },
            header: { "Idempotency-Key": idempotencyKey() },
          },
          body: { to_mode: toMode, note: note || null },
        }),
      );
      return out.data;
    },
    onSettled: () => void refresh(),
  });
}

export function useSaveLimits() {
  const refresh = useAfterMutation();
  return useMutation<
    { version: number; unset: string[] },
    TraderError,
    { limits: Record<string, string | null>; stepUp?: string }
  >({
    mutationFn: async ({ limits, stepUp }) => {
      const out = await unwrap<{ version: number; unset: string[] }>(
        traderApi.PUT("/trader/v1/limits", {
          params: {
            header: {
              "Idempotency-Key": idempotencyKey(),
              ...(stepUp ? { "x-step-up": stepUp } : {}),
            },
          },
          body: { limits },
        }),
      );
      return out.data;
    },
    onSettled: () => void refresh(),
  });
}

export function useSaveAllowlist() {
  const refresh = useAfterMutation();
  return useMutation<
    { pairs: string[]; active: boolean },
    TraderError,
    {
      pairs: string[];
      minVolume: string | null;
      maxSpread: string | null;
      stepUp?: string;
    }
  >({
    mutationFn: async ({ pairs, minVolume, maxSpread, stepUp }) => {
      const out = await unwrap<{ pairs: string[]; active: boolean }>(
        traderApi.PUT("/trader/v1/allowlist", {
          params: {
            header: {
              "Idempotency-Key": idempotencyKey(),
              ...(stepUp ? { "x-step-up": stepUp } : {}),
            },
          },
          body: {
            pairs,
            min_quote_volume_24h_idr: minVolume,
            max_spread_pct: maxSpread,
          },
        }),
      );
      return out.data;
    },
    onSettled: () => void refresh(),
  });
}

export function useSaveParameters() {
  const refresh = useAfterMutation();
  return useMutation<
    { version: string; mode: string },
    TraderError,
    {
      ema_fast: number;
      ema_slow: number;
      adx_period: number;
      adx_threshold: string;
      atr_period: number;
      atr_stop_multiple: string;
      cooldown_s: number;
    }
  >({
    mutationFn: async (body) => {
      const out = await unwrap<{ version: string; mode: string }>(
        traderApi.PUT("/trader/v1/strategies/{strategy_id}/parameters", {
          params: {
            path: { strategy_id: "ema_adx" },
            header: { "Idempotency-Key": idempotencyKey() },
          },
          body,
        }),
      );
      return out.data;
    },
    onSettled: () => void refresh(),
  });
}

export interface PaperValues {
  slippage_pct: string;
  partial_fill_fraction: string;
  maker_fee_pct: string;
  taker_fee_pct: string;
  tax_pct: string;
  clearing_pct: string;
  start_equity_idr: string;
}

export function useSavePaper() {
  const refresh = useAfterMutation();
  return useMutation<unknown, TraderError, { values: PaperValues; stepUp?: string }>({
    mutationFn: ({ values, stepUp }) =>
      unwrap(
        traderApi.PUT("/trader/v1/paper-config", {
          params: {
            header: {
              "Idempotency-Key": idempotencyKey(),
              ...(stepUp ? { "x-step-up": stepUp } : {}),
            },
          },
          body: values,
        }),
      ),
    onSettled: () => void refresh(),
  });
}
