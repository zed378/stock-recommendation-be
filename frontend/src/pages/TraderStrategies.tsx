import { useId, useMemo, useState } from "react";
import { useI18n, type MessageKey } from "@/i18n/context";
import { Button, Card, Empty, inputClass, Modal } from "@/components/primitives";
import { OriginBadge, PanelBody } from "@/trader/components";
import { traderApi } from "@/trader/client";
import { groupDigits } from "@/trader/format";
import { useTraderQuery } from "@/trader/hooks";
import {
  useSaveThresholds,
  type PromotionThresholdsBodyValues,
} from "@/trader/mutations";
import { StepUpDialog } from "@/trader/StepUpDialog";
import { StrategyWorkspace } from "@/trader/StrategyWorkspace";
import {
  THRESHOLD_FIELDS,
  thresholdEffect,
  thresholdProblem,
  type ThresholdEffect,
  type ThresholdField,
  type ThresholdName,
} from "@/trader/validators";
import type { Portfolio, PromotionThresholds } from "@/trader/types";


/**
 * Each strategy's mode, promotion gates, stored backtest evidence, and the owner's
 * promotion thresholds (OQ-12).
 *
 * Every gate shows its measured value, its threshold, and pass or fail. A
 * threshold the owner has not set is shown as unset and blocks promotion; it is
 * never shown as a default (docs/04-UX-UI/02).
 */
export function TraderStrategies() {
  const { t } = useI18n();
  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold text-ink">{t("trader.strategies.title")}</h1>
      <StrategyWorkspace />
      <BacktestRunsCard />
      <PromotionThresholdsCard />
    </div>
  );
}

function BacktestRunsCard() {
  const { t, dateTime } = useI18n();
  const portfolio = useTraderQuery<Portfolio>(["portfolio"], () =>
    traderApi.GET("/trader/v1/portfolio"),
  );
  return (
    <Card
      title={
        <h2 className="flex items-center gap-2 text-sm font-medium text-ink">
          {t("trader.backtests.title")}
          <OriginBadge origin="BACKTEST" />
        </h2>
      }
    >
      <PanelBody query={portfolio}>
        {(data) =>
          data.backtests.length === 0 ? (
            <Empty message={t("trader.backtests.empty")} />
          ) : (
            <div className="-mx-4 overflow-x-auto px-4">
              <table className="w-full min-w-[36rem] text-left text-sm">
                <thead className="text-xs text-muted">
                  <tr>
                    <th className="pb-2 pr-3 font-medium">{t("trader.backtests.col.pair")}</th>
                    <th className="pb-2 pr-3 font-medium">{t("trader.backtests.col.version")}</th>
                    <th className="pb-2 pr-3 font-medium">{t("trader.backtests.col.trades")}</th>
                    <th className="pb-2 pr-3 font-medium">{t("trader.backtests.col.winRate")}</th>
                    <th className="pb-2 pr-3 font-medium">{t("trader.backtests.col.return")}</th>
                    <th className="pb-2 pr-3 font-medium">{t("trader.backtests.col.drawdown")}</th>
                    <th className="pb-2 font-medium">{t("trader.backtests.col.ranAt")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {data.backtests.map((b) => (
                    <tr key={b.id}>
                      <td className="py-2 pr-3 font-mono">
                        {b.pair} <OriginBadge origin={b.origin} />
                      </td>
                      <td className="py-2 pr-3 font-mono text-xs text-muted">{b.strategy_version.slice(0, 12)}</td>
                      <td className="py-2 pr-3 font-mono tnum">{b.trades}</td>
                      <td className="py-2 pr-3 font-mono tnum">{b.win_rate_pct}%</td>
                      <td className="py-2 pr-3 font-mono tnum">{b.total_return_pct}%</td>
                      <td className="py-2 pr-3 font-mono tnum">{b.max_drawdown_pct}%</td>
                      <td className="py-2 text-xs text-muted">{dateTime(b.ran_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
      </PanelBody>
    </Card>
  );
}

function PromotionThresholdsCard() {
  const { t } = useI18n();
  const query = useTraderQuery<PromotionThresholds>(
    ["promotion-thresholds"],
    () => traderApi.GET("/trader/v1/promotion-thresholds"),
    { interval: false },
  );
  return (
    <Card title={t("trader.thresholds.title")}>
      <p className="mb-4 max-w-prose text-sm text-muted">{t("trader.thresholds.intro")}</p>
      <PanelBody query={query}>
        {(data) => <ThresholdsForm key={JSON.stringify(data.thresholds)} data={data} />}
      </PanelBody>
    </Card>
  );
}

function ThresholdsForm({ data }: { data: PromotionThresholds }) {
  const { t, locale } = useI18n();
  const save = useSaveThresholds();
  const storedText = (name: ThresholdName): string => {
    const v = data.thresholds[name];
    return v === null || v === undefined ? "" : String(v);
  };
  const [values, setValues] = useState<Record<ThresholdName, string>>(
    () =>
      Object.fromEntries(
        THRESHOLD_FIELDS.map((f) => [f.name, storedText(f.name)]),
      ) as Record<ThresholdName, string>,
  );
  const [reviewing, setReviewing] = useState(false);
  const [stepUp, setStepUp] = useState(false);
  const [done, setDone] = useState(false);

  const rows = useMemo(
    () =>
      THRESHOLD_FIELDS.map((field) => {
        const text = values[field.name];
        const before = storedText(field.name);
        const trimmed = text.trim();
        const changed = trimmed !== before;
        return {
          field,
          text,
          before: before === "" ? null : before,
          after: trimmed === "" ? null : trimmed,
          changed,
          error: thresholdProblem(field.kind, text),
          effect: changed
            ? thresholdEffect(field, before === "" ? null : before, trimmed === "" ? null : trimmed)
            : ("tighter" as ThresholdEffect),
        };
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [values, data],
  );

  const invalid = rows.some((r) => r.error !== null);
  const changes = rows.filter((r) => r.changed);
  const needsPassword = changes.some((r) => r.effect === "looser");
  const canReview = changes.length > 0 && !invalid;

  const payload = (): PromotionThresholdsBodyValues => {
    const raw = (n: ThresholdName) => {
      const v = values[n].trim();
      return v === "" ? null : v;
    };
    const trades = raw("min_paper_trades");
    return {
      min_paper_trades: trades === null ? null : Number(trades),
      max_paper_drawdown_pct: raw("max_paper_drawdown_pct"),
      backtest_min_return_pct: raw("backtest_min_return_pct"),
      max_live_capital_idr: raw("max_live_capital_idr"),
      max_slippage_pct: raw("max_slippage_pct"),
    };
  };

  const send = (grant?: string) =>
    save.mutate(
      { values: payload(), stepUp: grant },
      {
        onSuccess: () => {
          setDone(true);
          setReviewing(false);
          setStepUp(false);
        },
        onError: () => setStepUp(false),
      },
    );

  return (
    <form
      className="space-y-5"
      onSubmit={(e) => {
        e.preventDefault();
        if (canReview) setReviewing(true);
      }}
    >
      <p className={data.unset.length > 0 ? "text-xs text-watch" : "text-xs text-muted"}>
        {data.unset.length > 0
          ? t("trader.thresholds.unsetCount", { count: data.unset.length })
          : t("trader.thresholds.allSet")}
      </p>

      <div className="space-y-4">
        {rows.map((r) => (
          <ThresholdRow
            key={r.field.name}
            field={r.field}
            text={r.text}
            before={r.before}
            changed={r.changed}
            error={r.error}
            display={(v) => (r.field.kind === "idr" ? groupDigits(v, locale) : v)}
            onChange={(next) => {
              setDone(false);
              setValues((prev) => ({ ...prev, [r.field.name]: next }));
            }}
          />
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
        <Button type="submit" disabled={!canReview}>
          {t("trader.thresholds.review")}
        </Button>
        <p className="text-sm text-muted" role="status" aria-live="polite">
          {done
            ? t("trader.thresholds.saved")
            : invalid
              ? t("trader.limits.hasErrors")
              : changes.length === 0
                ? t("trader.limits.noChanges")
                : ""}
        </p>
      </div>

      {reviewing && (
        <Modal
          title={t("trader.thresholds.reviewTitle")}
          onClose={() => !save.isPending && setReviewing(false)}
          footer={
            <>
              <Button
                type="button"
                variant="ghost"
                autoFocus
                onClick={() => setReviewing(false)}
                disabled={save.isPending}
              >
                {t("common.cancel")}
              </Button>
              <Button
                type="button"
                busy={save.isPending}
                onClick={() => (needsPassword ? setStepUp(true) : send())}
              >
                {t("trader.thresholds.save")}
              </Button>
            </>
          }
        >
          <ul className="space-y-3">
            {changes.map((r) => (
              <li
                key={r.field.name}
                className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-line pb-2 last:border-0"
              >
                <span className="text-sm text-ink">{t(r.field.label)}</span>
                <span className="font-mono text-xs tnum text-muted">
                  {t("trader.limits.review.change", {
                    from: r.before ?? t("trader.limits.unset"),
                    to: r.after ?? t("trader.limits.unset"),
                  })}
                </span>
                <span
                  className={`w-full text-xs font-medium ${
                    r.effect === "looser" ? "text-watch" : "text-muted"
                  }`}
                >
                  {t(
                    r.effect === "looser"
                      ? "trader.limits.review.looser"
                      : r.effect === "tighter"
                        ? "trader.limits.review.tighter"
                        : "trader.limits.review.cleared",
                  )}
                </span>
              </li>
            ))}
          </ul>
          {needsPassword && (
            <p className="mt-4 text-sm text-watch">{t("trader.thresholds.stepUpNote")}</p>
          )}
          {save.error && (
            <p role="alert" className="mt-3 text-sm text-fall">
              {save.error.message}
            </p>
          )}
        </Modal>
      )}
      {stepUp && (
        <StepUpDialog
          scope="RAISE_LIMIT"
          onCancel={() => setStepUp(false)}
          onGranted={(grant) => send(grant)}
        />
      )}
    </form>
  );
}

function ThresholdRow({
  field,
  text,
  before,
  changed,
  error,
  display,
  onChange,
}: {
  field: ThresholdField;
  text: string;
  before: string | null;
  changed: boolean;
  error: MessageKey | null;
  display: (v: string) => string;
  onChange: (next: string) => void;
}) {
  const { t } = useI18n();
  const id = useId();
  return (
    <div className="grid gap-x-6 gap-y-1 md:grid-cols-[1fr_16rem] md:items-start">
      <div>
        <label htmlFor={id} className="text-sm font-medium text-ink">
          {t(field.label)}
        </label>
        <p id={`${id}-hint`} className="mt-0.5 max-w-prose text-xs text-muted">
          {t(field.hint)}
        </p>
      </div>
      <div>
        <div className="flex items-center gap-2">
          <input
            id={id}
            className={`${inputClass} font-mono tnum ${error ? "border-fall/60" : ""}`}
            inputMode="decimal"
            autoComplete="off"
            spellCheck={false}
            value={text}
            aria-invalid={error !== null}
            aria-describedby={`${id}-hint${error ? ` ${id}-err` : ""}`}
            onChange={(e) => onChange(e.target.value)}
          />
          {field.unit && <span className="shrink-0 text-xs text-muted">{t(field.unit)}</span>}
        </div>
        <p className="mt-1 text-xs text-muted">
          {before === null
            ? t("trader.limits.currentUnset")
            : t("trader.limits.current", { value: display(before) })}
          {changed && <span className="ml-2 font-medium text-watch">{t("trader.limits.changed")}</span>}
        </p>
        {error && (
          <p id={`${id}-err`} role="alert" className="mt-1 text-xs text-fall">
            {t(error)}
          </p>
        )}
      </div>
    </div>
  );
}
