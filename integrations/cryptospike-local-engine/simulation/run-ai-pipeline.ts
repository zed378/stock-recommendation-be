/**
 * Simulasi alur lengkap: kandidat dari aturan -> penilai AI -> sinyal -> (server sinyal palsu) ->
 * klien ASLI -> eksekutor Tokocrypto dry-run.
 *
 * Yang palsu: candle (deret sintetis), jawaban penilai AI (tanpa memanggil Anthropic sungguhan),
 * server sinyal, dan database. Yang asli: aturan masuk, dossier dan prompt AI, validasi jawaban AI,
 * pengawal "gagal = tidak bertindak", serta seluruh kode penerima sinyal dan eksekutor klien.
 * Jalankan dari folder server/ klien:  npx tsx simulation/run-ai-pipeline.ts
 */
import { assessWithAnthropic } from "../src/engine/ai-assessor";
import { loadEngineConfig } from "../src/engine/config";
import { createLocalEngine, type DecisionRecord } from "../src/engine/local-engine";
import { bootClient, say, sleep, TOKEN } from "./sim-common";

const H4 = 4 * 3600_000;
const NOW = 100 * H4 + 5_000;

function rows(n: number, step: number, from: number): unknown[][] {
  return Array.from({ length: n }, (_, i) => {
    const c = from + step * i;
    const open = (99 - (n - 1) + i) * H4;
    return [open, String(c - step), String(c + 0.4 * step), String(c - 0.4 * step), String(c), "1", open + H4 - 1];
  });
}
const PRICES: Record<string, [number, number]> = {
  BTCUSDT: [1, 100], ETHUSDT: [1, 300], SOLUSDT: [1, 150], ADAUSDT: [0.01, 5], XRPUSDT: [0.01, 6],
};

async function main() {
  const { server, state, connectToNestJS, disconnectSocket } = await bootClient({ maxOpenPositions: 5 });
  await connectToNestJS(TOKEN);
  await sleep(700);

  const loaded = loadEngineConfig({
    LOCAL_ENGINE_ENABLED: "true", LOCAL_ENGINE_MODE: "EXECUTE", LOCAL_ENGINE_CONFIRM_EXECUTE: "yes",
    LOCAL_ENGINE_SYMBOLS: "ETHUSDT,SOLUSDT,ADAUSDT,XRPUSDT",
    LOCAL_ENGINE_EMA_FAST: "3", LOCAL_ENGINE_EMA_SLOW: "6", LOCAL_ENGINE_ADX_PERIOD: "3",
    LOCAL_ENGINE_ADX_THRESHOLD: "20", LOCAL_ENGINE_ATR_PERIOD: "3", LOCAL_ENGINE_ATR_STOP_MULTIPLE: "2",
    LOCAL_ENGINE_DI_MARGIN: "0", LOCAL_ENGINE_TP_R1: "1.5", LOCAL_ENGINE_TP_R2: "2.5", LOCAL_ENGINE_TP_R3: "4",
    LOCAL_ENGINE_AI_ENABLED: "true", LOCAL_ENGINE_AI_MODEL: "sim-model", ANTHROPIC_API_KEY: "sk-sim-not-a-key",
    LOCAL_ENGINE_AI_MIN_SCORE: "70", LOCAL_ENGINE_AI_MAX_CALLS_PER_TICK: "10",
  } as NodeJS.ProcessEnv);
  if (loaded.status !== "ready" || !loaded.config.ai) throw new Error(JSON.stringify(loaded));
  const ai = loaded.config.ai;

  // Penilai AI PALSU di lapisan HTTP: meniru bentuk jawaban Anthropic, dengan jawaban per simbol.
  const scripted: Record<string, () => unknown> = {
    ETHUSDT: () => ({ score: 85, verdict: "TAKE", confidence: "HIGH", reasons: ["trend, ADX and DI agree"], risks: ["extended 7d move"] }),
    SOLUSDT: () => ({ score: 40, verdict: "SKIP", confidence: "MEDIUM", reasons: ["move looks stretched"], risks: ["stop too wide"] }),
    XRPUSDT: () => ({ score: 60, verdict: "TAKE", confidence: "LOW", reasons: ["acceptable but weak"], risks: [] }),
  };
  const fakeFetch = async (url: string, init?: any) => {
    if (url.startsWith("https://fake-anthropic.local")) {
      const symbol = JSON.parse(init.body).messages[0].content.match(/"symbol":"([A-Z]+)"/)[1] as string;
      if (symbol === "ADAUSDT") return { ok: false, status: 529, json: async () => ({}) }; // AI tidak tersedia
      return { ok: true, status: 200, json: async () => ({ content: [{ type: "text", text: JSON.stringify(scripted[symbol]!()) }] }) };
    }
    const symbol = new URL(url).searchParams.get("symbol")!;
    const [scale, start] = PRICES[symbol]!;
    return { ok: true, status: 200, json: async () => rows(60, scale, start) };
  };

  const records: DecisionRecord[] = [];
  const engine = createLocalEngine({
    config: loaded.config,
    fetchFn: fakeFetch as never,
    assess: (d) => assessWithAnthropic(d, ai, "sk-sim-not-a-key", fakeFetch as never, "https://fake-anthropic.local"),
    handleSignal: async (signal) => {
      say(`  -> sinyal dikirim ke klien lewat server sinyal palsu: ${signal.symbol} score ${signal.score} entry ${signal.entryPrice.toFixed(4)} sl ${signal.sl.toFixed(4)} tp1 ${signal.tp1.toFixed(4)}`);
      server.emit(signal);
      await sleep(400);
    },
    log: (l, m) => say(`  [engine ${l}] ${m}`),
    now: () => NOW,
    record: (e) => void records.push(e),
  });

  say("=== Satu putaran mesin: 4 simbol, semuanya lolos aturan masuk (pasar naik sintetis) ===");
  const r = await engine.tick();

  say("\n=== Catatan keputusan (decision log) ===");
  for (const e of records) say(`  ${e.symbol}: ${e.outcome}${e.verdict ? ` (skor ${e.verdict.score}, ${e.verdict.verdict}, ${e.verdict.reasons.join("; ")})` : ""}${e.error ? ` [${e.error}]` : ""}`);

  say("\n=== Hasil ===");
  say(`  kandidat dari aturan: 4, panggilan AI: ${r.aiCalls}, sinyal keluar: ${r.signals.length}`);
  say(`  posisi spot dry-run di klien: ${state.spot.map((s) => s.symbol).join(", ") || "-"}`);
  say(`  ACK ke server sinyal (RECEIVED): ${server.acks.filter((a) => a.stage === "RECEIVED").map((a) => a.signalId).join(", ")}`);
  disconnectSocket();
  await server.close();
  process.exit(0);
}
main().catch((e) => {
  console.error(e);
  process.exit(1);
});
