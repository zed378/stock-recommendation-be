import { describe, expect, it } from "vitest";
import {
  emaOrderBad,
  neededHistory,
  PAPER_FIELDS,
  paperEffect,
  paperFlatters,
  paperProblem,
  paramProblem,
  THRESHOLD_FIELDS,
  thresholdEffect,
  thresholdProblem,
  thresholdsLoosen,
  type PaperName,
} from "@/trader/validators";
import { countCsvDataRows } from "@/trader/mutations";

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

  describe("Promotion thresholds validators (OQ-12)", () => {
    it("validates threshold kinds and allows empty (unset)", () => {
      expect(thresholdProblem("int", "")).toBeNull();
      expect(thresholdProblem("int", "0")).toBe("trader.limits.invalid.int");
      expect(thresholdProblem("int", "5")).toBeNull();

      expect(thresholdProblem("pct_pos", "0")).toBe("trader.limits.invalid.pct");
      expect(thresholdProblem("pct_pos", "15.5")).toBeNull();

      expect(thresholdProblem("return_pct", "-100")).toBe("trader.thresholds.invalid.return");
      expect(thresholdProblem("return_pct", "-15.5")).toBeNull();
      expect(thresholdProblem("return_pct", "12.5")).toBeNull();
    });

    it("detects loosening thresholds symmetrically with server thresholds_loosen", () => {
      const tradesField = THRESHOLD_FIELDS.find((f) => f.name === "min_paper_trades")!;
      const ddField = THRESHOLD_FIELDS.find((f) => f.name === "max_paper_drawdown_pct")!;
      const retField = THRESHOLD_FIELDS.find((f) => f.name === "backtest_min_return_pct")!;

      expect(thresholdEffect(tradesField, null, "5")).toBe("looser");
      expect(thresholdEffect(tradesField, "10", null)).toBe("disables");
      expect(thresholdEffect(tradesField, "10", "5")).toBe("looser");
      expect(thresholdEffect(tradesField, "10", "15")).toBe("tighter");

      expect(thresholdEffect(ddField, "10", "15")).toBe("looser");
      expect(thresholdEffect(ddField, "10", "8")).toBe("tighter");

      expect(thresholdEffect(retField, "5", "-2")).toBe("looser");
      expect(thresholdEffect(retField, "-2", "5")).toBe("tighter");

      const before = {
        min_paper_trades: "10",
        max_paper_drawdown_pct: "10",
        backtest_min_return_pct: "5",
        max_live_capital_idr: "20000000",
        max_slippage_pct: "0.5",
      };
      expect(thresholdsLoosen(before, { ...before, min_paper_trades: "12" })).toBe(false);
      expect(thresholdsLoosen(before, { ...before, min_paper_trades: "8" })).toBe(true);
    });

    it("counts CSV data rows excluding the header", () => {
      expect(countCsvDataRows("a,b,c\n")).toBe(0);
      expect(countCsvDataRows("a,b,c\n1,2,3\n4,5,6\n")).toBe(2);
    });
  });
});
