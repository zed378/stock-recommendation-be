import { describe, expect, it } from "vitest";
import {
  ALL_FIELDS,
  allowlistEffects,
  allowlistLoosens,
  effect,
  limitsLoosen,
  needsStepUp,
  PAIR,
  parsePairs,
  problem,
  type LimitField,
} from "@/trader/limitsMeta";

function fieldByName(name: string): LimitField {
  const found = ALL_FIELDS.find((f) => f.name === name);
  if (!found) throw new Error(`missing field ${name}`);
  return found;
}

describe("limitsMeta.ts — validation and server-parity loosening rules", () => {
  describe("problem (mirrors limit_problem in aidss_trader/api/app.py)", () => {
    it("treats empty string as valid (unset disables trading)", () => {
      for (const f of ALL_FIELDS) {
        expect(problem(f, "")).toBeNull();
        expect(problem(f, "   ")).toBeNull();
      }
    });

    it("validates pct fields in (0, 100]", () => {
      const f = fieldByName("risk_per_trade_pct");
      expect(problem(f, "0")).toBe("trader.limits.invalid.pct");
      expect(problem(f, "0.01")).toBeNull();
      expect(problem(f, "100")).toBeNull();
      expect(problem(f, "100.01")).toBe("trader.limits.invalid.pct");
      expect(problem(f, "-1")).toBe("trader.limits.invalid.pct");
    });

    it("validates idr fields as > 0", () => {
      const f = fieldByName("max_order_idr");
      expect(problem(f, "0")).toBe("trader.limits.invalid.number");
      expect(problem(f, "100000")).toBeNull();
    });

    it("validates int (>= 1) and int0 (>= 0) fields", () => {
      const intField = fieldByName("max_open_positions");
      expect(problem(intField, "0")).toBe("trader.limits.invalid.int");
      expect(problem(intField, "1")).toBeNull();
      expect(problem(intField, "1.5")).toBe("trader.limits.invalid.int");

      const int0Field = fieldByName("cooldown_s");
      expect(problem(int0Field, "0")).toBeNull();
      expect(problem(int0Field, "60")).toBeNull();
      expect(problem(int0Field, "-1")).toBe("trader.limits.invalid.int0");
    });

    it("validates trading_window as HH:MM-HH:MM with 00<=HH<24 and 00<=MM<60", () => {
      const w = fieldByName("trading_window");
      expect(problem(w, "08:00-22:30")).toBeNull();
      expect(problem(w, "24:00-10:00")).toBe("trader.limits.invalid.window");
      expect(problem(w, "08:60-10:00")).toBe("trader.limits.invalid.window");
      expect(problem(w, "8:00-10:00")).toBe("trader.limits.invalid.window");
    });
  });

  describe("effect, needsStepUp, and limitsLoosen (mirrors loosens in aidss_trader/api/app.py)", () => {
    it("marks setting a previously unset limit as enabled (requires step-up) and clearing as cleared (no step-up)", () => {
      const f = fieldByName("risk_per_trade_pct");
      expect(effect(f, null, "1")).toBe("enabled");
      expect(needsStepUp(effect(f, null, "1"))).toBe(true);

      expect(effect(f, "1", "")).toBe("cleared");
      expect(needsStepUp(effect(f, "1", ""))).toBe(false);
      expect(effect(f, null, "")).toBe("neutral");
    });

    it("treats higher values as looser for _HIGHER_IS_LOOSER fields and lower values as looser for cooldown_s", () => {
      const risk = fieldByName("risk_per_trade_pct");
      expect(effect(risk, "1", "2")).toBe("looser");
      expect(effect(risk, "2", "1")).toBe("tighter");
      expect(effect(risk, "1.0", "1")).toBe("neutral");

      const cooldown = fieldByName("cooldown_s");
      expect(effect(cooldown, "300", "60")).toBe("looser");
      expect(needsStepUp(effect(cooldown, "300", "60"))).toBe(true);
      expect(effect(cooldown, "60", "300")).toBe("tighter");
      expect(needsStepUp(effect(cooldown, "60", "300"))).toBe(false);
    });

    it("never treats trading_window changes as loosening", () => {
      const w = fieldByName("trading_window");
      expect(effect(w, null, "09:00-17:00")).toBe("neutral");
      expect(effect(w, "09:00-17:00", "00:00-23:59")).toBe("neutral");
      expect(needsStepUp(effect(w, null, "09:00-17:00"))).toBe(false);
    });

    it("limitsLoosen matches server loosens across all fields", () => {
      const base: Record<string, string | null> = Object.fromEntries(
        ALL_FIELDS.map((f) => [f.name, f.kind === "window" ? null : "10"]),
      );
      const tighter: Record<string, string> = {
        ...Object.fromEntries(ALL_FIELDS.map((f) => [f.name, f.kind === "window" ? "" : "5"])),
        cooldown_s: "20", // higher cooldown is tighter
      };
      expect(limitsLoosen(base, tighter)).toBe(false);

      const looserCooldown = { ...tighter, cooldown_s: "5" };
      expect(limitsLoosen(base, looserCooldown)).toBe(true);
    });
  });

  describe("allowlistLoosens & allowlistEffects (mirrors allowlist_loosens in aidss_trader/api/app.py)", () => {
    it("parses and validates IDR pair symbols", () => {
      expect(parsePairs("btcidr, ethidr  btcidr ")).toEqual(["BTCIDR", "ETHIDR"]);
      expect(PAIR.test("BTCIDR")).toBe(true);
      expect(PAIR.test("BTCUSDT")).toBe(false);
      expect(PAIR.test("IDR")).toBe(false);
    });

    it("matches server allowlist_loosens on pair additions, filter activation, volume drop, and spread rise", () => {
      const active = { pairs: ["BTCIDR", "ETHIDR"], minVolume: "1000000000", maxSpread: "0.5" };

      // Adding a new pair loosens
      expect(
        allowlistLoosens(active, { pairs: ["BTCIDR", "ETHIDR", "SOLIDR"], minVolume: "1000000000", maxSpread: "0.5" }),
      ).toBe(true);

      // Removing a pair without loosening liquidity does not loosen
      expect(
        allowlistLoosens(active, { pairs: ["BTCIDR"], minVolume: "1000000000", maxSpread: "0.5" }),
      ).toBe(false);

      // Unsetting liquidity filter disables trading -> does not loosen
      expect(
        allowlistLoosens(active, { pairs: ["BTCIDR", "ETHIDR"], minVolume: null, maxSpread: "0.5" }),
      ).toBe(false);

      // Activating liquidity filter when previously unconfigured -> loosens
      expect(
        allowlistLoosens(
          { pairs: ["BTCIDR"], minVolume: null, maxSpread: null },
          { pairs: ["BTCIDR"], minVolume: "1000000000", maxSpread: "0.5" },
        ),
      ).toBe(true);

      // Lowering minVolume loosens; raising minVolume tightens
      expect(
        allowlistLoosens(active, { pairs: ["BTCIDR", "ETHIDR"], minVolume: "500000000", maxSpread: "0.5" }),
      ).toBe(true);
      expect(
        allowlistLoosens(active, { pairs: ["BTCIDR", "ETHIDR"], minVolume: "2000000000", maxSpread: "0.5" }),
      ).toBe(false);

      // Raising maxSpread loosens; lowering maxSpread tightens
      expect(
        allowlistLoosens(active, { pairs: ["BTCIDR", "ETHIDR"], minVolume: "1000000000", maxSpread: "0.8" }),
      ).toBe(true);
      expect(
        allowlistLoosens(active, { pairs: ["BTCIDR", "ETHIDR"], minVolume: "1000000000", maxSpread: "0.2" }),
      ).toBe(false);

      const effects = allowlistEffects(active, {
        pairs: ["BTCIDR"],
        minVolume: "500000000",
        maxSpread: "0.2",
      });
      expect(effects).toEqual({
        pairs: "tighter",
        minVolume: "looser",
        maxSpread: "tighter",
      });
    });
  });
});
