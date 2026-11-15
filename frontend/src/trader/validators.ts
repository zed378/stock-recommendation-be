import type { MessageKey } from "@/i18n/context";
import { compareDecimals, DECIMAL } from "@/trader/format";
import type { PaperValues } from "@/trader/mutations";

export type ParamKind = "int" | "int0" | "threshold" | "multiple";

export interface ParamField {
  name: string;
  kind: ParamKind;
  unit: MessageKey | null;
  label: MessageKey;
  hint: MessageKey;
}

export const PARAM_FIELDS: ParamField[] = [
  { name: "ema_fast", kind: "int", unit: null, label: "trader.params.field.ema_fast.label", hint: "trader.params.field.ema_fast.hint" },
  { name: "ema_slow", kind: "int", unit: null, label: "trader.params.field.ema_slow.label", hint: "trader.params.field.ema_slow.hint" },
  { name: "adx_period", kind: "int", unit: null, label: "trader.params.field.adx_period.label", hint: "trader.params.field.adx_period.hint" },
  { name: "adx_threshold", kind: "threshold", unit: null, label: "trader.params.field.adx_threshold.label", hint: "trader.params.field.adx_threshold.hint" },
  { name: "atr_period", kind: "int", unit: null, label: "trader.params.field.atr_period.label", hint: "trader.params.field.atr_period.hint" },
  { name: "atr_stop_multiple", kind: "multiple", unit: null, label: "trader.params.field.atr_stop_multiple.label", hint: "trader.params.field.atr_stop_multiple.hint" },
  { name: "cooldown_s", kind: "int0", unit: "trader.unit.seconds", label: "trader.params.field.cooldown_s.label", hint: "trader.params.field.cooldown_s.hint" },
];

/** Mirrors `EmaAdxParams` validation on the server, which answers last. */
export function paramProblem(kind: ParamKind, text: string): MessageKey | null {
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

export function emaOrderBad(emaFast: string | undefined, emaSlow: string | undefined): boolean {
  const f = emaFast?.trim() ?? "";
  const s = emaSlow?.trim() ?? "";
  return /^\d+$/.test(f) && /^\d+$/.test(s) && Number(f) >= Number(s);
}

/** Candles of history the strategy needs: the longest of its look-backs (see `min_history`). */
export function neededHistory(values: Record<string, string>): number | null {
  const n = (k: string) => (/^\d+$/.test(values[k]?.trim() ?? "") ? Number(values[k].trim()) : null);
  const slow = n("ema_slow");
  const adx = n("adx_period");
  const atr = n("atr_period");
  if (slow === null || adx === null || atr === null) return null;
  return Math.max(slow, 2 * adx + 1, atr + 1);
}

export type PaperKind = "pct" | "fraction" | "idr";
export type PaperName = keyof PaperValues;
export type PaperEffect = "flatters" | "harsher" | "neutral";

export interface PaperField {
  name: PaperName;
  kind: PaperKind;
  unit: MessageKey | null;
  label: MessageKey;
  hint: MessageKey;
  /** Which way flatters the simulated results: lower costs, or more of an order filled. */
  flatters: "lower" | "higher" | null;
}

export const PAPER_FIELDS: PaperField[] = [
  { name: "start_equity_idr", kind: "idr", unit: "trader.unit.idr", label: "trader.paper.start.label", hint: "trader.paper.start.hint", flatters: null },
  { name: "slippage_pct", kind: "pct", unit: "trader.unit.pct", label: "trader.paper.slippage.label", hint: "trader.paper.slippage.hint", flatters: "lower" },
  { name: "partial_fill_fraction", kind: "fraction", unit: null, label: "trader.paper.fraction.label", hint: "trader.paper.fraction.hint", flatters: "higher" },
  { name: "maker_fee_pct", kind: "pct", unit: "trader.unit.pct", label: "trader.paper.maker.label", hint: "trader.paper.maker.hint", flatters: "lower" },
  { name: "taker_fee_pct", kind: "pct", unit: "trader.unit.pct", label: "trader.paper.taker.label", hint: "trader.paper.taker.hint", flatters: "lower" },
  { name: "tax_pct", kind: "pct", unit: "trader.unit.pct", label: "trader.paper.tax.label", hint: "trader.paper.tax.hint", flatters: "lower" },
  { name: "clearing_pct", kind: "pct", unit: "trader.unit.pct", label: "trader.paper.clearing.label", hint: "trader.paper.clearing.hint", flatters: "lower" },
];

/** Mirrors `set_paper_settings` on the server, which answers last. Empty is reported once. */
export function paperProblem(kind: PaperKind, text: string): MessageKey | null {
  const v = text.trim();
  if (v === "") return null;
  if (!DECIMAL.test(v))
    return kind === "idr"
      ? "trader.paper.invalid.idr"
      : kind === "pct"
        ? "trader.paper.invalid.pct"
        : "trader.paper.invalid.fraction";
  switch (kind) {
    case "pct":
      return compareDecimals(v, "100") <= 0 ? null : "trader.paper.invalid.pct";
    case "fraction":
      return compareDecimals(v, "0") > 0 && compareDecimals(v, "1") <= 0 ? null : "trader.paper.invalid.fraction";
    case "idr":
      return compareDecimals(v, "0") > 0 ? null : "trader.paper.invalid.idr";
  }
}

/** Whether a change makes simulated results look better; mirrors `paper_flatters` on the server. */
export function paperEffect(field: PaperField, from: string, to: string): PaperEffect {
  if (field.flatters === null || from === "" || !DECIMAL.test(to.trim())) return "neutral";
  const c = compareDecimals(to.trim(), from);
  if (c === 0) return "neutral";
  return (c > 0) === (field.flatters === "higher") ? "flatters" : "harsher";
}

/** Whether any field change across the paper assumptions flatters results (mirrors `paper_flatters` in `settings_store.py`). */
export function paperFlatters(
  before: Record<PaperName, string>,
  after: Record<PaperName, string>,
): boolean {
  return PAPER_FIELDS.some((f) => paperEffect(f, before[f.name] ?? "", after[f.name] ?? "") === "flatters");
}
