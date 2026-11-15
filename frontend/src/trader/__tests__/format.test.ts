import { describe, expect, it } from "vitest";
import { ageSeconds, compareDecimals, groupDigits, multiplyDecimals } from "@/trader/format";

describe("format.ts — exact decimal string helpers", () => {
  describe("multiplyDecimals", () => {
    it("multiplies IDR prices and crypto quantities without float rounding", () => {
      expect(multiplyDecimals("1600000000", "0.00312500")).toBe("5000000");
      expect(multiplyDecimals("1600000000.01", "0.00312500")).toBe("5000000.00003125");
      expect(multiplyDecimals("999999999999999.99", "1")).toBe("999999999999999.99");
    });

    it("handles zero and strips trailing fractional zeroes", () => {
      expect(multiplyDecimals("0", "12345.6789")).toBe("0");
      expect(multiplyDecimals("12345.6789", "0.000")).toBe("0");
      expect(multiplyDecimals("2.50", "4.00")).toBe("10");
      expect(multiplyDecimals("0.1", "0.2")).toBe("0.02");
    });

    it("handles small fractional products with leading zeroes after the decimal point", () => {
      expect(multiplyDecimals("0.01", "1236777000")).toBe("12367770");
      expect(multiplyDecimals("0.00000001", "1")).toBe("0.00000001");
      expect(multiplyDecimals("0.005", "0.002")).toBe("0.00001");
    });
  });

  describe("compareDecimals", () => {
    it("compares decimals of different fractional lengths and leading zeroes", () => {
      expect(compareDecimals("1.5", "1.5000")).toBe(0);
      expect(compareDecimals("0010.05", "10.050")).toBe(0);
      expect(compareDecimals("0", "0.000")).toBe(0);
      expect(compareDecimals("10.05", "10.049")).toBe(1);
      expect(compareDecimals("10.049", "10.05")).toBe(-1);
    });

    it("compares numbers larger than Number.MAX_SAFE_INTEGER accurately", () => {
      expect(compareDecimals("9007199254740993", "9007199254740992")).toBe(1);
      expect(compareDecimals("9007199254740992", "9007199254740993")).toBe(-1);
    });
  });

  describe("groupDigits", () => {
    it("groups integer digits for Indonesian and English locales without rounding", () => {
      expect(groupDigits("1600000000", "id")).toBe("1.600.000.000");
      expect(groupDigits("1600000000", "en")).toBe("1,600,000,000");
      expect(groupDigits("1234567.8901", "id")).toBe("1.234.567,8901");
      expect(groupDigits("1234567.8901", "en")).toBe("1,234,567.8901");
      expect(groupDigits("999", "id")).toBe("999");
    });

    it("returns non-decimal strings unchanged", () => {
      expect(groupDigits("-", "id")).toBe("-");
    });
  });

  describe("ageSeconds", () => {
    it("rounds elapsed seconds and clamps negative skew to 0", () => {
      expect(ageSeconds(10_000, 22_400)).toBe(12);
      expect(ageSeconds(10_000, 22_900)).toBe(13);
      expect(ageSeconds(25_000, 20_000)).toBe(0);
    });
  });
});
