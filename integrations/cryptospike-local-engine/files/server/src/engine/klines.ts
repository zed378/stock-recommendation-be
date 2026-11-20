import { at, type Candle } from "./indicators";

export type FetchInit = {
  method?: string;
  headers?: Record<string, string>;
  body?: string;
  signal?: AbortSignal;
};

export type FetchLike = (url: string, init?: FetchInit) => Promise<{
  ok: boolean;
  status: number;
  json(): Promise<unknown>;
}>;

export class KlinesError extends Error {}

/**
 * Candle 4 jam TERTUTUP dari endpoint publik Binance (`/api/v3/klines`, tanpa tanda tangan, tanpa
 * kunci API). Candle yang belum tutup dibuang, karena memutuskan di atasnya akan berubah sebelum
 * ditutup. Data yang rusak membuat seluruh pengambilan ditolak, tidak diperbaiki diam-diam.
 */
export async function fetchClosedKlines(
  base: string,
  symbol: string,
  fetchFn: FetchLike,
  nowMs: number,
  limit = 300,
): Promise<Candle[]> {
  const url = `${base}/api/v3/klines?symbol=${encodeURIComponent(symbol)}&interval=4h&limit=${limit}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10_000);
  let res;
  try {
    res = await fetchFn(url, { signal: controller.signal });
  } catch (err) {
    throw new KlinesError(`klines request for ${symbol} failed: ${(err as Error).name}`);
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) throw new KlinesError(`klines request for ${symbol} answered ${res.status}`);
  const body = await res.json();
  if (!Array.isArray(body)) throw new KlinesError(`klines for ${symbol}: expected a list`);
  const out: Candle[] = [];
  for (const row of body) {
    if (!Array.isArray(row) || row.length < 7) throw new KlinesError(`klines for ${symbol}: bad row`);
    const c: Candle = {
      openTime: Number(row[0]),
      open: Number(row[1]),
      high: Number(row[2]),
      low: Number(row[3]),
      close: Number(row[4]),
      volume: Number(row[5]),
      closeTime: Number(row[6]),
    };
    if (![c.openTime, c.open, c.high, c.low, c.close, c.volume, c.closeTime].every(Number.isFinite)) {
      throw new KlinesError(`klines for ${symbol}: non-numeric value`);
    }
    if (c.high < c.low || c.low <= 0) throw new KlinesError(`klines for ${symbol}: impossible candle`);
    if (c.closeTime >= nowMs) continue; // belum tutup
    out.push(c);
  }
  out.sort((a, b) => a.openTime - b.openTime);
  for (let i = 1; i < out.length; i++) {
    if (at(out, i).openTime === at(out, i - 1).openTime) throw new KlinesError(`klines for ${symbol}: duplicate candle`);
  }
  return out;
}
