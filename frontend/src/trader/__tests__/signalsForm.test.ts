import { describe, expect, it } from "vitest";
import { bodyFrom, formFrom, loosensSignals, sameForm, type SignalsForm } from "@/trader/signalsForm";
import type { SignalsConfig } from "@/trader/types";

const config = (over: Partial<SignalsConfig["settings"]> = {}): SignalsConfig => ({
  configured: true,
  settings: {
    enabled: true,
    mode: "SHADOW",
    symbols: ["BTCUSDT", "ETHUSDT"],
    top_n: 5,
    min_quote_volume_usdt: "50000000",
    horizons: ["14d", "30d"],
    min_score_ratio: "0.8",
    atr_stop_multiple: "2.5",
    tp_r: ["1.5", "2.5", "4"],
    ai_min_score: 70,
    ai_max_calls: 10,
    ...over,
  },
  unset: [],
  ready: true,
  default_top_n: 5,
  max_top_n: 50,
  valid_horizons: ["1d", "7d", "14d", "30d"],
  run_requested_at: null,
  updated_at: "2026-11-20T00:00:00Z",
  updated_by: "owner",
});

const edit = (c: SignalsConfig, over: Partial<SignalsForm>): SignalsForm => ({ ...formFrom(c), ...over });

describe("signals form", () => {
  it("round-trips the stored settings and sends blanks as null, never as zero", () => {
    const c = config();
    expect(bodyFrom(formFrom(c))).toMatchObject({
      enabled: true,
      mode: "SHADOW",
      symbols: ["BTCUSDT", "ETHUSDT"],
      top_n: 5,
      min_quote_volume_usdt: "50000000",
      horizons: ["14d", "30d"],
      min_score_ratio: "0.8",
      tp_r: ["1.5", "2.5", "4"],
      ai_min_score: 70,
      ai_max_calls: 10,
      confirm_publish: false,
    });
    const blank = config({ min_score_ratio: null, atr_stop_multiple: null, tp_r: null, ai_min_score: null, ai_max_calls: null, min_quote_volume_usdt: null, horizons: [] });
    const body = bodyFrom(formFrom(blank));
    expect(body).toMatchObject({ min_score_ratio: null, atr_stop_multiple: null, tp_r: null, ai_min_score: null, ai_max_calls: null, min_quote_volume_usdt: null, horizons: [] });
  });

  it("parses typed symbols from commas, spaces and lines, upper-cased", () => {
    const f = edit(config(), { symbols: " btcusdt,ethusdt\nsolusdt  xrpusdt" });
    expect(bodyFrom(f).symbols).toEqual(["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]);
  });

  it("keeps horizons in their natural order and drops unknown ones", () => {
    expect(bodyFrom(edit(config(), { horizons: ["30d", "7d", "99d"] })).horizons).toEqual(["7d", "30d"]);
  });

  it("a half-typed number is not a number: whole fields become null, decimals are left for the server", () => {
    const f = edit(config(), { topN: "5x", aiMin: "", aiCalls: "3.5" });
    const b = bodyFrom(f);
    expect(b.top_n).toBeNull();
    expect(b.ai_min_score).toBeNull();
    expect(b.ai_max_calls).toBeNull();
  });

  it("detects a change and ignores formatting noise", () => {
    const c = config();
    expect(sameForm(formFrom(c), edit(c, { symbols: "ETHUSDT BTCUSDT" }))).toBe(false); // order is a change
    expect(sameForm(formFrom(c), edit(c, { symbols: " BTCUSDT ,  ETHUSDT " }))).toBe(true);
    expect(sameForm(formFrom(c), edit(c, { minRatio: "0.8 " }))).toBe(true);
  });
});

describe("what needs the password", () => {
  const c = config();
  it.each([
    ["publishing", { mode: "PUBLISH" as const }],
    ["a lower score bar", { minRatio: "0.7" }],
    ["a lower AI minimum", { aiMin: "60" }],
    ["a lower volume floor", { minVolume: "1000" }],
    ["more coins by volume", { topN: "6" }],
    ["a wider stop", { atrStop: "3" }],
    ["more AI calls", { aiCalls: "11" }],
  ])("%s asks for it", (_name, over) => {
    expect(loosensSignals(c, edit(c, over))).toBe(true);
  });

  it.each([
    ["a higher score bar", { minRatio: "0.9" }],
    ["fewer coins", { topN: "2" }],
    ["switching off", { enabled: false }],
    ["other coins", { symbols: "SOLUSDT" }],
    ["other horizons", { horizons: ["30d"] }],
    ["a tighter stop", { atrStop: "2" }],
    ["fewer AI calls", { aiCalls: "3" }],
  ])("%s does not", (_name, over) => {
    expect(loosensSignals(c, edit(c, over))).toBe(false);
  });

  it("nothing set before means nothing to loosen, and staying in PUBLISH is not a switch", () => {
    const fresh = config({ min_score_ratio: null, ai_min_score: null, min_quote_volume_usdt: null, atr_stop_multiple: null, ai_max_calls: null });
    expect(loosensSignals(fresh, edit(fresh, { minRatio: "0.5", aiMin: "10", minVolume: "1", atrStop: "9", aiCalls: "50" }))).toBe(false);
    const live = config({ mode: "PUBLISH" });
    expect(loosensSignals(live, edit(live, { mode: "PUBLISH" }))).toBe(false);
  });
});
