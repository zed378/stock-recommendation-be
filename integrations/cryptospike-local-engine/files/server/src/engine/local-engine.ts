import type { EngineConfig } from "./config";
import { buildDossier, type Dossier, type Verdict } from "./ai-assessor";
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
  /** Skor penilai AI (0-100) bila penilai AI menyala; dipakai filter minScore milik klien. */
  score?: number;
  btcTrendBias: "bullish" | "bearish" | "";
  analytics: {
    source: "local-engine";
    candleOpenTime: number;
    reason: string;
    inputs: Record<string, number | null>;
    ai?: Verdict;
  };
}

export interface EngineDeps {
  config: EngineConfig;
  fetchFn: FetchLike;
  /** Dipanggil hanya di mode EXECUTE. Biasanya `handleIncomingSignal` milik klien. */
  handleSignal: (signal: LocalSignal) => Promise<void>;
  log: (level: "INFO" | "WARN" | "ERROR" | "SUCCESS", message: string) => void;
  now: () => number;
  /** Penilai AI (opsional). Tanpa ini, kandidat langsung jadi sinyal. */
  assess?: (dossier: Dossier) => Promise<Verdict>;
  /** Catatan keputusan per kandidat, untuk mengukur nilai AI dari hasil nyata nanti. */
  record?: (entry: DecisionRecord) => void;
}

export interface DecisionRecord {
  at: string;
  symbol: string;
  candleOpenTime: number;
  outcome: "SIGNAL" | "AI_SKIP" | "AI_BELOW_MIN" | "AI_UNAVAILABLE" | "AI_BUDGET";
  mode: string;
  entry: number;
  stop: number;
  verdict?: Verdict;
  error?: string;
}

export interface TickResult {
  evaluated: number;
  aiCalls: number;
  signals: LocalSignal[];
  skipped: string[];
  errors: string[];
}

export const STRATEGY_NAME = "local-ema-adx-di";

/** Membuang derau pecahan biner (356.20000000000005) agar harga di sinyal rapi. Bursa tetap membulatkan ke tick. */
const px = (n: number): number => Number(n.toPrecision(10));

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
    const result: TickResult = { evaluated: 0, aiCalls: 0, signals: [], skipped: [], errors: [] };
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
          const base = {
            at: new Date(deps.now()).toISOString(),
            symbol,
            candleOpenTime: last.openTime,
            mode: config.mode,
            entry: ev.entry,
            stop: ev.stop,
          };
          let verdict: Verdict | undefined;
          if (config.ai) {
            if (!deps.assess) throw new Error("AI reviewer is configured but no assessor was given");
            if (result.aiCalls >= config.ai.maxCallsPerTick) {
              result.skipped.push(`${symbol}: AI call budget for this round used up`);
              deps.record?.({ ...base, outcome: "AI_BUDGET" });
              deps.log("WARN", `Local engine: ${symbol} candidate dropped, AI call budget used up`);
              continue;
            }
            result.aiCalls++;
            try {
              const dossier = buildDossier(symbol, candles, ev, bias, [config.params.tpR1, config.params.tpR2, config.params.tpR3], config.params);
              verdict = await deps.assess(dossier);
            } catch (err) {
              // Tanpa penilaian, tidak bertindak. Kandidat ini tidak diulang: candle ini sudah diputuskan.
              result.errors.push(`${symbol}: AI ${(err as Error).message}`);
              deps.record?.({ ...base, outcome: "AI_UNAVAILABLE", error: (err as Error).message });
              deps.log("WARN", `Local engine: ${symbol} candidate dropped, AI reviewer unavailable (${(err as Error).message})`);
              continue;
            }
            if (verdict.verdict !== "TAKE") {
              deps.record?.({ ...base, outcome: "AI_SKIP", verdict });
              deps.log("INFO", `Local engine: ${symbol} candidate skipped by AI (score ${verdict.score}): ${verdict.reasons.join("; ")}`);
              continue;
            }
            if (verdict.score < config.ai.minScore) {
              deps.record?.({ ...base, outcome: "AI_BELOW_MIN", verdict });
              deps.log("INFO", `Local engine: ${symbol} candidate below the AI minimum score (${verdict.score} < ${config.ai.minScore})`);
              continue;
            }
          }
          const signal: LocalSignal = {
            id: `local-${symbol}-${last.openTime}`,
            symbol,
            side: "LONG",
            entryPrice: px(ev.entry),
            sl: px(ev.stop),
            tp1: px(ev.tp1),
            tp2: px(ev.tp2),
            tp3: px(ev.tp3),
            strategy: STRATEGY_NAME,
            ...(verdict ? { score: verdict.score } : {}),
            btcTrendBias: bias,
            analytics: {
              source: "local-engine",
              candleOpenTime: last.openTime,
              reason: ev.reason,
              inputs: ev.inputs,
              ...(verdict ? { ai: verdict } : {}),
            },
          };
          result.signals.push(signal);
          deps.record?.({ ...base, outcome: "SIGNAL", ...(verdict ? { verdict } : {}) });
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
