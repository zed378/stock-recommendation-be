import { useEffect, useMemo, useRef, useState } from "react";
import { useI18n } from "@/i18n/context";
import { Button, inputClass } from "@/components/primitives";
import { groupDigits } from "@/trader/format";
import {
  groupNameProblem,
  groupState,
  removeGroup,
  toggleGroup,
  upsertGroup,
  type PairGroup,
} from "@/trader/pairGroups";
import type { CatalogPair } from "@/trader/types";

interface Props {
  /** Every IDR market the exchange lists; null while unavailable. */
  catalog: CatalogPair[] | null;
  /** Why the list is unavailable, when it is. */
  catalogError: string | null;
  selected: string[];
  onChange: (pairs: string[]) => void;
  groups: PairGroup[];
  onSaveGroups: (groups: PairGroup[]) => void;
  groupsBusy: boolean;
  groupsError: string | null;
}

/**
 * Choose pairs from the exchange's whole list, and keep named groups of them.
 *
 * A group is a shortcut: ticking it ticks its pairs here, and nothing trades until the owner
 * saves the allowlist (which asks for a password when it adds anything). Editing a group never
 * changes what is already allowed.
 */
export function PairPicker({
  catalog,
  catalogError,
  selected,
  onChange,
  groups,
  onSaveGroups,
  groupsBusy,
  groupsError,
}: Props) {
  const { t, locale } = useI18n();
  const [query, setQuery] = useState("");
  const [name, setName] = useState("");
  const selectedSet = useMemo(() => new Set(selected), [selected]);

  const rows = useMemo(() => {
    const q = query.trim().toUpperCase();
    return (catalog ?? []).filter((r) => q === "" || r.pair.includes(q) || r.asset.toUpperCase().includes(q));
  }, [catalog, query]);

  const known = useMemo(() => new Set((catalog ?? []).map((r) => r.pair)), [catalog]);
  const orphans = catalog ? selected.filter((p) => !known.has(p)) : [];

  const toggle = (pair: string) => {
    const next = new Set(selectedSet);
    if (next.has(pair)) next.delete(pair);
    else next.add(pair);
    onChange([...next].sort());
  };

  const nameProblem = name.trim() === "" ? null : groupNameProblem(name);
  const existing = groups.find((g) => g.name.toLowerCase() === name.replace(/\s+/g, " ").trim().toLowerCase());
  const canSaveGroup = selected.length > 0 && name.trim() !== "" && nameProblem === null && !groupsBusy;

  return (
    <div className="space-y-4">
      {catalog === null ? (
        <p role="status" className="rounded-md border border-line p-3 text-sm text-muted">
          {catalogError ?? t("trader.picker.loading")}
        </p>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <label className="min-w-[12rem] flex-1">
              <span className="mb-1.5 block text-xs font-medium text-muted">{t("trader.picker.search")}</span>
              <input
                className={`${inputClass} font-mono`}
                value={query}
                spellCheck={false}
                autoComplete="off"
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => onChange([...new Set([...selected, ...rows.map((r) => r.pair)])].sort())}
              disabled={rows.length === 0}
            >
              {t("trader.picker.selectVisible", { n: rows.length })}
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => onChange([])} disabled={selected.length === 0}>
              {t("trader.picker.clear")}
            </Button>
          </div>
          <p className="text-xs text-muted" role="status" aria-live="polite">
            {t("trader.picker.selected", { n: selected.length, total: catalog.length })}
          </p>
          <div
            className="max-h-72 overflow-auto rounded-md border border-line"
            role="group"
            aria-label={t("trader.picker.list")}
          >
            {rows.length === 0 ? (
              <p className="p-3 text-sm text-muted">{t("trader.picker.noMatch")}</p>
            ) : (
              <ul className="divide-y divide-line">
                {rows.map((r) => (
                  <li key={r.pair}>
                    <label className="flex min-h-9 cursor-pointer items-center gap-3 px-3 py-1.5 text-sm hover:bg-hover max-sm:min-h-11">
                      <input
                        type="checkbox"
                        className="h-4 w-4 shrink-0"
                        checked={selectedSet.has(r.pair)}
                        onChange={() => toggle(r.pair)}
                      />
                      <span className="w-24 shrink-0 font-mono text-ink">{r.pair}</span>
                      <span className="tnum min-w-0 flex-1 truncate text-right font-mono text-xs text-muted">
                        {r.quote_volume_24h_idr ? groupDigits(r.quote_volume_24h_idr, locale) : "—"}
                      </span>
                      <span className="tnum hidden w-16 shrink-0 text-right font-mono text-xs text-muted sm:inline">
                        {r.spread_pct ? `${r.spread_pct}%` : "—"}
                      </span>
                      {!r.trading && <span className="shrink-0 text-xs text-watch">{t("trader.picker.notTrading")}</span>}
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <p className="text-xs text-faint">{t("trader.picker.columns")}</p>
          {orphans.length > 0 && (
            <p className="text-xs text-watch" role="status">
              {t("trader.picker.orphans", { pairs: orphans.join(", ") })}
            </p>
          )}
        </div>
      )}

      <section aria-labelledby="pair-groups-title" className="space-y-3 border-t border-line pt-4">
        <h3 id="pair-groups-title" className="text-sm font-semibold text-ink">
          {t("trader.groups.title")}
        </h3>
        <p className="max-w-prose text-xs text-muted">{t("trader.groups.hint")}</p>
        {groups.length === 0 ? (
          <p className="text-sm text-muted">{t("trader.groups.empty")}</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {groups.map((g) => (
              <GroupChip
                key={g.name}
                group={g}
                state={groupState(g, selectedSet)}
                onToggle={() => onChange(toggleGroup(g, selected, groups))}
                onDelete={() => onSaveGroups(removeGroup(groups, g.name))}
                disabled={groupsBusy}
              />
            ))}
          </ul>
        )}
        <div className="flex flex-wrap items-end gap-3">
          <label className="min-w-[12rem] flex-1">
            <span className="mb-1.5 block text-xs font-medium text-muted">{t("trader.groups.name")}</span>
            <input
              className={inputClass}
              value={name}
              maxLength={60}
              autoComplete="off"
              aria-invalid={nameProblem !== null}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <Button
            type="button"
            variant="ghost"
            busy={groupsBusy}
            disabled={!canSaveGroup}
            onClick={() => {
              onSaveGroups(upsertGroup(groups, name, selected));
              setName("");
            }}
          >
            {existing ? t("trader.groups.update") : t("trader.groups.create")}
          </Button>
        </div>
        {nameProblem && (
          <p role="alert" className="text-xs text-fall">
            {t("trader.groups.invalidName")}
          </p>
        )}
        {selected.length === 0 && <p className="text-xs text-faint">{t("trader.groups.needSelection")}</p>}
        {groupsError && (
          <p role="alert" className="text-xs text-fall">
            {groupsError}
          </p>
        )}
      </section>
    </div>
  );
}

function GroupChip({
  group,
  state,
  onToggle,
  onDelete,
  disabled,
}: {
  group: PairGroup;
  state: "all" | "some" | "none";
  onToggle: () => void;
  onDelete: () => void;
  disabled: boolean;
}) {
  const { t } = useI18n();
  const box = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (box.current) box.current.indeterminate = state === "some";
  }, [state]);
  return (
    <li className="flex items-center gap-1 rounded-md border border-line pl-3">
      <label className="flex min-h-9 cursor-pointer items-center gap-2 text-sm max-sm:min-h-11">
        <input ref={box} type="checkbox" className="h-4 w-4" checked={state === "all"} onChange={onToggle} />
        <span className="text-ink">{group.name}</span>
        <span className="tnum text-xs text-muted">{group.pairs.length}</span>
      </label>
      <button
        type="button"
        className="px-2.5 py-1 text-muted hover:text-fall focus-visible:outline-2 focus-visible:outline-rise max-sm:min-h-11"
        aria-label={t("trader.groups.delete", { name: group.name })}
        title={group.pairs.join(", ")}
        disabled={disabled}
        onClick={onDelete}
      >
        ×
      </button>
    </li>
  );
}
