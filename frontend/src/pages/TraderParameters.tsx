import { useId, useMemo, useState } from "react";
import { useI18n, type MessageKey } from "@/i18n/context";
import { Button, Card, inputClass, Modal } from "@/components/primitives";
import { OriginBadge, PanelBody } from "@/trader/components";
import { traderApi } from "@/trader/client";
import { useTraderQuery } from "@/trader/hooks";
import { compareDecimals, DECIMAL } from "@/trader/format";
import { useSaveParameters } from "@/trader/mutations";
import type { StrategyParams } from "@/trader/types";

type Kind = "int" | "int0" | "threshold" | "multiple";

interface Field {
  name: string;
  kind: Kind;
  unit: MessageKey | null;
  label: MessageKey;
  hint: MessageKey;
}

const FIELDS: Field[] = [
  { name: "ema_fast", kind: "int", unit: null, label: "trader.params.field.ema_fast.label", hint: "trader.params.field.ema_fast.hint" },
  { name: "ema_slow", kind: "int", unit: null, label: "trader.params.field.ema_slow.label", hint: "trader.params.field.ema_slow.hint" },
  { name: "adx_period", kind: "int", unit: null, label: "trader.params.field.adx_period.label", hint: "trader.params.field.adx_period.hint" },
  { name: "adx_threshold", kind: "threshold", unit: null, label: "trader.params.field.adx_threshold.label", hint: "trader.params.field.adx_threshold.hint" },
  { name: "atr_period", kind: "int", unit: null, label: "trader.params.field.atr_period.label", hint: "trader.params.field.atr_period.hint" },
  { name: "atr_stop_multiple", kind: "multiple", unit: null, label: "trader.params.field.atr_stop_multiple.label", hint: "trader.params.field.atr_stop_multiple.hint" },
  { name: "cooldown_s", kind: "int0", unit: "trader.unit.seconds", label: "trader.params.field.cooldown_s.label", hint: "trader.params.field.cooldown_s.hint" },
];

/** Mirrors `EmaAdxParams` validation on the server, which answers last. */
function problem(kind: Kind, text: string): MessageKey | null {
  const v = text.trim();
  if (v === "") return null; // reported once, as "fill in every number"
  switch (kind) {
    case "int":
      return /^\d+$/.test(v) && Number(v) >= 1 ? null : "trader.params.invalid.int";
    case "int0":
      return /^\d+$/.test(v) ? null : "trader.params.invalid.int0";
    case "threshold":
      return DECIMAL.test(v) && compareDecimals(v, "0") > 0 && compareDecimals(v, "100") <= 0
        ? null
        : "trader.params.invalid.threshold";
    case "multiple":
      return DECIMAL.test(v) && compareDecimals(v, "0") > 0 ? null : "trader.params.invalid.number";
  }
}

/** Candles of history the strategy needs: the longest of its look-backs (see `min_history`). */
function neededHistory(values: Record<string, string>): number | null {
  const n = (k: string) => (/^\d+$/.test(values[k]?.trim() ?? "") ? Number(values[k].trim()) : null);
  const slow = n("ema_slow");
  const adx = n("adx_period");
  const atr = n("atr_period");
  if (slow === null || adx === null || atr === null) return null;
  return Math.max(slow, 2 * adx + 1, atr + 1);
}

/**
 * The strategy's numbers, edited as a new version.
 *
 * Saving different numbers creates a new strategy version and returns the
 * strategy to PAPER: promotion evidence belongs to one set of numbers, so a
 * changed set starts again. The screen says so before saving, and says it with
 * more force when the strategy is currently live. Nothing is suggested and
 * nothing has a default: every field must be filled by the owner.
 */
export function TraderParameters() {
  const { t } = useI18n();
  const query = useTraderQuery<StrategyParams>(
    ["parameters"],
    () =>
      traderApi.GET("/trader/v1/strategies/{strategy_id}/parameters", {
        params: { path: { strategy_id: "ema_adx" } },
      }),
    { interval: false },
  );
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-lg font-semibold text-ink">{t("trader.params.title")}</h1>
        <p className="mt-1 max-w-prose text-sm text-muted">{t("trader.params.intro")}</p>
      </header>
      <Card
        title={
          <h2 className="flex flex-wrap items-center gap-2 text-sm font-medium text-ink">
            <span className="font-mono">ema_adx</span>
            <OriginBadge origin="PAPER" />
          </h2>
        }
      >
        <PanelBody query={query}>
          {(data) => <ParametersForm key={JSON.stringify(data.params) + data.version} data={data} />}
        </PanelBody>
      </Card>
    </div>
  );
}

function ParametersForm({ data }: { data: StrategyParams }) {
  const { t } = useI18n();
  const save = useSaveParameters();
  const stored = (name: string) => data.params?.[name] ?? "";
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(FIELDS.map((f) => [f.name, stored(f.name)])),
  );
  const [reviewing, setReviewing] = useState(false);
  const [saved, setSaved] = useState<{ version: string; mode: string } | null>(null);

  const rows = useMemo(
    () =>
      FIELDS.map((field) => {
        const text = values[field.name] ?? "";
        return {
          field,
          text,
          changed: text.trim() !== stored(field.name),
          error: problem(field.kind, text),
        };
      }),
    // `stored` is derived from `data`, which is the form's key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [values, data],
  );

  const empty = rows.some((r) => r.text.trim() === "");
  const orderBad =
    /^\d+$/.test(values.ema_fast?.trim() ?? "") &&
    /^\d+$/.test(values.ema_slow?.trim() ?? "") &&
    Number(values.ema_fast) >= Number(values.ema_slow);
  const needed = neededHistory(values);
  const tooLong = needed !== null && needed > data.max_history_bars;
  const invalid = rows.some((r) => r.error !== null) || orderBad || tooLong;
  const changes = rows.filter((r) => r.changed);
  const canReview = changes.length > 0 && !empty && !invalid;
  const live = data.mode !== null && data.mode !== "PAPER";

  const send = () =>
    save.mutate(
      {
        ema_fast: Number(values.ema_fast),
        ema_slow: Number(values.ema_slow),
        adx_period: Number(values.adx_period),
        adx_threshold: values.adx_threshold.trim(),
        atr_period: Number(values.atr_period),
        atr_stop_multiple: values.atr_stop_multiple.trim(),
        cooldown_s: Number(values.cooldown_s),
      },
      {
        onSuccess: (out) => {
          setSaved(out);
          setReviewing(false);
        },
      },
    );

  return (
    <form
      className="space-y-6"
      onSubmit={(event) => {
        event.preventDefault();
        if (canReview) setReviewing(true);
      }}
    >
      <p className="text-sm text-muted">
        {data.configured && data.version
          ? t("trader.params.current", { version: data.version, mode: data.mode ?? "-" })
          : t("trader.params.none")}
      </p>

      <div className="space-y-5">
        {rows.map((r) => (
          <ParamRow
            key={r.field.name}
            field={r.field}
            text={r.text}
            stored={stored(r.field.name)}
            changed={r.changed}
            error={r.error ?? (r.field.name === "ema_fast" && orderBad ? "trader.params.invalid.order" : null)}
            onChange={(next) => {
              setSaved(null);
              setValues((v) => ({ ...v, [r.field.name]: next }));
            }}
          />
        ))}
      </div>

      {needed !== null && (
        <p className={`text-sm ${tooLong ? "text-fall" : "text-muted"}`} role={tooLong ? "alert" : undefined}>
          {tooLong
            ? t("trader.params.historyTooLong", { needed, max: data.max_history_bars })
            : t("trader.params.history", { needed, max: data.max_history_bars })}
        </p>
      )}

      <p className="max-w-prose border-l-2 border-watch/40 pl-2.5 text-xs leading-relaxed text-faint">
        {t("trader.params.resets")}
      </p>
      {live && <p className="text-sm text-watch">{t("trader.params.resetsLive", { mode: data.mode ?? "" })}</p>}

      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
        <Button type="submit" disabled={!canReview}>
          {t("trader.params.review")}
        </Button>
        <p className="text-sm text-muted" role="status" aria-live="polite">
          {saved
            ? t("trader.params.saved", { version: saved.version, mode: saved.mode })
            : empty
              ? t("trader.params.mustFill")
              : changes.length === 0
                ? t("trader.limits.noChanges")
                : invalid
                  ? t("trader.limits.hasErrors")
                  : ""}
        </p>
      </div>

      {reviewing && (
        <Modal
          title={t("trader.params.reviewTitle")}
          onClose={() => !save.isPending && setReviewing(false)}
          footer={
            <>
              <Button type="button" variant="ghost" autoFocus onClick={() => setReviewing(false)} disabled={save.isPending}>
                {t("common.cancel")}
              </Button>
              <Button type="button" variant={live ? "danger" : "primary"} busy={save.isPending} onClick={send}>
                {t("trader.params.save")}
              </Button>
            </>
          }
        >
          <ul className="space-y-2">
            {changes.map((r) => (
              <li key={r.field.name} className="flex flex-wrap items-baseline justify-between gap-x-4 border-b border-line pb-2 last:border-0">
                <span className="text-sm text-ink">{t(r.field.label)}</span>
                <span className="font-mono text-xs tnum text-muted">
                  {t("trader.limits.review.change", {
                    from: stored(r.field.name) === "" ? t("trader.limits.unset") : stored(r.field.name),
                    to: r.text.trim(),
                  })}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-4 text-sm text-watch">{t("trader.params.resets")}</p>
          {live && <p className="mt-2 text-sm font-medium text-fall">{t("trader.params.resetsLive", { mode: data.mode ?? "" })}</p>}
          {save.error && (
            <p role="alert" className="mt-3 text-sm text-fall">
              {save.error.message}
            </p>
          )}
        </Modal>
      )}
    </form>
  );
}

function ParamRow({
  field,
  text,
  stored,
  changed,
  error,
  onChange,
}: {
  field: Field;
  text: string;
  stored: string;
  changed: boolean;
  error: MessageKey | null;
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
        <p id={`${id}-hint`} className="mt-0.5 max-w-prose text-xs text-faint">
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
        <p className="mt-1 text-xs text-faint">
          {stored === "" ? t("trader.limits.currentUnset") : t("trader.limits.current", { value: stored })}
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
