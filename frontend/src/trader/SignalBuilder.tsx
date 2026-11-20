import { useState } from "react";
import { Button, Field, Modal, inputClass } from "@/components/primitives";
import { useI18n, type MessageKey } from "@/i18n/context";
import { useSaveStrategyDef } from "@/trader/mutations";
import type { BuilderStart } from "@/trader/StrategyBuilder";

type Indicator = "close" | "constant" | "ema" | "rsi" | "adx" | "volume_ratio";
interface Operand { indicator: Indicator; period?: number; value?: string }
interface Rule { name: string; left: Operand; operator: string; right: Operand }
interface Group { mode: "ALL" | "ANY"; rules: Rule[] }
interface Definition {
  exchange: "INDODAX"; quote: "IDR"; timeframe: "4H" | "1D";
  entry: Group; exit: Group;
  [key: string]: unknown;
}
const INTEGER_FIELDS = new Set([
  "atr_period", "cooldown_s", "max_data_age_seconds", "max_review_age_seconds",
  "forecast_bars", "forecast_samples", "ai_min_score",
]);
const NUMBERS = [
  "atr_period", "atr_stop_multiple", "cooldown_s", "max_data_age_seconds",
  "max_review_age_seconds", "forecast_bars", "forecast_samples",
  "min_projected_return_pct", "ai_min_score",
] as const;
const rule = (name: string): Rule => ({
  name, left: { indicator: "close" }, operator: "gt", right: { indicator: "constant", value: "" },
});
const initial = (start: BuilderStart): Definition => {
  if (start.params.definition) return JSON.parse(start.params.definition) as Definition;
  return { exchange: "INDODAX", quote: "IDR", timeframe: "4H",
    entry: { mode: "ALL", rules: [rule("Entry 1")] },
    exit: { mode: "ALL", rules: [rule("Exit 1")] } };
};
const operandReady = (op: Operand) => op.indicator === "close" ||
  (op.indicator === "constant" ? /^-?\d+(\.\d+)?$/.test(op.value ?? "") :
    Number.isInteger(op.period) && (op.period ?? 0) >= 2);

export function SignalBuilder({ start, onClose, onSaved }: {
  start: BuilderStart; onClose: () => void; onSaved: (id: string) => void;
}) {
  const { t } = useI18n();
  const save = useSaveStrategyDef();
  const [id, setId] = useState(start.id);
  const [label, setLabel] = useState(start.label);
  const [definition, setDefinition] = useState<Definition>(() => initial(start));
  const [numbers, setNumbers] = useState<Record<string, string>>(() => {
    const d = initial(start);
    return Object.fromEntries(NUMBERS.map((key) => [key, d[key] == null ? "" : String(d[key])]));
  });
  const canSave = /^[a-z][a-z0-9_]{1,31}$/.test(id) && label.trim() !== "" &&
    NUMBERS.every((k) => (INTEGER_FIELDS.has(k) ? /^\d+$/ : /^-?\d+(\.\d+)?$/).test(numbers[k])) &&
    [definition.entry, definition.exit].every((g) => g.rules.length > 0 &&
      g.rules.every((r) => operandReady(r.left) && operandReady(r.right))) && !save.isPending;
  const submit = () => {
    if (!canSave) return;
    const numeric = Object.fromEntries(NUMBERS.map((key) => [key,
      INTEGER_FIELDS.has(key) ? Number(numbers[key]) : numbers[key],
    ]));
    save.mutate({ id, label: label.trim(), kind: "signal_builder", existing: start.existing,
      params: { definition: JSON.stringify({ ...definition, ...numeric }) },
    }, { onSuccess: (saved) => onSaved(saved.id) });
  };
  return <Modal wide title={t("builder.title")} onClose={() => !save.isPending && onClose()}
    footer={<><Button variant="ghost" disabled={save.isPending} onClick={onClose}>{t("common.cancel")}</Button>
      <Button disabled={!canSave} busy={save.isPending} onClick={submit}>{t("common.save")}</Button></>}>
    <form className="space-y-5" onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <p className="text-sm text-muted">{t("builder.scope")}</p>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("trader.strat.builder.id")} hint={t("trader.strat.builder.idHint")}><input className={inputClass} value={id}
          disabled={start.existing || save.isPending} onChange={(e) => setId(e.target.value)} /></Field>
        <Field label={t("trader.strat.builder.label")}><input className={inputClass} value={label}
          maxLength={60} onChange={(e) => setLabel(e.target.value)} /></Field>
        <Field label={t("builder.timeframe")}><select className={inputClass} value={definition.timeframe}
          onChange={(e) => setDefinition({ ...definition, timeframe: e.target.value as "4H" | "1D" })}>
          <option value="4H">4H</option><option value="1D">1D</option>
        </select></Field>
      </div>
      {(["entry", "exit"] as const).map((side) => <RuleGroupEditor key={side}
        title={t(`builder.${side}`)} group={definition[side]}
        onChange={(group) => setDefinition({ ...definition, [side]: group })} />)}
      <fieldset className="grid gap-4 border-t border-line pt-4 sm:grid-cols-2">
        <legend className="text-sm font-medium">{t("builder.parameters")}</legend>
        {NUMBERS.map((key) => <Field key={key} label={t(`builder.${key}` as MessageKey)}>
          <input className={inputClass} inputMode={INTEGER_FIELDS.has(key) ? "numeric" : "decimal"}
            value={numbers[key]} onChange={(e) => setNumbers({ ...numbers, [key]: e.target.value })} />
        </Field>)}
      </fieldset>
      <p className="text-xs text-muted">{t("builder.noDefaults")}</p>
      {save.error && <p role="alert" className="text-sm text-fall">{save.error.message}</p>}
    </form>
  </Modal>;
}

function RuleGroupEditor({ title, group, onChange }: {
  title: string; group: Group; onChange: (g: Group) => void;
}) {
  const { t } = useI18n();
  const update = (index: number, value: Rule) => onChange({ ...group,
    rules: group.rules.map((r, i) => i === index ? value : r),
  });
  return <fieldset className="space-y-3 rounded border border-line p-3">
    <legend className="px-1 text-sm font-medium">{title}</legend>
    <Field label={t("builder.match")}><select className={inputClass} value={group.mode}
      onChange={(e) => onChange({ ...group, mode: e.target.value as "ALL" | "ANY" })}>
      <option value="ALL">{t("builder.all")}</option><option value="ANY">{t("builder.any")}</option>
    </select></Field>
    {group.rules.map((r, index) => <div key={index} className="space-y-2 border-t border-line pt-3">
      <div className="grid gap-2 sm:grid-cols-3">
        <OperandEditor label={t("builder.left")} value={r.left}
          onChange={(left) => update(index, { ...r, left })} />
        <Field label={t("builder.comparison")}><select className={inputClass} value={r.operator}
          onChange={(e) => update(index, { ...r, operator: e.target.value })}>
          {["gt", "gte", "lt", "lte", "crosses_above", "crosses_below"].map((op) =>
            <option key={op} value={op}>{t(`builder.op.${op}` as MessageKey)}</option>)}
        </select></Field>
        <OperandEditor label={t("builder.right")} value={r.right}
          onChange={(right) => update(index, { ...r, right })} />
      </div>
      <Button type="button" size="sm" variant="ghost" disabled={group.rules.length === 1}
        onClick={() => onChange({ ...group, rules: group.rules.filter((_, i) => i !== index) })}>
        {t("builder.remove")}</Button>
    </div>)}
    <Button type="button" size="sm" disabled={group.rules.length >= 32}
      onClick={() => onChange({ ...group, rules: [...group.rules,
        rule(`Rule ${Date.now()}`)] })}>{t("builder.add")}</Button>
  </fieldset>;
}

function OperandEditor({ label, value, onChange }: {
  label: string; value: Operand; onChange: (v: Operand) => void;
}) {
  const { t } = useI18n();
  return <div className="space-y-2"><Field label={label}>
    <select className={inputClass} value={value.indicator} onChange={(e) => {
      const indicator = e.target.value as Indicator;
      onChange(indicator === "constant" ? { indicator, value: "" } : { indicator });
    }}>{["close", "constant", "ema", "rsi", "adx", "volume_ratio"].map((indicator) =>
      <option key={indicator} value={indicator}>{t(`builder.ind.${indicator}` as MessageKey)}</option>)}
    </select></Field>
    {value.indicator === "constant" && <Field label={t("builder.value")}>
      <input className={inputClass} inputMode="decimal" value={value.value ?? ""}
        onChange={(e) => onChange({ ...value, value: e.target.value })} /></Field>}
    {!["constant", "close"].includes(value.indicator) && <Field label={t("builder.period")}>
      <input className={inputClass} inputMode="numeric" value={value.period ?? ""}
        onChange={(e) => onChange({ indicator: value.indicator,
          period: /^\d+$/.test(e.target.value) ? Number(e.target.value) : undefined })} /></Field>}
  </div>;
}
