import { describe, expect, it } from "vitest";
import {
  displayAmount,
  displayPercent,
  displayPrice,
  displayQuantity,
  roundDecimal,
  trimZeros,
} from "@/trader/format";

describe("exact display rounding (no float)", () => {
  it("rounds half away from zero on the digits themselves", () => {
    expect(roundDecimal("73843.43374045872", 0)).toBe("73843");
    expect(roundDecimal("0.5", 0)).toBe("1");
    expect(roundDecimal("-0.5", 0)).toBe("-1");
    expect(roundDecimal("9.995", 2)).toBe("10.00");
    expect(roundDecimal("999.999", 2)).toBe("1000.00");
    expect(roundDecimal("0.2506244550557837837837838", 2)).toBe("0.25");
  });

  it("never shows a negative zero and leaves short values alone", () => {
    expect(roundDecimal("-0.004", 2)).toBe("0.00");
    expect(roundDecimal("12.5", 4)).toBe("12.5");
    expect(roundDecimal("7", 2)).toBe("7");
  });

  it("trims trailing zeros and a dangling point only where there is a fraction", () => {
    expect(trimZeros("10.50")).toBe("10.5");
    expect(trimZeros("10.00")).toBe("10");
    expect(trimZeros("100")).toBe("100");
    expect(trimZeros("0.0")).toBe("0");
  });

  it("shows money as whole rupiah from 1,000 up and two decimals below", () => {
    expect(displayAmount("73843.43374045872")).toBe("73843");
    expect(displayAmount("74000")).toBe("74000");
    expect(displayAmount("340.397370875")).toBe("340.4");
    expect(displayAmount("-1.2399")).toBe("-1.24");
    expect(displayAmount("0")).toBe("0");
  });

  it("shows more decimals for a price the smaller it is", () => {
    expect(displayPrice("18354.124")).toBe("18354.12");
    expect(displayPrice("5446.357934")).toBe("5446.36");
    expect(displayPrice("340.397370875")).toBe("340.3974");
    expect(displayPrice("0.000001234567")).toBe("0.000001");
    expect(displayPrice("1000")).toBe("1000");
  });

  it("keeps quantities as fine as the exchange's steps and percentages to two decimals", () => {
    expect(displayQuantity("0.80958372")).toBe("0.80958372");
    expect(displayQuantity("16.000000000000000000")).toBe("16");
    expect(displayPercent("0.2506244550557837837837838")).toBe("0.25");
    expect(displayPercent("1.2")).toBe("1.2");
  });
});
