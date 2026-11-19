import { useMemo, useState } from "react";
import { useI18n, type MessageKey } from "@/i18n/context";
import { Button, Field, inputClass, Modal } from "@/components/primitives";
import { useSaveStrategyDef } from "@/trader/mutations";
import type { StrategyKind } from "@/trader/types";

const ID_PATTERN = /^[a-z][a-z0-9_]{1,31}$/;

export interface BuilderStart {
  /** Set when editing: the id and kind are fixed, the name and numbers change. */
  existing: boolean;
  id: string;
  label: string;
  kind: string;
  params: Record<string, string>;
}

/**
 * Create, duplicate or edit a strategy from one of the rule shapes the Trader offers.
 *
 * A strategy here is a kind plus numbers, never code. The suggested value beside each field is a
 * starting point to copy, not a default: nothing is saved that was not typed or copied by the
 * owner, and the server checks every number again.
 */
export function StrategyBuilder({
  kinds,
  start,
  onClose,
  onSaved,
}: {
  kinds: StrategyKind[];
  start: BuilderStart;
  onClose: () => void;
  onSaved: (id: string) => void;
}) {
  const { t } = useI18n();
  const save = useSaveStrategyDef();
  const [kind, setKind] = useState(start.kind || kinds[0]?.kind || "");
  const [id, setId] = useState(start.id);
  const [label, setLabel] = useState(start.label);
  const [params, setParams] = useState<Record<string, string>>(start.params);
  const spec = useMemo(() => kinds.find((k) => k.kind === kind), [kinds, kind]);

  const idProblem = !start.existing && id !== "" && !ID_PATTERN.test(id);
  const missing = spec ? spec.fields.some((f) => (params[f.name] ?? "").trim() === "") : true;
  const canSave =
    spec !== undefined && !missing && label.trim() !== "" && ID_PATTERN.test(id) && !save.isPending;

  const submit = () => {
    if (!spec || !canSave) return;
    const clean = Object.fromEntries(spec.fields.map((f) => [f.name, params[f.name].trim()]));
    save.mutate(
      { id, label: label.trim(), kind, params: clean, existing: start.existing },
      { onSuccess: (saved) => onSaved(saved.id) },
    );
  };

  return (
    <Modal
      title={start.existing ? t("trader.strat.builder.editTitle") : t("trader.strat.builder.createTitle")}
      onClose={() => !save.isPending && onClose()}
      footer={
        <>
          <Button type="button" variant="ghost" onClick={onClose} disabled={save.isPending}>
            {t("common.cancel")}
          </Button>
          <Button type="button" busy={save.isPending} disabled={!canSave} onClick={submit}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        {!start.existing && (
          <Field label={t("trader.strat.builder.kind")}>
            <select
              className={inputClass}
              value={kind}
              onChange={(e) => {
                setKind(e.target.value);
                setParams({});
              }}
            >
              {kinds.map((k) => (
                <option key={k.kind} value={k.kind}>
                  {t(`trader.strat.kind.${k.kind}` as MessageKey)}
                </option>
              ))}
            </select>
          </Field>
        )}
        {spec && (
          <p className="text-xs text-muted">{t(`trader.strat.kind.${spec.kind}.desc` as MessageKey)}</p>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("trader.strat.builder.id")} hint={t("trader.strat.builder.idHint")}>
            <input
              className={`${inputClass} font-mono`}
              value={id}
              disabled={start.existing}
              spellCheck={false}
              autoComplete="off"
              aria-invalid={idProblem}
              onChange={(e) => setId(e.target.value)}
            />
          </Field>
          <Field label={t("trader.strat.builder.label")}>
            <input
              className={inputClass}
              value={label}
              maxLength={60}
              autoComplete="off"
              onChange={(e) => setLabel(e.target.value)}
            />
          </Field>
        </div>
        {idProblem && (
          <p role="alert" className="text-xs text-fall">
            {t("trader.strat.builder.idInvalid")}
          </p>
        )}

        {spec && (
          <div className="space-y-3 border-t border-line pt-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-medium text-ink">{t("trader.strat.params")}</h3>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() =>
                  setParams((prev) => ({
                    ...Object.fromEntries(spec.fields.map((f) => [f.name, f.suggested])),
                    ...Object.fromEntries(Object.entries(prev).filter(([, v]) => v.trim() !== "")),
                  }))
                }
              >
                {t("trader.strat.builder.fill")}
              </Button>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              {spec.fields.map((f) => (
                <Field
                  key={f.name}
                  label={f.name}
                  hint={t("trader.strat.builder.range", {
                    suggested: f.suggested,
                    min: f.minimum,
                    max: f.maximum,
                  })}
                >
                  <input
                    className={`${inputClass} font-mono tnum`}
                    inputMode="decimal"
                    autoComplete="off"
                    spellCheck={false}
                    value={params[f.name] ?? ""}
                    onChange={(e) => setParams((prev) => ({ ...prev, [f.name]: e.target.value }))}
                  />
                </Field>
              ))}
            </div>
            <p className="text-xs text-faint">{t("trader.strat.builder.noDefaults")}</p>
          </div>
        )}
        {save.error && (
          <p role="alert" className="text-sm text-fall">
            {save.error.message}
          </p>
        )}
      </form>
    </Modal>
  );
}
