import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useI18n } from "@/i18n/context";
import { useToast } from "@/components/toastContext";
import { idempotencyKey, traderApi, unwrap, TraderError } from "@/trader/client";
import type {
  BacktestJob,
  CredentialKind,
  KillResult,
  PromotionThresholds,
  StrategyDef,
  StrategyPaper,
} from "@/trader/types";
import type { PairGroup } from "@/trader/pairGroups";

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
      allPairs: boolean;
      maxPairs: number | null;
      stepUp?: string;
    }
  >({
    mutationFn: async ({ pairs, minVolume, maxSpread, allPairs, maxPairs, stepUp }) => {
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
            all_pairs: allPairs,
            max_pairs: maxPairs,
          },
        }),
      );
      return out.data;
    },
    onSettled: () => void refresh(),
  });
}

/** Replace the owner's pair groups. Groups trade nothing, so there is no step-up. */
export function useSavePairGroups() {
  const queryClient = useQueryClient();
  return useMutation<{ groups: { name: string; pairs: string[] }[] }, TraderError, PairGroup[]>({
    mutationFn: async (groups) => {
      const out = await unwrap<{ groups: { name: string; pairs: string[] }[] }>(
        traderApi.PUT("/trader/v1/pair-groups", {
          params: { header: { "Idempotency-Key": idempotencyKey() } },
          body: { groups },
        }),
      );
      return out.data;
    },
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ["trader", "pair-groups"] }),
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

/**
 * Storing a credential. Deliberately not a React Query mutation: those keep their variables
 * in the mutation cache after they settle, which would leave the key and secret in memory for
 * minutes. Here the values exist only as arguments to `run`, are sent, and are gone. A refusal
 * carries only the server's reason, which never contains them.
 */
export function useStoreCredential() {
  const refresh = useAfterMutation();
  const [state, setState] = useState<{
    pending: boolean;
    error: TraderError | null;
    success: boolean;
  }>({ pending: false, error: null, success: false });

  const run = async (args: {
    kind: CredentialKind;
    key: string;
    secret: string;
    stepUp: string;
  }): Promise<boolean> => {
    setState({ pending: true, error: null, success: false });
    try {
      await unwrap(
        traderApi.PUT("/trader/v1/credentials/{kind}", {
          params: {
            path: { kind: args.kind },
            header: { "Idempotency-Key": idempotencyKey(), "x-step-up": args.stepUp },
          },
          body: { key: args.key, secret: args.secret },
        }),
      );
      setState({ pending: false, error: null, success: true });
      return true;
    } catch (err) {
      const error =
        err instanceof TraderError
          ? err
          : new TraderError("The request failed.", "UNKNOWN", null, null, null);
      setState({ pending: false, error, success: false });
      return false;
    } finally {
      void refresh();
    }
  };
  return { run, isPending: state.pending, error: state.error, isSuccess: state.success };
}

export function useTestCredential() {
  const refresh = useAfterMutation();
  return useMutation<{ last_test_ok: boolean; reason: string | null }, TraderError, { kind: CredentialKind }>({
    mutationFn: async ({ kind }) => {
      const out = await unwrap<{ last_test_ok: boolean; reason: string | null }>(
        traderApi.POST("/trader/v1/credentials/{kind}/test", {
          params: { path: { kind }, header: { "Idempotency-Key": idempotencyKey() } },
        }),
      );
      return out.data;
    },
    onSettled: () => void refresh(),
  });
}

export function useRemoveCredential() {
  const refresh = useAfterMutation();
  return useMutation<unknown, TraderError, { kind: CredentialKind; stepUp: string }>({
    mutationFn: ({ kind, stepUp }) =>
      unwrap(
        traderApi.DELETE("/trader/v1/credentials/{kind}", {
          params: {
            path: { kind },
            header: { "Idempotency-Key": idempotencyKey(), "x-step-up": stepUp },
          },
        }),
      ),
    onSettled: () => void refresh(),
  });
}

export interface PromotionThresholdsBodyValues {
  min_paper_trades: number | null;
  max_paper_drawdown_pct: string | null;
  backtest_min_return_pct: string | null;
  max_live_capital_idr: string | null;
  max_slippage_pct: string | null;
}

export function useSaveThresholds() {
  const refresh = useAfterMutation();
  return useMutation<
    PromotionThresholds,
    TraderError,
    { values: PromotionThresholdsBodyValues; stepUp?: string }
  >({
    mutationFn: async ({ values, stepUp }) => {
      const out = await unwrap<PromotionThresholds>(
        traderApi.PUT("/trader/v1/promotion-thresholds", {
          params: {
            header: {
              "Idempotency-Key": idempotencyKey(),
              ...(stepUp ? { "x-step-up": stepUp } : {}),
            },
          },
          body: values,
        }),
      );
      return out.data;
    },
    onSettled: () => void refresh(),
  });
}

export function useSaveStrategyDef() {
  const refresh = useAfterMutation();
  return useMutation<
    StrategyDef,
    TraderError,
    { id: string; label: string; kind: string; params: Record<string, string>; existing: boolean }
  >({
    mutationFn: async ({ id, label, kind, params, existing }) => {
      const headers = { "Idempotency-Key": idempotencyKey() };
      const out = existing
        ? await unwrap<StrategyDef>(
            traderApi.PUT("/trader/v1/strategy-defs/{strategy_id}", {
              params: { path: { strategy_id: id }, header: headers },
              body: { label, params },
            }),
          )
        : await unwrap<StrategyDef>(
            traderApi.POST("/trader/v1/strategy-defs", {
              params: { header: headers },
              body: { id, label, kind, params },
            }),
          );
      return out.data;
    },
    onSettled: () => void refresh(),
  });
}

export function useDeleteStrategyDef() {
  const refresh = useAfterMutation();
  return useMutation<unknown, TraderError, { id: string }>({
    mutationFn: ({ id }) =>
      unwrap(
        traderApi.DELETE("/trader/v1/strategy-defs/{strategy_id}", {
          params: { path: { strategy_id: id }, header: { "Idempotency-Key": idempotencyKey() } },
        }),
      ),
    onSettled: () => void refresh(),
  });
}

export function useSetStrategyPaper() {
  const refresh = useAfterMutation();
  return useMutation<StrategyPaper, TraderError, { id: string; enabled: boolean }>({
    mutationFn: async ({ id, enabled }) => {
      const out = await unwrap<StrategyPaper>(
        traderApi.PUT("/trader/v1/strategy-defs/{strategy_id}/paper", {
          params: { path: { strategy_id: id }, header: { "Idempotency-Key": idempotencyKey() } },
          body: { enabled },
        }),
      );
      return out.data;
    },
    onSettled: () => void refresh(),
  });
}

export function useStartBacktests() {
  const refresh = useAfterMutation();
  return useMutation<BacktestJob, TraderError, { strategyIds: string[] | null }>({
    mutationFn: async ({ strategyIds }) => {
      const out = await unwrap<BacktestJob>(
        traderApi.POST("/trader/v1/backtests", {
          params: { header: { "Idempotency-Key": idempotencyKey() } },
          body: { strategy_ids: strategyIds },
        }),
      );
      return out.data;
    },
    onSettled: () => void refresh(),
  });
}

export function countCsvDataRows(csv: string): number {
  const lines = csv
    .replace(/\r\n/g, "\n")
    .split("\n")
    .filter((line) => line.length > 0);
  return Math.max(0, lines.length - 1);
}

export async function exportTraderCsv(
  kind: "ledger" | "audit",
  start: string,
  end: string,
): Promise<{ csv: string; rowCount: number; headerCount: number }> {
  const result = await traderApi.GET("/trader/v1/export", {
    params: { query: { kind, start, end } },
    parseAs: "text",
  });
  if (!result.response.ok || typeof result.data !== "string") {
    throw new TraderError(
      `Export failed (${result.response.status}).`,
      result.response.status === 403 ? "FORBIDDEN" : "UNKNOWN",
      null,
      null,
      result.response.status,
    );
  }
  const csv = result.data;
  const dataRows = countCsvDataRows(csv);
  const rawHeader = result.response.headers.get("X-Row-Count");
  const headerCount = rawHeader !== null && /^\d+$/.test(rawHeader) ? Number(rawHeader) : dataRows;
  return { csv, rowCount: dataRows, headerCount };
}

