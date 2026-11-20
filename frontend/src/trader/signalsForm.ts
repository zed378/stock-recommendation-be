import type { SignalsConfig } from "@/trader/types";
import type { SignalsConfigBodyValues } from "@/trader/mutations";

/** The form's own shape: everything as text, so a half-typed number is never a wrong number. */
export interface SignalsForm {
  enabled: boolean;
  mode: "SHADOW" | "PUBLISH";
  symbols: string;
  topN: string;
  minVolume: string;
  horizons: string[];
  minRatio: string;
  atrStop: string;
  tp1: string;
  tp2: string;
  tp3: string;
  aiMin: string;
  aiCalls: string;
  confirmPublish: boolean;
}

export const HORIZON_ORDER = ["1d", "7d", "14d", "30d"] as const;

export function formFrom(config: SignalsConfig): SignalsForm {
  const s = config.settings;
  return {
    enabled: s.enabled,
    mode: s.mode === "PUBLISH" ? "PUBLISH" : "SHADOW",
    symbols: s.symbols.join(", "),
    topN: String(s.top_n),
    minVolume: s.min_quote_volume_usdt ?? "",
    horizons: [...s.horizons],
    minRatio: s.min_score_ratio ?? "",
    atrStop: s.atr_stop_multiple ?? "",
    tp1: s.tp_r?.[0] ?? "",
    tp2: s.tp_r?.[1] ?? "",
    tp3: s.tp_r?.[2] ?? "",
    aiMin: s.ai_min_score === null ? "" : String(s.ai_min_score),
    aiCalls: s.ai_max_calls === null ? "" : String(s.ai_max_calls),
    confirmPublish: false,
  };
}

const text = (v: string) => (v.trim() === "" ? null : v.trim());
const whole = (v: string) => {
  const t = v.trim();
  return t === "" || !/^-?\d+$/.test(t) ? null : Number(t);
};

export function bodyFrom(f: SignalsForm): SignalsConfigBodyValues {
  const tp = [f.tp1, f.tp2, f.tp3].map((v) => v.trim());
  return {
    enabled: f.enabled,
    mode: f.mode,
    symbols: f.symbols
      .split(/[\s,]+/)
      .map((x) => x.trim().toUpperCase())
      .filter(Boolean),
    top_n: whole(f.topN),
    min_quote_volume_usdt: text(f.minVolume),
    horizons: HORIZON_ORDER.filter((h) => f.horizons.includes(h)),
    min_score_ratio: text(f.minRatio),
    atr_stop_multiple: text(f.atrStop),
    tp_r: tp.every((v) => v === "") ? null : tp,
    ai_min_score: whole(f.aiMin),
    ai_max_calls: whole(f.aiCalls),
    confirm_publish: f.confirmPublish,
    notes: "",
  };
}

const num = (v: string | null | undefined): number | null => {
  if (v === null || v === undefined || v.trim() === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

/**
 * Whether saving `next` over `current` makes the worker act more readily, which the server answers
 * with a password. Mirrors the server's rule so the dialog opens before the request, not after a
 * refusal; the server still decides.
 */
export function loosensSignals(current: SignalsConfig, next: SignalsForm): boolean {
  const a = current.settings;
  const n = bodyFrom(next);
  const lower = (was: number | null, now: number | null) => was !== null && now !== null && now < was;
  const higher = (was: number | null, now: number | null) => was !== null && now !== null && now > was;
  if (n.mode === "PUBLISH" && a.mode !== "PUBLISH") return true;
  if (lower(num(a.min_score_ratio), num(n.min_score_ratio))) return true;
  if (lower(a.ai_min_score, n.ai_min_score)) return true;
  if (lower(num(a.min_quote_volume_usdt), num(n.min_quote_volume_usdt))) return true;
  if (n.top_n !== null && n.top_n > a.top_n) return true;
  if (higher(num(a.atr_stop_multiple), num(n.atr_stop_multiple))) return true;
  if (higher(a.ai_max_calls, n.ai_max_calls)) return true;
  return false;
}

export function sameForm(a: SignalsForm, b: SignalsForm): boolean {
  return JSON.stringify(bodyFrom(a)) === JSON.stringify(bodyFrom(b));
}
