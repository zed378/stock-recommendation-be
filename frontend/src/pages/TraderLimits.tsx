import { useId, useMemo, useState } from "react";
import { useI18n, type MessageKey } from "@/i18n/context";
import { Button, Card, Field, inputClass, Modal } from "@/components/primitives";
import { PanelBody } from "@/trader/components";
import { traderApi } from "@/trader/client";
import { useTraderQuery } from "@/trader/hooks";
import { compareDecimals, DECIMAL, groupDigits } from "@/trader/format";
import {
  ALL_FIELDS,
  allowlistEffects,
  allowlistLoosens,
  effect,
  GROUPS,
  needsStepUp,
  PAIR,
  parsePairs,
  problem,
  type Effect,
  type LimitField,
} from "@/trader/limitsMeta";
import { useSaveAllowlist, useSaveLimits, useSavePairGroups } from "@/trader/mutations";
import { PairPicker } from "@/trader/PairPicker";
import { StepUpDialog } from "@/trader/StepUpDialog";
import type { Allowlist, Limits, PairCatalog, PairGroups } from "@/trader/types";

/** Mirrors `MAX_ALL_PAIRS_LIMIT` on the server: the most markets ALL may keep current. */
const MAX_ALL_PAIRS = 200;

const EFFECT_LABEL: Record<Effect, MessageKey | null> = {
  looser: "trader.limits.review.looser",
  tighter: "trader.limits.review.tighter",
  cleared: "trader.limits.review.cleared",
  enabled: "trader.limits.review.enabled",
  neutral: null,
};

/**
 * Risk limits and the pair allowlist: the owner's numbers, edited in one place.
 *
 * Nothing here has a default and nothing is suggested. A field left empty is
 * unset and disables trading; the screen says so next to the field. Every save
 * goes through a review that names what gets looser and what gets tighter, and a
 * change that lets more risk through asks for the password again. The server
 * validates ranges and decides about the step-up regardless (UX principle 8).
 */
export function TraderLimits() {
  const { t } = useI18n();
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-lg font-semibold text-ink">{t("trader.limits.page.title")}</h1>
        <p className="mt-1 max-w-prose text-sm text-muted">{t("trader.limits.page.intro")}</p>
      </header>
      <LimitsEditor />
      <AllowlistEditor />
    </div>
  );
}

// ------------------------------------------------------------------- limits

function LimitsEditor() {
  const { t } = useI18n();
  // No polling: a form that rewrites itself under the cursor loses what is being typed.
  const query = useTraderQuery<Limits>(["limits"], () => traderApi.GET("/trader/v1/limits"), {
    interval: false,
  });
  return (
    <Card title={t("trader.limits.title")}>
      <PanelBody query={query}>
        {(data) => <LimitsForm key={JSON.stringify(data.limits)} data={data} />}
      </PanelBody>
    </Card>
  );
}

function LimitsForm({ data }: { data: Limits }) {
  const { t } = useI18n();
  const save = useSaveLimits();
  const current = (name: string): string | null => data.limits?.[name] ?? null;
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(ALL_FIELDS.map((f) => [f.name, current(f.name) ?? ""])),
  );
  const [reviewing, setReviewing] = useState(false);
  const [stepUp, setStepUp] = useState(false);
  const [saved, setSaved] = useState<number | null>(null);

  const rows = useMemo(
    () =>
      ALL_FIELDS.map((field) => {
        const text = values[field.name] ?? "";
        const before = current(field.name);
        const changed = text.trim() !== (before ?? "");
        return {
          field,
          text,
          before,
          changed,
          error: problem(field, text),
          effect: changed ? effect(field, before, text) : ("neutral" as Effect),
        };
      }),
    // `current` is derived from `data`, which is the form's key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [values, data],
  );
  const changes = rows.filter((r) => r.changed);
  const invalid = rows.some((r) => r.error !== null);
  const loosens = changes.some((r) => needsStepUp(r.effect));

  const send = (grant?: string) => {
    const limits: Record<string, string | null> = {};
    for (const r of changes) limits[r.field.name] = r.text.trim() === "" ? null : r.text.trim();
    save.mutate(
      { limits, stepUp: grant },
      {
        onSuccess: (out) => {
          setSaved(out.version);
          setReviewing(false);
          setStepUp(false);
        },
        onError: () => setStepUp(false),
      },
    );
  };

  return (
    <form
      className="space-y-8"
      onSubmit={(event) => {
        event.preventDefault();
        if (changes.length > 0 && !invalid) setReviewing(true);
      }}
    >
      {GROUPS.map((group) => (
        <fieldset key={group.title} className="space-y-4">
          <legend className="mb-1 text-xs font-medium uppercase tracking-wider text-muted">
            {t(group.title)}
          </legend>
          {group.fields.map((field) => {
            const row = rows.find((r) => r.field.name === field.name)!;
            return (
              <LimitRow
                key={field.name}
                field={field}
                text={row.text}
                before={row.before}
                changed={row.changed}
                error={row.error}
                onChange={(next) => {
                  setSaved(null);
                  setValues((v) => ({ ...v, [field.name]: next }));
                }}
              />
            );
          })}
        </fieldset>
      ))}

      <p className="text-xs text-muted">
        {t("trader.limit.daily_loss_day_boundary.label")}: {t("trader.limits.readOnly")}
      </p>

      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
        <Button type="submit" disabled={changes.length === 0 || invalid}>
          {t("trader.limits.review")}
        </Button>
        <Button
          type="button"
          variant="ghost"
          disabled={changes.length === 0}
          onClick={() =>
            setValues(Object.fromEntries(ALL_FIELDS.map((f) => [f.name, current(f.name) ?? ""])))
          }
        >
          {t("trader.limits.reset")}
        </Button>
        <p className="text-sm text-muted" role="status" aria-live="polite">
          {saved !== null
            ? t("trader.limits.saved", { version: saved })
            : invalid
              ? t("trader.limits.hasErrors")
              : changes.length === 0
                ? t("trader.limits.noChanges")
                : ""}
        </p>
      </div>

      <p className="text-sm text-muted">
        {data.unset.length === 0
          ? t("trader.limits.allSet")
          : t("trader.limits.stillUnset", { count: data.unset.length })}
      </p>

      {reviewing && (
        <Modal
          title={t("trader.limits.review.title")}
          onClose={() => !save.isPending && setReviewing(false)}
          footer={
            <>
              <Button
                type="button"
                variant="ghost"
                onClick={() => setReviewing(false)}
                disabled={save.isPending}
                autoFocus
              >
                {t("common.cancel")}
              </Button>
              <Button
                type="button"
                busy={save.isPending}
                onClick={() => (loosens ? setStepUp(true) : send())}
              >
                {t("trader.limits.review.save", { count: changes.length })}
              </Button>
            </>
          }
        >
          <ul className="space-y-3">
            {changes.map((r) => (
              <ReviewLine
                key={r.field.name}
                label={t(r.field.label)}
                from={r.before === null ? t("trader.limits.unset") : r.before}
                to={r.text.trim() === "" ? t("trader.limits.unset") : r.text.trim()}
                effect={r.effect}
              />
            ))}
          </ul>
          {loosens && <p className="mt-4 text-sm text-watch">{t("trader.limits.review.loosens")}</p>}
          {save.error && (
            <p role="alert" className="mt-3 text-sm text-fall">
              {save.error.message}
            </p>
          )}
        </Modal>
      )}

      {stepUp && (
        <StepUpDialog scope="RAISE_LIMIT" onCancel={() => setStepUp(false)} onGranted={(g) => send(g)} />
      )}
    </form>
  );
}

function LimitRow({
  field,
  text,
  before,
  changed,
  error,
  onChange,
}: {
  field: LimitField;
  text: string;
  before: string | null;
  changed: boolean;
  error: MessageKey | null;
  onChange: (next: string) => void;
}) {
  const { t, locale } = useI18n();
  const id = useId();
  const describedBy = `${id}-hint ${id}-now${error ? ` ${id}-err` : ""}`;
  const shown = (v: string) => (field.kind === "idr" ? groupDigits(v, locale) : v);
  return (
    <div className="grid gap-x-6 gap-y-1 md:grid-cols-[1fr_16rem] md:items-start">
      <div>
        <label htmlFor={id} className="text-sm font-medium text-ink">
          {t(field.label)}
        </label>
        <p id={`${id}-hint`} className="mt-0.5 max-w-prose text-xs text-muted">
          {t(field.hint)} {field.optional ? t("trader.limits.emptyOptional") : t("trader.limits.emptyMeans")}
        </p>
      </div>
      <div>
        <div className="flex items-center gap-2">
          <input
            id={id}
            className={`${inputClass} font-mono tnum ${error ? "border-fall/60" : ""}`}
            inputMode={field.kind === "window" ? "text" : "decimal"}
            autoComplete="off"
            spellCheck={false}
            value={text}
            aria-invalid={error !== null}
            aria-describedby={describedBy}
            placeholder={field.kind === "window" ? "08:00-22:00" : ""}
            onChange={(e) => onChange(e.target.value)}
          />
          {field.unit && <span className="shrink-0 text-xs text-muted">{t(field.unit)}</span>}
        </div>
        <p id={`${id}-now`} className="mt-1 text-xs text-muted">
          {before === null ? t("trader.limits.currentUnset") : t("trader.limits.current", { value: shown(before) })}
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

function ReviewLine({
  label,
  from,
  to,
  effect: e,
}: {
  label: string;
  from: string;
  to: string;
  effect: Effect;
}) {
  const { t } = useI18n();
  const tag = EFFECT_LABEL[e];
  return (
    <li className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-line pb-2 last:border-0">
      <span className="text-sm text-ink">{label}</span>
      <span className="font-mono text-xs tnum text-muted">{t("trader.limits.review.change", { from, to })}</span>
      {tag && (
        <span
          className={`w-full text-xs font-medium ${e === "looser" || e === "enabled" ? "text-watch" : e === "cleared" ? "text-fall" : "text-muted"}`}
        >
          {t(tag)}
        </span>
      )}
    </li>
  );
}

// ---------------------------------------------------------------- allowlist

function AllowlistEditor() {
  const { t } = useI18n();
  const query = useTraderQuery<Allowlist>(["allowlist"], () => traderApi.GET("/trader/v1/allowlist"), {
    interval: false,
  });
  return (
    <Card title={t("trader.allow.title")}>
      <PanelBody query={query}>
        {(data) => <AllowlistForm key={JSON.stringify(data)} data={data} />}
      </PanelBody>
    </Card>
  );
}

function AllowlistForm({ data }: { data: Allowlist }) {
  const { t, locale } = useI18n();
  const save = useSaveAllowlist();
  const catalogQuery = useTraderQuery<PairCatalog>(
    ["pairs-catalog"],
    () => traderApi.GET("/trader/v1/pairs-catalog"),
    { interval: 60_000 },
  );
  const groupsQuery = useTraderQuery<PairGroups>(
    ["pair-groups"],
    () => traderApi.GET("/trader/v1/pair-groups"),
    { interval: false },
  );
  const saveGroups = useSavePairGroups();
  const [selected, setSelected] = useState<string[]>([...data.pairs].sort());
  const [pairsText, setPairsText] = useState(data.pairs.join(", "));
  const [allPairs, setAllPairs] = useState(data.all_pairs);
  const [maxPairsText, setMaxPairsText] = useState(data.max_pairs === null ? "" : String(data.max_pairs));
  const [minVolume, setMinVolume] = useState(data.min_quote_volume_24h_idr ?? "");
  const [maxSpread, setMaxSpread] = useState(data.max_spread_pct ?? "");
  const [reviewing, setReviewing] = useState(false);
  const [stepUp, setStepUp] = useState(false);
  const [done, setDone] = useState(false);

  const pairs = selected;
  const pairsBad = pairs.some((p) => !PAIR.test(p));
  const maxPairsBad =
    maxPairsText.trim() !== "" &&
    !(/^\d{1,3}$/.test(maxPairsText.trim()) && +maxPairsText >= 1 && +maxPairsText <= MAX_ALL_PAIRS);
  const maxPairs = maxPairsText.trim() === "" || maxPairsBad ? null : Number(maxPairsText.trim());
  const volBad = minVolume.trim() !== "" && !(DECIMAL.test(minVolume.trim()) && compareDecimals(minVolume.trim(), "0") > 0);
  const spreadBad =
    maxSpread.trim() !== "" &&
    !(DECIMAL.test(maxSpread.trim()) && compareDecimals(maxSpread.trim(), "0") > 0 && compareDecimals(maxSpread.trim(), "100") <= 0);
  const invalid = pairsBad || volBad || spreadBad || maxPairsBad;

  const before = { pairs: data.pairs, vol: data.min_quote_volume_24h_idr, spread: data.max_spread_pct };
  const next = { vol: minVolume.trim() || null, spread: maxSpread.trim() || null };
  const changed =
    pairs.join(",") !== [...before.pairs].sort().join(",") ||
    next.vol !== before.vol ||
    next.spread !== before.spread ||
    allPairs !== data.all_pairs ||
    maxPairs !== data.max_pairs;

  const prevSnap = {
    pairs: before.pairs,
    minVolume: before.vol,
    maxSpread: before.spread,
    allPairs: data.all_pairs,
    maxPairs: data.max_pairs,
  };
  const nextSnap = { pairs, minVolume: next.vol, maxSpread: next.spread, allPairs, maxPairs };
  const loosens = allowlistLoosens(prevSnap, nextSnap);
  const rowEffects = allowlistEffects(prevSnap, nextSnap);

  const send = (grant?: string) =>
    save.mutate(
      { pairs, minVolume: next.vol, maxSpread: next.spread, allPairs, maxPairs, stepUp: grant },
      {
        onSuccess: () => {
          setDone(true);
          setReviewing(false);
          setStepUp(false);
        },
        onError: () => setStepUp(false),
      },
    );

  const status = data.active
    ? t("trader.allow.active")
    : data.pairs.length === 0 && !data.all_pairs
      ? t("trader.allow.inactive.noPairs")
      : data.all_pairs && data.max_pairs === null
        ? t("trader.allow.inactive.noN")
        : t("trader.allow.inactive.noFilter");
  const list = (p: string[]) => (p.length ? p.join(", ") : t("trader.allow.empty"));
  const num = (v: string | null) => (v === null ? t("trader.limits.unset") : groupDigits(v, locale));
  const allText = (on: boolean, n: number | null) =>
    !on ? t("trader.allow.all.off") : n === null ? t("trader.allow.all.noN") : t("trader.allow.all.on", { n });

  return (
    <form
      className="space-y-5"
      onSubmit={(event) => {
        event.preventDefault();
        if (changed && !invalid) setReviewing(true);
      }}
    >
      <p className="max-w-prose text-sm text-muted">{t("trader.allow.intro")}</p>
      <fieldset className="space-y-3">
        <legend className="mb-1.5 text-xs font-medium text-muted">{t("trader.allow.pairs")}</legend>
        <PairPicker
          catalog={catalogQuery.data?.data.pairs ?? null}
          catalogError={catalogQuery.isError ? catalogQuery.error.message : null}
          selected={selected}
          onChange={(next) => {
            setDone(false);
            setSelected(next);
            setPairsText(next.join(", "));
          }}
          groups={groupsQuery.data?.data.groups ?? []}
          onSaveGroups={(groups) => saveGroups.mutate(groups)}
          groupsBusy={saveGroups.isPending}
          groupsError={saveGroups.error?.message ?? null}
        />
        {catalogQuery.isError && (
          <Field label={t("trader.allow.manual")}>
            <input
              className={`${inputClass} font-mono`}
              value={pairsText}
              spellCheck={false}
              autoComplete="off"
              aria-invalid={pairsBad}
              onChange={(e) => {
                setDone(false);
                setPairsText(e.target.value);
                setSelected(parsePairs(e.target.value));
              }}
            />
          </Field>
        )}
      </fieldset>
      <div className="space-y-2 rounded-md border border-line p-3">
        <label className="flex cursor-pointer items-start gap-3 text-sm">
          <input
            type="checkbox"
            className="mt-0.5 h-4 w-4 shrink-0"
            checked={allPairs}
            onChange={(e) => {
              setDone(false);
              setAllPairs(e.target.checked);
            }}
          />
          <span>
            <span className="font-medium text-ink">{t("trader.allow.all.label")}</span>
            <span className="mt-0.5 block text-xs text-muted">{t("trader.allow.all.hint")}</span>
          </span>
        </label>
        {allPairs && (
          <div className="max-w-xs">
            <Field label={t("trader.allow.all.max")}>
              <input
                className={`${inputClass} font-mono tnum`}
                inputMode="numeric"
                value={maxPairsText}
                aria-invalid={maxPairsBad}
                onChange={(e) => {
                  setDone(false);
                  setMaxPairsText(e.target.value);
                }}
              />
              <span className="mt-1 block text-xs text-muted">{t("trader.allow.all.maxHint", { max: MAX_ALL_PAIRS })}</span>
            </Field>
            {maxPairsBad && (
              <p role="alert" className="mt-1 text-xs text-fall">
                {t("trader.allow.all.invalid", { max: MAX_ALL_PAIRS })}
              </p>
            )}
          </div>
        )}
      </div>
      {pairsBad && (
        <p role="alert" className="text-xs text-fall">
          {t("trader.allow.invalid.pairs")}
        </p>
      )}
      <div className="grid gap-5 sm:grid-cols-2">
        <Field label={t("trader.allow.minVolume")}>
          <input
            className={`${inputClass} font-mono tnum`}
            inputMode="decimal"
            value={minVolume}
            aria-invalid={volBad}
            onChange={(e) => {
              setDone(false);
              setMinVolume(e.target.value);
            }}
          />
          <span className="mt-1 block text-xs text-muted">{t("trader.limits.emptyMeans")}</span>
        </Field>
        <Field label={t("trader.allow.maxSpread")}>
          <input
            className={`${inputClass} font-mono tnum`}
            inputMode="decimal"
            value={maxSpread}
            aria-invalid={spreadBad}
            onChange={(e) => {
              setDone(false);
              setMaxSpread(e.target.value);
            }}
          />
          <span className="mt-1 block text-xs text-muted">{t("trader.limits.emptyMeans")}</span>
        </Field>
      </div>
      {volBad && (
        <p role="alert" className="text-xs text-fall">
          {t("trader.limits.invalid.number")}
        </p>
      )}
      {spreadBad && (
        <p role="alert" className="text-xs text-fall">
          {t("trader.limits.invalid.pct")}
        </p>
      )}

      <p className={`text-sm ${data.active ? "text-muted" : "text-watch"}`}>{status}</p>

      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
        <Button type="submit" disabled={!changed || invalid}>
          {t("trader.allow.save")}
        </Button>
        <p className="text-sm text-muted" role="status" aria-live="polite">
          {done ? t("trader.allow.saved") : !changed ? t("trader.limits.noChanges") : ""}
        </p>
      </div>

      {reviewing && (
        <Modal
          title={t("trader.allow.review.title")}
          onClose={() => !save.isPending && setReviewing(false)}
          footer={
            <>
              <Button type="button" variant="ghost" autoFocus onClick={() => setReviewing(false)} disabled={save.isPending}>
                {t("common.cancel")}
              </Button>
              <Button type="button" busy={save.isPending} onClick={() => (loosens ? setStepUp(true) : send())}>
                {t("trader.allow.save")}
              </Button>
            </>
          }
        >
          <ul className="space-y-3">
            <ReviewLine label={t("trader.allow.pairs")} from={list(before.pairs)} to={list(pairs)} effect={rowEffects.pairs} />
            <ReviewLine
              label={t("trader.allow.all.label")}
              from={allText(data.all_pairs, data.max_pairs)}
              to={allText(allPairs, maxPairs)}
              effect={rowEffects.allPairs}
            />
            <ReviewLine label={t("trader.allow.minVolume")} from={num(before.vol)} to={num(next.vol)} effect={rowEffects.minVolume} />
            <ReviewLine label={t("trader.allow.maxSpread")} from={num(before.spread)} to={num(next.spread)} effect={rowEffects.maxSpread} />
          </ul>
          {loosens && <p className="mt-4 text-sm text-watch">{t("trader.allow.review.loosens")}</p>}
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
