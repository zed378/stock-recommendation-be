import { useState } from "react";
import { useI18n } from "@/i18n/context";
import { Button, Card, ConfirmDialog, Field, inputClass } from "@/components/primitives";
import { OriginBadge, PanelBody } from "@/trader/components";
import { traderApi } from "@/trader/client";
import { useTraderQuery } from "@/trader/hooks";
import { useDemote, usePromote } from "@/trader/mutations";
import { StepUpDialog } from "@/trader/StepUpDialog";
import type { Gate, Mode, Promotion, Strategy } from "@/trader/types";

const ORDER: Mode[] = ["PAPER", "APPROVAL", "AUTO"];

const GATE_LABELS = {
  duration: "trader.gate.duration",
  data_integrity: "trader.gate.data_integrity",
  backtest: "trader.gate.backtest",
  paper_activity: "trader.gate.paper_activity",
  paper_drawdown: "trader.gate.paper_drawdown",
  no_breaker_or_kill_switch: "trader.gate.no_breaker_or_kill_switch",
  capital: "trader.gate.capital",
  slippage: "trader.gate.slippage",
} as const;

function gateText(g: Gate, t: ReturnType<typeof useI18n>["t"]): string | null {
  if (g.reason.startsWith("threshold unset")) return t("trader.promotion.unsetThreshold");
  if (g.reason === "no evidence") return t("trader.promotion.noEvidence");
  return null;
}

export function StrategyCard({ strategy }: { strategy: Strategy }) {
  const { t, dateTime } = useI18n();
  const promotion = useTraderQuery<Promotion>(["promotion", strategy.strategy_id], () =>
    traderApi.GET("/trader/v1/strategies/{strategy_id}/promotion", {
      params: { path: { strategy_id: strategy.strategy_id } },
    }),
  );
  const promote = usePromote();
  const demote = useDemote();
  const [note, setNote] = useState("");
  const [stepUp, setStepUp] = useState(false);
  const [confirmDemote, setConfirmDemote] = useState<Mode | null>(null);
  const lower = ORDER.slice(0, ORDER.indexOf(strategy.mode));

  return (
    <Card
      title={
        <h2 className="flex flex-wrap items-center gap-2 text-sm font-medium text-ink">
          <span className="font-mono">{strategy.strategy_id}</span>
          <span className="rounded border border-line px-1.5 py-0.5 text-[0.65rem] font-semibold tracking-wide">
            {t(`trader.mode.${strategy.mode}`)}
          </span>
          {strategy.mode === "PAPER" && <OriginBadge origin="PAPER" />}
        </h2>
      }
      action={
        <span className="text-xs text-muted">
          {t("trader.strategies.version", { version: strategy.version, when: dateTime(strategy.since) })}
        </span>
      }
    >
      <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">
        {t("trader.promotion.title")}
      </h3>
      <PanelBody query={promotion}>
        {(data) =>
          data.next === null ? (
            <p className="text-sm text-muted">{t("trader.promotion.top")}</p>
          ) : (
            <div className="space-y-4">
              <p className="text-sm text-muted">{t("trader.promotion.next", { mode: data.next })}</p>
              <ul className="divide-y divide-line">
                {data.gates.map((g) => {
                  const explain = gateText(g, t);
                  return (
                    <li key={g.name} className="flex flex-wrap items-start gap-x-4 gap-y-1 py-2.5">
                      <div className="min-w-0 flex-1">
                        <p className="text-sm text-ink">{g.name in GATE_LABELS ? t(GATE_LABELS[g.name as keyof typeof GATE_LABELS]) : g.name}</p>
                        {explain && <p className="mt-0.5 text-xs text-watch">{explain}</p>}
                      </div>
                      <p className="font-mono text-xs text-muted tnum">
                        {t("trader.promotion.measured")}: {g.measured ?? "-"} · {t("trader.promotion.threshold")}:{" "}
                        {g.threshold ?? t("trader.limits.unset")}
                      </p>
                      {/* Text and a mark, not colour alone. */}
                      <p className={`w-24 text-right text-xs font-semibold ${g.passed ? "text-rise" : "text-fall"}`}>
                        {g.passed ? `✓ ${t("trader.promotion.pass")}` : `✗ ${t("trader.promotion.fail")}`}
                      </p>
                    </li>
                  );
                })}
              </ul>
              <p className="text-xs text-muted">{t("trader.promotion.evidenceNote")}</p>
              <Field label={t("trader.promotion.note")}>
                <input className={inputClass} value={note} onChange={(e) => setNote(e.target.value)} />
              </Field>
              <Button
                busy={promote.isPending}
                onClick={() =>
                  data.next === "AUTO"
                    ? setStepUp(true)
                    : promote.mutate({ strategyId: strategy.strategy_id, note })
                }
              >
                {t("trader.promotion.go", { mode: data.next })}
              </Button>
              <div role="status" aria-live="polite">
                {promote.isSuccess && (
                  <p className="text-sm text-ink">{t("trader.promotion.done", { mode: promote.data.mode })}</p>
                )}
                {/* The server's reason, verbatim: it names the gate that blocked. */}
                {promote.error && <p className="text-sm text-fall">{promote.error.message}</p>}
              </div>
            </div>
          )
        }
      </PanelBody>

      {lower.length > 0 && (
        <div className="mt-6 border-t border-line pt-4">
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">
            {t("trader.demote.title")}
          </h3>
          <div className="flex flex-wrap gap-2">
            {lower.map((m) => (
              <Button key={m} variant="ghost" size="sm" onClick={() => setConfirmDemote(m)}>
                {t("trader.demote.to")} {m}
              </Button>
            ))}
          </div>
          {demote.error && <p className="mt-2 text-sm text-fall">{demote.error.message}</p>}
        </div>
      )}

      {stepUp && (
        <StepUpDialog
          scope="PROMOTE_AUTO"
          onCancel={() => setStepUp(false)}
          onGranted={(grant) => {
            setStepUp(false);
            promote.mutate({ strategyId: strategy.strategy_id, note, stepUp: grant });
          }}
        />
      )}
      {confirmDemote && (
        <ConfirmDialog
          title={t("trader.demote.title")}
          message={t("trader.demote.confirm", { strategy: strategy.strategy_id, mode: confirmDemote })}
          confirmLabel={t("trader.demote.go")}
          destructive
          busy={demote.isPending}
          onCancel={() => setConfirmDemote(null)}
          onConfirm={() =>
            demote.mutate(
              { strategyId: strategy.strategy_id, toMode: confirmDemote },
              { onSettled: () => setConfirmDemote(null) },
            )
          }
        />
      )}
    </Card>
  );
}
