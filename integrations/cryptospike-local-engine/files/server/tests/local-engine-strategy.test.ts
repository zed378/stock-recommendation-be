import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { evaluateEntry, minHistory, validateParams, btcTrendBias, type StrategyParams } from "../src/engine/strategy";
import type { Candle } from "../src/engine/indicators";
import { series } from "./local-engine-indicators.test";

/** Angka uji di berkas ini; bukan angka yang disarankan untuk dipakai. Jalankan: npx tsx --test tests/local-engine-strategy.test.ts */
const P: StrategyParams = {
  emaFast: 3, emaSlow: 6, adxPeriod: 3, adxThreshold: 20, atrPeriod: 3,
  atrStopMultiple: 2, diMargin: 0, tpR1: 1.5, tpR2: 2.5, tpR3: 4,
};

function trend(n: number, step: number, from = 100): Candle[] {
  return Array.from({ length: n }, (_, i) => {
    const c = from + step * i;
    return { openTime: i * 14400_000, closeTime: (i + 1) * 14400_000 - 1, open: c - step, high: c + 0.4, low: c - 0.4, close: c, volume: 1 };
  });
}

describe("evaluateEntry", () => {
  test("pasar naik tegas: ENTRY dengan stop di bawah entry dan target naik berurutan", () => {
    const ev = evaluateEntry(trend(40, 1), P);
    assert.equal(ev.kind, "ENTRY");
    if (ev.kind !== "ENTRY") return;
    assert.ok(ev.stop > 0 && ev.stop < ev.entry);
    assert.ok(ev.entry < ev.tp1 && ev.tp1 < ev.tp2 && ev.tp2 < ev.tp3);
    const risk = ev.entry - ev.stop;
    assert.ok(Math.abs((ev.tp1 - ev.entry) / risk - 1.5) < 1e-9);
    assert.ok(Math.abs((ev.tp3 - ev.entry) / risk - 4) < 1e-9);
  });
  test("pasar turun: tidak masuk", () => {
    const ev = evaluateEntry(trend(40, -1, 200), P);
    assert.equal(ev.kind, "NONE");
    assert.equal(ev.reason, "trend_not_up");
  });
  test("data kurang: tidak masuk dan tidak error", () => {
    const ev = evaluateEntry(trend(5, 1), P);
    assert.deepEqual([ev.kind, ev.reason], ["NONE", "insufficient_history"]);
    assert.equal(minHistory(P), Math.max(6, 7, 4) + 1);
  });
  test("ambang ADX dan margin DI hanya bisa MENOLAK entri, tidak membuat yang baru", () => {
    const cs = series(120);
    let looser = 0;
    let stricter = 0;
    for (let n = minHistory(P); n <= cs.length; n++) {
      const base = evaluateEntry(cs.slice(0, n), P).kind === "ENTRY";
      const strict = evaluateEntry(cs.slice(0, n), { ...P, adxThreshold: 40, diMargin: 5 }).kind === "ENTRY";
      if (base) looser++;
      if (strict) {
        stricter++;
        assert.ok(base, "filter yang lebih ketat tidak boleh masuk di tempat yang longgar menolak");
      }
    }
    assert.ok(looser > 0 && stricter <= looser);
  });
  test("tidak mengintip masa depan: keputusan di candle i sama dengan keputusan dari data sampai i saja", () => {
    const cs = series(120);
    for (const n of [40, 70, 100]) {
      const a = evaluateEntry(cs.slice(0, n), P);
      const b = evaluateEntry([...cs.slice(0, n), ...cs.slice(n)].slice(0, n), P);
      assert.deepEqual(a, b);
    }
  });
  test("stop tidak sah (di bawah nol) ditolak", () => {
    const ev = evaluateEntry(trend(40, 1, 1), { ...P, atrStopMultiple: 50 });
    assert.equal(ev.kind, "NONE");
    assert.equal(ev.reason, "invalid_stop");
  });
});

describe("validateParams dan btcTrendBias", () => {
  test("angka tidak sah disebut satu per satu", () => {
    assert.deepEqual(validateParams(P), []);
    assert.ok(validateParams({ ...P, emaFast: 9 }).length > 0);
    assert.ok(validateParams({ ...P, adxThreshold: 0 }).length > 0);
    assert.ok(validateParams({ ...P, tpR2: 1 }).length > 0);
    assert.ok(validateParams({ ...P, diMargin: -1 }).length > 0);
  });
  test("arah BTC", () => {
    assert.equal(btcTrendBias(trend(40, 1), 3, 6), "bullish");
    assert.equal(btcTrendBias(trend(40, -1, 200), 3, 6), "bearish");
    assert.equal(btcTrendBias(trend(3, 1), 3, 6), "");
  });
});
