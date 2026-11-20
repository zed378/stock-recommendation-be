import { adx, at, atr, directionalLines, ema, type Candle } from "./indicators";

/**
 * Aturan masuk: EMA + ADX dengan konfirmasi arah DI (varian D2 di AIDSS Trader).
 *
 * Masuk LONG pada penutupan candle bila: EMA cepat di atas EMA lambat, ADX di atas ambang, dan
 * +DI melebihi -DI lebih dari `diMargin`. Stop = close dikurangi kelipatan ATR. Target TP1..TP3
 * adalah kelipatan R (jarak entry ke stop).
 *
 * PENTING: aturan KELUAR di AIDSS adalah "filter tren gagal". Di klien ini posisi dikelola oleh
 * tangga TP dan SL milik klien (TP 50/30/20, break-even, trailing), jadi keluarnya BERBEDA dan hasil
 * backtest AIDSS tidak berlaku untuk konfigurasi ini.
 *
 * Tidak ada angka bawaan: semua parameter wajib diisi pemilik (lihat config.ts).
 */
export interface StrategyParams {
  emaFast: number;
  emaSlow: number;
  adxPeriod: number;
  adxThreshold: number;
  atrPeriod: number;
  atrStopMultiple: number;
  diMargin: number;
  tpR1: number;
  tpR2: number;
  tpR3: number;
}

export function minHistory(p: StrategyParams): number {
  return Math.max(p.emaSlow, 2 * p.adxPeriod + 1, p.atrPeriod + 1) + 1;
}

export type Evaluation =
  | { kind: "NONE"; reason: string; inputs: Record<string, number | null> }
  | {
      kind: "ENTRY";
      reason: string;
      entry: number;
      stop: number;
      tp1: number;
      tp2: number;
      tp3: number;
      inputs: Record<string, number | null>;
    };

export function validateParams(p: StrategyParams): string[] {
  const problems: string[] = [];
  const int = (n: number) => Number.isInteger(n) && n >= 1;
  if (!int(p.emaFast) || !int(p.emaSlow) || p.emaFast >= p.emaSlow) problems.push("emaFast must be below emaSlow");
  if (!int(p.adxPeriod) || !int(p.atrPeriod)) problems.push("adxPeriod and atrPeriod must be whole numbers from 1");
  if (!(p.adxThreshold > 0 && p.adxThreshold <= 100)) problems.push("adxThreshold must be above 0 and at most 100");
  if (!(p.atrStopMultiple > 0)) problems.push("atrStopMultiple must be positive");
  if (!(p.diMargin >= 0 && p.diMargin < 100)) problems.push("diMargin must be from 0 up to 100");
  if (!(p.tpR1 > 0 && p.tpR2 > p.tpR1 && p.tpR3 > p.tpR2)) problems.push("need 0 < tpR1 < tpR2 < tpR3");
  return problems;
}

/** `candles` harus candle TERTUTUP saja, urut waktu naik. Candle terakhir adalah yang diputuskan. */
export function evaluateEntry(candles: Candle[], p: StrategyParams): Evaluation {
  if (candles.length < minHistory(p)) {
    return { kind: "NONE", reason: "insufficient_history", inputs: { bars: candles.length } };
  }
  const closes = candles.map((c) => c.close);
  const last = candles.length - 1;
  const fast = at(ema(closes, p.emaFast), last);
  const slow = at(ema(closes, p.emaSlow), last);
  const strength = at(adx(candles, p.adxPeriod), last);
  const vol = at(atr(candles, p.atrPeriod), last);
  const { plus, minus } = directionalLines(candles, p.adxPeriod);
  const pdi = at(plus, last);
  const mdi = at(minus, last);
  const entry = at(closes, last);
  const inputs = { close: entry, emaFast: fast, emaSlow: slow, adx: strength, atr: vol, plusDi: pdi, minusDi: mdi };
  if ([fast, slow, strength, vol, pdi, mdi].some((v) => v === null || !Number.isFinite(v as number))) {
    return { kind: "NONE", reason: "insufficient_history", inputs };
  }
  if (!((fast as number) > (slow as number))) return { kind: "NONE", reason: "trend_not_up", inputs };
  if (!((strength as number) > p.adxThreshold)) return { kind: "NONE", reason: "adx_too_low", inputs };
  if (!((pdi as number) - (mdi as number) > p.diMargin)) return { kind: "NONE", reason: "di_not_confirming", inputs };
  const stop = entry - p.atrStopMultiple * (vol as number);
  const risk = entry - stop;
  if (!(stop > 0) || !(risk > 0)) return { kind: "NONE", reason: "invalid_stop", inputs };
  return {
    kind: "ENTRY",
    reason: "trend_up_strong_and_di_confirmed",
    entry,
    stop,
    tp1: entry + p.tpR1 * risk,
    tp2: entry + p.tpR2 * risk,
    tp3: entry + p.tpR3 * risk,
    inputs,
  };
}

/** Arah tren BTC untuk filter bawaan klien: "bullish" bila EMA cepat di atas lambat, selain itu "bearish". */
export function btcTrendBias(candles: Candle[], emaFast: number, emaSlow: number): "bullish" | "bearish" | "" {
  if (candles.length < emaSlow) return "";
  const closes = candles.map((c) => c.close);
  const last = candles.length - 1;
  const fast = at(ema(closes, emaFast), last);
  const slow = at(ema(closes, emaSlow), last);
  if (fast === null || slow === null) return "";
  return fast > slow ? "bullish" : "bearish";
}
