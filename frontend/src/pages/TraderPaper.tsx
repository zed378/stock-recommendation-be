import { useId, useMemo, useState } from "react";
import { useI18n, type MessageKey } from "@/i18n/context";
import { Button, Card, inputClass, Modal } from "@/components/primitives";
import { OriginBadge, PanelBody } from "@/trader/components";
import { traderApi } from "@/trader/client";
import { useTraderQuery } from "@/trader/hooks";
import { groupDigits } from "@/trader/format";
import { useSavePaper, type PaperValues } from "@/trader/mutations";
import { StepUpDialog } from "@/trader/StepUpDialog";
import {
  PAPER_FIELDS as FIELDS,
  paperEffect as effect,
  paperProblem as problem,
  type PaperEffect as Effect,
  type PaperField as Field,
  type PaperName as Name,
} from "@/trader/validators";
import { OriginPortfolioBlock } from "@/pages/Trader";
import type { PaperConfig, Portfolio } from "@/trader/types";

/**
 * The assumptions behind every simulated trade.
 *
 * These numbers decide whether paper results look good, which is exactly why they
 * are the owner's and have no defaults. Changing them after results exist is the
 * quiet way to flatter the evidence, so the screen says what a change does to the
 * look of the results, and when paper fills already exist a flattering change asks
 * for the password again (the server enforces it). Recorded fills are never
 * recalculated.
 */
export function TraderPaper() {
  const { t } = useI18n();
  const query = useTraderQuery<PaperConfig>(
    ["paper-config"],
    () => traderApi.GET("/trader/v1/paper-config"),
    { interval: false },
  );
  const portfolio = useTraderQuery<Portfolio>(["portfolio"], () =>
    traderApi.GET("/trader/v1/portfolio"),
  );
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-lg font-semibold text-ink">{t("trader.paper.title")}</h1>
        <p className="mt-1 max-w-prose text-sm text-muted">{t("trader.paper.intro")}</p>
      </header>
      <Card
        title={
          <h2 className="flex items-center gap-2 text-sm font-medium text-ink">
            {t("trader.portfolio.paperTitle")}
            <OriginBadge origin="PAPER" />
          </h2>
        }
      >
        <PanelBody query={portfolio}>
          {(data) => <OriginPortfolioBlock data={data.paper} />}
        </PanelBody>
      </Card>
      <Card
        title={
          <h2 className="flex items-center gap-2 text-sm font-medium text-ink">
            {t("nav.traderPaper")}
            <OriginBadge origin="PAPER" />
          </h2>
        }
      >
        <PanelBody query={query}>
          {(data) => <PaperForm key={JSON.stringify(data)} data={data} />}
        </PanelBody>
      </Card>
    </div>
  );
}

function PaperForm({ data }: { data: PaperConfig }) {
  const { t, locale } = useI18n();
  const save = useSavePaper();
  const stored = (name: Name) => (data.configured ? (data[name] ?? "") : "");
  const [values, setValues] = useState<Record<Name, string>>(
    () => Object.fromEntries(FIELDS.map((f) => [f.name, stored(f.name)])) as Record<Name, string>,
  );
  const [reviewing, setReviewing] = useState(false);
  const [stepUp, setStepUp] = useState(false);
  const [done, setDone] = useState(false);

  const rows = useMemo(
    () =>
      FIELDS.map((field) => {
        const text = values[field.name];
        const before = stored(field.name);
        const changed = text.trim() !== before;
        return {
          field, text, before, changed,
          error: problem(field.kind, text),
          effect: changed ? effect(field, before, text) : ("neutral" as Effect),
        };
      }),
    // `stored` is derived from `data`, which is the form's key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [values, data],
  );
  const empty = rows.some((r) => r.text.trim() === "");
  const invalid = rows.some((r) => r.error !== null);
  const changes = rows.filter((r) => r.changed);
  const flatters = changes.some((r) => r.effect === "flatters");
  const needsPassword = flatters && data.configured && data.paper_fills > 0;
  const canReview = changes.length > 0 && !empty && !invalid;

  const send = (grant?: string) =>
    save.mutate(
      { values: Object.fromEntries(FIELDS.map((f) => [f.name, values[f.name].trim()])) as unknown as PaperValues, stepUp: grant },
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
      className="space-y-6"
      onSubmit={(event) => {
        event.preventDefault();
        if (canReview) setReviewing(true);
      }}
    >
      {!data.configured && <p className="text-sm text-watch">{t("trader.paper.notConfigured")}</p>}
      {data.paper_fills > 0 && (
        <p className="text-sm text-muted">{t("trader.paper.history", { count: data.paper_fills })}</p>
      )}

      <div className="space-y-5">
        {rows.map((r) => (
          <PaperRow
            key={r.field.name}
            field={r.field}
            text={r.text}
            before={r.before}
            changed={r.changed}
            error={r.error}
            display={(v) => (r.field.kind === "idr" ? groupDigits(v, locale) : v)}
            onChange={(next) => {
              setDone(false);
              setValues((v) => ({ ...v, [r.field.name]: next }));
            }}
          />
        ))}
      </div>

      <p className="max-w-prose border-l-2 border-watch/40 pl-2.5 text-xs leading-relaxed text-faint">
        {t("trader.paper.honest")}
        {data.paper_fills > 0 && ` ${t("trader.paper.flatterNote")}`}
      </p>

      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
        <Button type="submit" disabled={!canReview}>
          {t("trader.paper.review")}
        </Button>
        <p className="text-sm text-muted" role="status" aria-live="polite">
          {done
            ? t("trader.paper.saved")
            : empty
              ? t("trader.paper.mustFill")
              : invalid
                ? t("trader.limits.hasErrors")
                : changes.length === 0
                  ? t("trader.limits.noChanges")
                  : ""}
        </p>
      </div>

      {reviewing && (
        <Modal
          title={t("trader.paper.reviewTitle")}
          onClose={() => !save.isPending && setReviewing(false)}
          footer={
            <>
              <Button type="button" variant="ghost" autoFocus onClick={() => setReviewing(false)} disabled={save.isPending}>
                {t("common.cancel")}
              </Button>
              <Button type="button" busy={save.isPending} onClick={() => (needsPassword ? setStepUp(true) : send())}>
                {t("trader.paper.save")}
              </Button>
            </>
          }
        >
          <ul className="space-y-3">
            {changes.map((r) => (
              <li key={r.field.name} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-line pb-2 last:border-0">
                <span className="text-sm text-ink">{t(r.field.label)}</span>
                <span className="font-mono text-xs tnum text-muted">
                  {t("trader.limits.review.change", {
                    from: r.before === "" ? t("trader.limits.unset") : r.before,
                    to: r.text.trim(),
                  })}
                </span>
                {r.effect !== "neutral" && (
                  <span className={`w-full text-xs font-medium ${r.effect === "flatters" ? "text-watch" : "text-muted"}`}>
                    {t(r.effect === "flatters" ? "trader.paper.effect.flatters" : "trader.paper.effect.harsher")}
                  </span>
                )}
              </li>
            ))}
          </ul>
          {needsPassword && <p className="mt-4 text-sm text-watch">{t("trader.paper.flatterNote")}</p>}
          {save.error && (
            <p role="alert" className="mt-3 text-sm text-fall">
              {save.error.message}
            </p>
          )}
        </Modal>
      )}
      {stepUp && <StepUpDialog scope="RAISE_LIMIT" onCancel={() => setStepUp(false)} onGranted={(g) => send(g)} />}
    </form>
  );
}

function PaperRow({
  field, text, before, changed, error, display, onChange,
}: {
  field: Field;
  text: string;
  before: string;
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
          {before === "" ? t("trader.limits.currentUnset") : t("trader.limits.current", { value: display(before) })}
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
