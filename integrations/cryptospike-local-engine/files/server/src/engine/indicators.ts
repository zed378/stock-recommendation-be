/**
 * Indikator untuk mesin strategi lokal. Ditulis agar sama persis dengan rumusnya di AIDSS Trader
 * (EMA berbenih rata-rata sederhana, ATR dan ADX Wilder), supaya hasil keduanya bisa dibandingkan.
 * Fungsi murni: tanpa jaringan, tanpa database, tanpa jam.
 */

export interface Candle {
  openTime: number; // ms
  closeTime: number; // ms
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export type Series = Array<number | null>;

/** Akses indeks yang pasti ada (tsconfig klien memakai noUncheckedIndexedAccess). */
export function at<T>(items: ArrayLike<T>, i: number): T {
  const v = items[i];
  if (v === undefined) throw new Error(`index ${i} out of range`);
  return v;
}

export function ema(values: number[], period: number): Series {
  if (!Number.isInteger(period) || period < 1) throw new Error("period must be at least 1");
  const out: Series = new Array(values.length).fill(null);
  if (values.length < period) return out;
  const alpha = 2 / (period + 1);
  let current = values.slice(0, period).reduce((a, b) => a + b, 0) / period;
  out[period - 1] = current;
  for (let i = period; i < values.length; i++) {
    current = at(values, i) * alpha + current * (1 - alpha);
    out[i] = current;
  }
  return out;
}

export function trueRanges(candles: Candle[]): Series {
  const out: Series = [null];
  for (let i = 1; i < candles.length; i++) {
    const prev = at(candles, i - 1);
    const cur = at(candles, i);
    out.push(
      Math.max(
        cur.high - cur.low,
        Math.abs(cur.high - prev.close),
        Math.abs(cur.low - prev.close),
      ),
    );
  }
  return out;
}

export function atr(candles: Candle[], period: number): Series {
  const trs = trueRanges(candles);
  const out: Series = new Array(candles.length).fill(null);
  if (candles.length < period + 1) return out;
  let current = 0;
  for (let i = 1; i <= period; i++) current += at(trs, i) ?? 0;
  current /= period;
  out[period] = current;
  for (let i = period + 1; i < candles.length; i++) {
    current = (current * (period - 1) + (at(trs, i) ?? 0)) / period;
    out[i] = current;
  }
  return out;
}

function directionalMoves(candles: Candle[]): { plus: number[]; minus: number[]; trs: number[] } {
  const plus = [0];
  const minus = [0];
  for (let i = 1; i < candles.length; i++) {
    const cur = at(candles, i);
    const prev = at(candles, i - 1);
    const up = cur.high - prev.high;
    const down = prev.low - cur.low;
    plus.push(up > down && up > 0 ? up : 0);
    minus.push(down > up && down > 0 ? down : 0);
  }
  return { plus, minus, trs: trueRanges(candles).map((t) => t ?? 0) };
}

/** Wilder ADX. Butuh sekitar 2 * period candle sebelum nilai pertama. */
export function adx(candles: Candle[], period: number): Series {
  const n = candles.length;
  const out: Series = new Array(n).fill(null);
  if (n < 2 * period + 1) return out;
  const { plus, minus, trs } = directionalMoves(candles);
  let sTr = 0;
  let sP = 0;
  let sM = 0;
  for (let i = 1; i <= period; i++) {
    sTr += at(trs, i);
    sP += at(plus, i);
    sM += at(minus, i);
  }
  const dxOf = (tr: number, p: number, m: number): number => {
    if (tr === 0) return 0;
    const diP = (100 * p) / tr;
    const diM = (100 * m) / tr;
    const total = diP + diM;
    return total === 0 ? 0 : (100 * Math.abs(diP - diM)) / total;
  };
  const dx: number[] = [dxOf(sTr, sP, sM)];
  for (let i = period + 1; i < n; i++) {
    sTr = sTr - sTr / period + at(trs, i);
    sP = sP - sP / period + at(plus, i);
    sM = sM - sM / period + at(minus, i);
    dx.push(dxOf(sTr, sP, sM));
  }
  if (dx.length < period) return out;
  let current = dx.slice(0, period).reduce((a, b) => a + b, 0) / period;
  out[2 * period - 1] = current;
  for (let k = period; k < dx.length; k++) {
    current = (current * (period - 1) + at(dx, k)) / period;
    out[period + k] = current;
  }
  return out;
}

/** Wilder +DI dan -DI, dalam persen (null sebelum indeks `period`). */
export function directionalLines(candles: Candle[], period: number): { plus: Series; minus: Series } {
  const n = candles.length;
  const plus: Series = new Array(n).fill(null);
  const minus: Series = new Array(n).fill(null);
  if (n < period + 1) return { plus, minus };
  const moves = directionalMoves(candles);
  let sTr = 0;
  let sP = 0;
  let sM = 0;
  for (let i = 1; i <= period; i++) {
    sTr += at(moves.trs, i);
    sP += at(moves.plus, i);
    sM += at(moves.minus, i);
  }
  for (let i = period; i < n; i++) {
    if (i > period) {
      sTr = sTr - sTr / period + at(moves.trs, i);
      sP = sP - sP / period + at(moves.plus, i);
      sM = sM - sM / period + at(moves.minus, i);
    }
    plus[i] = sTr === 0 ? 0 : (100 * sP) / sTr;
    minus[i] = sTr === 0 ? 0 : (100 * sM) / sTr;
  }
  return { plus, minus };
}
