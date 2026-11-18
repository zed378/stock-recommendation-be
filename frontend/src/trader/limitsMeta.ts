import type { MessageKey } from "@/i18n/context";
import { compareDecimals, DECIMAL } from "@/trader/format";

/**
 * What each risk limit is, how it is typed, and which direction loosens it.
 *
 * The Trader API is the control: it validates every range and decides whether a
 * change needs a step-up. This file mirrors those rules so the form can explain
 * a change before it is sent (what is looser, what needs a password), and a
 * disagreement is harmless because the server answers last. Keep it in step with
 * `limit_problem` and `loosens` in `aidss_trader/api/app.py`.
 */

export type Kind = "pct" | "idr" | "int" | "int0" | "window" | "fixed";

export interface LimitField {
  name: string;
  kind: Kind;
  /** Which way is looser: a higher value lets more risk through, or a lower one. */
  looser: "higher" | "lower" | null;
  unit: MessageKey | null;
  label: MessageKey;
  hint: MessageKey;
  /** An empty value means "unset, trading disabled" unless the field is optional. */
  optional?: boolean;
}

const f = (
  name: string,
  kind: Kind,
  looser: LimitField["looser"],
  unit: MessageKey | null,
  label: MessageKey,
  hint: MessageKey,
  optional = false,
): LimitField => ({ name, kind, looser, unit, label, hint, optional });

export const GROUPS: { title: MessageKey; fields: LimitField[] }[] = [
  {
    title: "trader.limits.group.trade",
    fields: [
      f("risk_per_trade_pct", "pct", "higher", "trader.unit.pctEquity", "trader.limit.risk_per_trade_pct.label", "trader.limit.risk_per_trade_pct.hint"),
      f("max_order_idr", "idr", "higher", "trader.unit.idr", "trader.limit.max_order_idr.label", "trader.limit.max_order_idr.hint"),
      f("price_deviation_pct", "pct", "higher", "trader.unit.pct", "trader.limit.price_deviation_pct.label", "trader.limit.price_deviation_pct.hint"),
    ],
  },
  {
    title: "trader.limits.group.exposure",
    fields: [
      f("max_open_positions", "int", "higher", "trader.unit.count", "trader.limit.max_open_positions.label", "trader.limit.max_open_positions.hint"),
      f("max_exposure_per_pair_pct", "pct", "higher", "trader.unit.pctEquity", "trader.limit.max_exposure_per_pair_pct.label", "trader.limit.max_exposure_per_pair_pct.hint"),
      f("max_total_exposure_pct", "pct", "higher", "trader.unit.pctEquity", "trader.limit.max_total_exposure_pct.label", "trader.limit.max_total_exposure_pct.hint"),
    ],
  },
  {
    title: "trader.limits.group.loss",
    fields: [
      f("max_daily_loss_idr", "idr", "higher", "trader.unit.idr", "trader.limit.max_daily_loss_idr.label", "trader.limit.max_daily_loss_idr.hint"),
      f("max_drawdown_pct", "pct", "higher", "trader.unit.pct", "trader.limit.max_drawdown_pct.label", "trader.limit.max_drawdown_pct.hint"),
      f("max_consecutive_losses", "int", "higher", "trader.unit.count", "trader.limit.max_consecutive_losses.label", "trader.limit.max_consecutive_losses.hint"),
    ],
  },
  {
    title: "trader.limits.group.operation",
    fields: [
      f("freshness_limit_s", "int", "higher", "trader.unit.seconds", "trader.limit.freshness_limit_s.label", "trader.limit.freshness_limit_s.hint"),
      f("cooldown_s", "int0", "lower", "trader.unit.seconds", "trader.limit.cooldown_s.label", "trader.limit.cooldown_s.hint"),
      f("order_rate_limit", "int", "higher", "trader.unit.perMinute", "trader.limit.order_rate_limit.label", "trader.limit.order_rate_limit.hint"),
      f("trading_window", "window", null, null, "trader.limit.trading_window.label", "trader.limit.trading_window.hint", true),
    ],
  },
];

export const ALL_FIELDS = GROUPS.flatMap((g) => g.fields);

const WINDOW = /^(\d{2}):(\d{2})-(\d{2}):(\d{2})$/;

/** The message for an invalid entry, or null. An empty entry is valid: it means unset. */
export function problem(field: LimitField, text: string): MessageKey | null {
  const v = text.trim();
  if (v === "") return null;
  switch (field.kind) {
    case "pct":
      return DECIMAL.test(v) && compareDecimals(v, "0") > 0 && compareDecimals(v, "100") <= 0
        ? null
        : "trader.limits.invalid.pct";
    case "idr":
      return DECIMAL.test(v) && compareDecimals(v, "0") > 0 ? null : "trader.limits.invalid.number";
    case "int":
      return /^\d+$/.test(v) && Number(v) >= 1 ? null : "trader.limits.invalid.int";
    case "int0":
      return /^\d+$/.test(v) ? null : "trader.limits.invalid.int0";
    case "window": {
      const m = WINDOW.exec(v);
      const ok =
        m !== null && Number(m[1]) < 24 && Number(m[2]) < 60 && Number(m[3]) < 24 && Number(m[4]) < 60;
      return ok ? null : "trader.limits.invalid.window";
    }
    default:
      return null;
  }
}

export type Effect = "looser" | "tighter" | "cleared" | "enabled" | "neutral";

/** What a change does to the amount of risk allowed, for the review screen. */
export function effect(field: LimitField, from: string | null, to: string): Effect {
  // The trading window is not a risk amount: the server never treats it as looser.
  if (field.kind === "window") return "neutral";
  const next = to.trim();
  if (next === "") return from === null ? "neutral" : "cleared";
  if (from === null) return "enabled"; // switching a limit on is the loosest change there is
  if (field.looser === null) return "neutral";
  const c = compareDecimals(next, from);
  if (c === 0) return "neutral";
  return (c > 0) === (field.looser === "higher") ? "looser" : "tighter";
}

/** Whether the server will ask for a step-up: anything that lets more risk through. */
export function needsStepUp(e: Effect): boolean {
  return e === "looser" || e === "enabled";
}

/** Whether any field change across the limit set loosens risk (mirrors `loosens` in `api/app.py`). */
export function limitsLoosen(
  before: Record<string, string | null>,
  after: Record<string, string>,
): boolean {
  return ALL_FIELDS.some((field) => needsStepUp(effect(field, before[field.name] ?? null, after[field.name] ?? "")));
}

export const PAIR = /^[A-Z0-9]{2,12}IDR$/;

export function parsePairs(text: string): string[] {
  return [...new Set(text.split(/[\s,]+/).map((p) => p.trim().toUpperCase()).filter(Boolean))].sort();
}

export interface AllowlistSnapshot {
  pairs: readonly string[];
  minVolume: string | null;
  maxSpread: string | null;
  /** ALL: every IDR market that passes the liquidity filter, best volume first, at most `maxPairs`. */
  allPairs?: boolean;
  maxPairs?: number | null;
}

/**
 * Mirrors `allowlist_loosens` in `aidss_trader/api/app.py`:
 * true when `next` can trade something `prev` could not (a new pair, a newly
 * configured liquidity filter, a lower volume floor, or a wider spread cap).
 */
export function allowlistLoosens(prev: AllowlistSnapshot, next: AllowlistSnapshot): boolean {
  if (next.pairs.some((p) => !prev.pairs.includes(p))) return true;
  // ALL switched on, or its number raised (an unset number counts as 0): more markets can qualify.
  if (next.allPairs && (!prev.allPairs || (next.maxPairs ?? 0) > (prev.maxPairs ?? 0))) return true;
  const prevConfigured = prev.minVolume !== null && prev.maxSpread !== null;
  const nextConfigured = next.minVolume !== null && next.maxSpread !== null;
  if (!nextConfigured) return false;
  if (!prevConfigured) return true;
  return (
    compareDecimals(next.minVolume!, prev.minVolume!) < 0 ||
    compareDecimals(next.maxSpread!, prev.maxSpread!) > 0
  );
}

/** Per-row effect badges for the allowlist review dialog. */
export function allowlistEffects(
  prev: AllowlistSnapshot,
  next: AllowlistSnapshot,
): { pairs: Effect; minVolume: Effect; maxSpread: Effect; allPairs: Effect } {
  const prevSet = new Set(prev.pairs);
  const nextSet = new Set(next.pairs);
  const added = next.pairs.some((p) => !prevSet.has(p));
  const removed = prev.pairs.some((p) => !nextSet.has(p));
  const pairsEffect: Effect =
    next.pairs.length === 0 && prev.pairs.length > 0
      ? "cleared"
      : prev.pairs.length === 0 && next.pairs.length > 0
        ? "enabled"
        : added
          ? "looser"
          : removed
            ? "tighter"
            : "neutral";

  const minVolumeEffect: Effect =
    next.minVolume === null
      ? prev.minVolume === null
        ? "neutral"
        : "cleared"
      : prev.minVolume === null
        ? "enabled"
        : compareDecimals(next.minVolume, prev.minVolume) < 0
          ? "looser"
          : compareDecimals(next.minVolume, prev.minVolume) > 0
            ? "tighter"
            : "neutral";

  const maxSpreadEffect: Effect =
    next.maxSpread === null
      ? prev.maxSpread === null
        ? "neutral"
        : "cleared"
      : prev.maxSpread === null
        ? "enabled"
        : compareDecimals(next.maxSpread, prev.maxSpread) > 0
          ? "looser"
          : compareDecimals(next.maxSpread, prev.maxSpread) < 0
            ? "tighter"
            : "neutral";

  const prevAll = prev.allPairs === true;
  const nextAll = next.allPairs === true;
  const allEffect: Effect =
    nextAll && !prevAll
      ? "enabled"
      : !nextAll && prevAll
        ? "cleared"
        : nextAll && (next.maxPairs ?? 0) > (prev.maxPairs ?? 0)
          ? "looser"
          : nextAll && (next.maxPairs ?? 0) < (prev.maxPairs ?? 0)
            ? "tighter"
            : "neutral";

  return {
    pairs: pairsEffect,
    minVolume: minVolumeEffect,
    maxSpread: maxSpreadEffect,
    allPairs: allEffect,
  };
}

