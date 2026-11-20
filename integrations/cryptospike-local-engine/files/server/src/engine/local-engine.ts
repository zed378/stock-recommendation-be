import type { EngineConfig } from "./config";
import { at } from "./indicators";
import { fetchClosedKlines, type FetchLike } from "./klines";
import { btcTrendBias, evaluateEntry, minHistory } from "./strategy";

export interface LocalSignal {
  id: string;
  symbol: string;
  side: "LONG";
  entryPrice: number;
  sl: number;
  tp1: number;
  tp2: number;
  tp3: number;
  strategy: string;
  btcTrendBias: "bullish" | "bearish" | "";
  analytics: { source: "local-engine"; candleOpenTime: number; reason: string; inputs: Record<string, number | null> };
}

export interface EngineDeps {
  config: EngineConfig;
  fetchFn: FetchLike;
  /** Dipanggil hanya di mode EXECUTE. Biasanya `handleIncomingSignal` milik klien. */
  handleSignal: (signal: LocalSignal) => Promise<void>;
  log: (level: "INFO" | "WARN" | "ERROR" | "SUCCESS", message: string) => void;
  now: () => number;
}

export interface TickResult {
  evaluated: number;
  signals: LocalSignal[];
  skipped: string[];
  errors: string[];
}

export const STRATEGY_NAME = "local-ema-adx-di";

/**
 * Setiap putaran: untuk tiap simbol, ambil candle tertutup, putuskan HANYA pada candle tertutup
 * terbaru yang belum pernah diputuskan, dan keluarkan paling banyak satu sinyal per candle.
 *
 * Aman terhadap restart: id sinyal `local-<simbol>-<waktu buka candle>` sama untuk candle yang
 * sama, dan klien sudah menolak id yang pernah diproses (disimpan ke disk).
 * Satu simbol yang gagal tidak menghentikan simbol lain.
 */
export function createLocalEngine(deps: EngineDeps) {
  const { config } = deps;
  const lastDecided = new Map<string, number>();
  let running = false;

  async function tick(): Promise<TickResult> {
    const result: TickResult = { evaluated: 0, signals: [], skipped: [], errors: [] };
    if (running) {
      result.skipped.push("previous tick still running");
      return result;
    }
    running = true;
    try {
      let bias: "bullish" | "bearish" | "" = "";
      try {
        const btc = await fetchClosedKlines(config.klinesBase, config.btcSymbol, deps.fetchFn, deps.now());
        bias = btcTrendBias(btc, config.params.emaFast, config.params.emaSlow);
      } catch (err) {
        // Tanpa arah BTC filter bawaan klien tidak bisa menahan sinyal; lebih aman tidak bertindak.
        result.errors.push(`${config.btcSymbol}: ${(err as Error).message}`);
        deps.log("WARN", `Local engine: BTC trend unavailable, no signals this round (${(err as Error).message})`);
        return result;
      }
      for (const symbol of config.symbols) {
        try {
          const candles = await fetchClosedKlines(config.klinesBase, symbol, deps.fetchFn, deps.now());
          if (candles.length < minHistory(config.params)) {
            result.skipped.push(`${symbol}: not enough history`);
            continue;
          }
          const last = at(candles, candles.length - 1);
          if ((lastDecided.get(symbol) ?? 0) >= last.openTime) continue;
          lastDecided.set(symbol, last.openTime);
          result.evaluated++;
          const ev = evaluateEntry(candles, config.params);
          if (ev.kind !== "ENTRY") continue;
          const signal: LocalSignal = {
            id: `local-${symbol}-${last.openTime}`,
            symbol,
            side: "LONG",
            entryPrice: ev.entry,
            sl: ev.stop,
            tp1: ev.tp1,
            tp2: ev.tp2,
            tp3: ev.tp3,
            strategy: STRATEGY_NAME,
            btcTrendBias: bias,
            analytics: {
              source: "local-engine",
              candleOpenTime: last.openTime,
              reason: ev.reason,
              inputs: ev.inputs,
            },
          };
          result.signals.push(signal);
          const text = `${symbol} LONG entry ${signal.entryPrice} sl ${signal.sl} tp ${signal.tp1}/${signal.tp2}/${signal.tp3}`;
          if (config.mode === "SHADOW") {
            deps.log("INFO", `Local engine SHADOW signal (not sent to any exchange): ${text}`);
          } else {
            deps.log("INFO", `Local engine signal: ${text}`);
            await deps.handleSignal(signal);
          }
        } catch (err) {
          result.errors.push(`${symbol}: ${(err as Error).message}`);
          deps.log("WARN", `Local engine: ${symbol} skipped (${(err as Error).message})`);
        }
      }
      return result;
    } finally {
      running = false;
    }
  }

  let timer: ReturnType<typeof setInterval> | null = null;
  return {
    tick,
    start(): void {
      if (timer) return;
      void tick();
      timer = setInterval(() => void tick(), config.pollSeconds * 1000);
    },
    stop(): void {
      if (timer) clearInterval(timer);
      timer = null;
    },
  };
}
