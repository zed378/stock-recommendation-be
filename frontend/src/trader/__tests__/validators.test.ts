import { describe, expect, it } from "vitest";
import {
  emaOrderBad,
  neededHistory,
  PAPER_FIELDS,
  paperEffect,
  paperFlatters,
  paperProblem,
   paramProblem,
  type PaperName,
} from "@/trader/validators";

describe("validators.ts — strategy parameters and paper simulation assumptions", () => {
  describe("strategy parameter validators (TraderParameters.tsx)", () => {
    it("validates int, int0, threshold, and multiple fields", () => {
      expect(paramProblem("int", "0")).toBe("trader.params.invalid.int");
      expect(paramProblem("int", "12")).toBeNull();
      expect(paramProblem("int0", "0")).toBeNull();
      expect(paramProblem("int0", "-1")).toBe("trader.params.invalid.int0");
      expect(paramProblem("threshold", "0")).toBe("trader.params.invalid.threshold");
      expect(paramProblem("threshold", "25")).toBeNull();
      expect(paramProblem("threshold", "100")).toBeNull();
      expect(paramProblem("threshold", "100.1")).toBe("trader.params.invalid.threshold");
      expect(paramProblem("multiple", "0")).toBe("trader.params.invalid.number");
      expect(paramProblem("multiple", "2.5")).toBeNull();
    });

    it("checks ema_fast < ema_slow and computes min_history exactly like EmaAdxStrategy.min_history", () => {
      expect(emaOrderBad("12", "26")).toBe(false);
      expect(emaOrderBad("26", "26")).toBe(true);
      expect(emaOrderBad("30", "26")).toBe(true);

      // max(ema_slow, 2 * adx_period + 1, atr_period + 1)
      expect(
        neededHistory({ ema_slow: "26", adx_period: "14", atr_period: "14" }),
      ).toBe(29);
      expect(
        neededHistory({ ema_slow: "200", adx_period: "14", atr_period: "14" }),
      ).toBe(200);
      expect(
        neededHistory({ ema_slow: "", adx_period: "14", atr_period: "14" }),
      ).toBeNull();
    });
  });

  describe("paper assumption validators & paperFlatters (mirrors paper_flatters in settings_store.py)", () => {
    it("validates pct [0, 100], fraction (0, 1], and idr > 0", () => {
      expect(paperProblem("pct", "0")).toBeNull();
      expect(paperProblem("pct", "100")).toBeNull();
      expect(paperProblem("pct", "100.01")).toBe("trader.paper.invalid.pct");

      expect(paperProblem("fraction", "0")).toBe("trader.paper.invalid.fraction");
      expect(paperProblem("fraction", "0.5")).toBeNull();
      expect(paperProblem("fraction", "1")).toBeNull();
      expect(paperProblem("fraction", "1.01")).toBe("trader.paper.invalid.fraction");

      expect(paperProblem("idr", "0")).toBe("trader.paper.invalid.idr");
      expect(paperProblem("idr", "10000000")).toBeNull();
    });

    it("detects flattering changes identically to server paper_flatters", () => {
      const base: Record<PaperName, string> = {
        start_equity_idr: "10000000",
        slippage_pct: "0.2",
        partial_fill_fraction: "0.8",
        maker_fee_pct: "0.1",
        taker_fee_pct: "0.2",
        tax_pct: "0.1",
        clearing_pct: "0.05",
      };

      // Changing start_equity_idr alone never flatters
      expect(paperFlatters(base, { ...base, start_equity_idr: "50000000" })).toBe(false);

      // Raising costs or lowering fill fraction is harsher, not flattering
      expect(
        paperFlatters(base, {
          ...base,
          slippage_pct: "0.3",
          partial_fill_fraction: "0.5",
          taker_fee_pct: "0.3",
        }),
      ).toBe(false);

      // Lowering any fee/slippage or raising partial_fill_fraction flatters
      expect(paperFlatters(base, { ...base, slippage_pct: "0.1" })).toBe(true);
      expect(paperFlatters(base, { ...base, partial_fill_fraction: "0.9" })).toBe(true);
      expect(paperFlatters(base, { ...base, maker_fee_pct: "0.05" })).toBe(true);
      expect(paperFlatters(base, { ...base, taker_fee_pct: "0.15" })).toBe(true);
      expect(paperFlatters(base, { ...base, tax_pct: "0.05" })).toBe(true);
      expect(paperFlatters(base, { ...base, clearing_pct: "0.01" })).toBe(true);

      const slipField = PAPER_FIELDS.find((f) => f.name === "slippage_pct")!;
      expect(paperEffect(slipField, "0.2", "0.1")).toBe("flatters");
      expect(paperEffect(slipField, "0.2", "0.3")).toBe("harsher");
    });
  });
});
