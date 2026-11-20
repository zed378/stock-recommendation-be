import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { adx, at, atr, directionalLines, ema, type Candle } from "../src/engine/indicators";

/**
 * Paritas dengan AIDSS Trader: deret yang sama (bilangan bulat, sehingga identik di kedua bahasa)
 * dihitung di Python (Decimal) dan angka di bawah disalin dari sana.
 * Jalankan: npx tsx --test tests/local-engine-indicators.test.ts
 */
export function series(n = 120, seed = 12345): Candle[] {
  // BigInt: o produto do LCG melebihi 2^53, dan hasilnya harus identik dengan versi Python.
  let x = BigInt(seed);
  const next = (): number => {
    x = (x * 1103515245n + 12345n) % 2147483648n;
    return Number(x);
  };
  let prev = 100000;
  const out: Candle[] = [];
  for (let i = 0; i < n; i++) {
    const step = (next() % 2001) - 900;
    const close = Math.max(1000, prev + step);
    const h = next() % 600;
    const l = next() % 600;
    out.push({
      openTime: Date.UTC(2026, 0, 1) + i * 4 * 3600_000,
      closeTime: Date.UTC(2026, 0, 1) + (i + 1) * 4 * 3600_000 - 1,
      open: prev,
      high: Math.max(prev, close) + h,
      low: Math.min(prev, close) - l,
      close,
      volume: 1,
    });
    prev = close;
  }
  return out;
}

const IDX = [50, 80, 119];
const EXPECT = {
  ema5: [102778.15643945364, 103322.1913873642, 110261.5433212466],
  ema12: [102636.13690197616, 103369.86762635186, 110094.50452792874],
  atr5: [1251.1150999177337, 1012.4662852246394, 1134.2636372861393],
  adx5: [33.3628049777137, 19.10112085591487, 25.00174068830809],
  plus5: [14.484675800431777, 16.269605612817656, 13.360379827653443],
  minus5: [10.060115801362839, 17.606661117349468, 17.913039263569708],
};

const close = (a: number | null, b: number) => {
  assert.ok(a !== null && Math.abs(a - b) <= 1e-7 * Math.max(1, Math.abs(b)), `${a} vs ${b}`);
};

describe("indikator sama dengan AIDSS Trader", () => {
  const cs = series();
  const closes = cs.map((c) => c.close);
  test("EMA", () => {
    IDX.forEach((i, k) => {
      close(at(ema(closes, 5), i), at(EXPECT.ema5, k));
      close(at(ema(closes, 12), i), at(EXPECT.ema12, k));
    });
  });
  test("ATR Wilder", () => IDX.forEach((i, k) => close(at(atr(cs, 5), i), at(EXPECT.atr5, k))));
  test("ADX Wilder", () => IDX.forEach((i, k) => close(at(adx(cs, 5), i), at(EXPECT.adx5, k))));
  test("+DI dan -DI", () => {
    const { plus, minus } = directionalLines(cs, 5);
    IDX.forEach((i, k) => {
      close(at(plus, i), at(EXPECT.plus5, k));
      close(at(minus, i), at(EXPECT.minus5, k));
    });
  });
  test("nilai sebelum cukup data adalah null, bukan nol", () => {
    assert.equal(ema(closes, 5)[3], null);
    assert.equal(atr(cs, 5)[4], null);
    assert.equal(adx(cs, 5)[8], null);
    assert.equal(directionalLines(cs, 5).plus[4], null);
    assert.equal(ema([1, 2], 5)[1], null);
  });
  test("periode tidak sah ditolak", () => {
    assert.throws(() => ema([1, 2, 3], 0));
  });
});
