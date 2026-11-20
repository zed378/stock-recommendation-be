import { validateParams, type StrategyParams } from "./strategy";

export type EngineMode = "SHADOW" | "EXECUTE";

export interface EngineConfig {
  mode: EngineMode;
  symbols: string[];
  klinesBase: string;
  params: StrategyParams;
  btcSymbol: string;
  pollSeconds: number;
}

export type EngineConfigResult =
  | { status: "disabled" }
  | { status: "invalid"; problems: string[] }
  | { status: "ready"; config: EngineConfig; notes: string[] };

const SYMBOL = /^[A-Z0-9]{5,20}$/;

/**
 * Membaca konfigurasi dari environment. Dimatikan secara bawaan. Tidak ada angka bawaan untuk
 * strategi: bila satu saja kosong, mesin tidak jalan dan menyebut apa yang kurang.
 *
 * Mode bawaan SHADOW: sinyal hanya dicatat di log, tidak pernah dikirim ke bursa. Mode EXECUTE butuh
 * LOCAL_ENGINE_CONFIRM_EXECUTE=yes; tanpa itu mesin turun ke SHADOW dan mengatakannya.
 */
export function loadEngineConfig(env: NodeJS.ProcessEnv): EngineConfigResult {
  if ((env.LOCAL_ENGINE_ENABLED ?? "").trim().toLowerCase() !== "true") return { status: "disabled" };
  const problems: string[] = [];
  const notes: string[] = [];

  const symbols = (env.LOCAL_ENGINE_SYMBOLS ?? "")
    .split(",")
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean);
  if (symbols.length === 0) problems.push("LOCAL_ENGINE_SYMBOLS is required (comma list such as BTCUSDT,ETHUSDT)");
  for (const s of symbols) if (!SYMBOL.test(s)) problems.push(`LOCAL_ENGINE_SYMBOLS: ${s} is not a symbol`);
  if (new Set(symbols).size !== symbols.length) problems.push("LOCAL_ENGINE_SYMBOLS has a duplicate");

  const num = (name: string): number => {
    const raw = (env[name] ?? "").trim();
    const n = Number(raw);
    if (raw === "" || !Number.isFinite(n)) {
      problems.push(`${name} is required and must be a number`);
      return NaN;
    }
    return n;
  };
  const params: StrategyParams = {
    emaFast: num("LOCAL_ENGINE_EMA_FAST"),
    emaSlow: num("LOCAL_ENGINE_EMA_SLOW"),
    adxPeriod: num("LOCAL_ENGINE_ADX_PERIOD"),
    adxThreshold: num("LOCAL_ENGINE_ADX_THRESHOLD"),
    atrPeriod: num("LOCAL_ENGINE_ATR_PERIOD"),
    atrStopMultiple: num("LOCAL_ENGINE_ATR_STOP_MULTIPLE"),
    diMargin: num("LOCAL_ENGINE_DI_MARGIN"),
    tpR1: num("LOCAL_ENGINE_TP_R1"),
    tpR2: num("LOCAL_ENGINE_TP_R2"),
    tpR3: num("LOCAL_ENGINE_TP_R3"),
  };
  if (Object.values(params).every((v) => Number.isFinite(v))) problems.push(...validateParams(params));

  let mode: EngineMode = "SHADOW";
  const wanted = (env.LOCAL_ENGINE_MODE ?? "SHADOW").trim().toUpperCase();
  if (wanted !== "SHADOW" && wanted !== "EXECUTE") problems.push("LOCAL_ENGINE_MODE must be SHADOW or EXECUTE");
  if (wanted === "EXECUTE") {
    if ((env.LOCAL_ENGINE_CONFIRM_EXECUTE ?? "").trim().toLowerCase() === "yes") mode = "EXECUTE";
    else notes.push("LOCAL_ENGINE_MODE=EXECUTE needs LOCAL_ENGINE_CONFIRM_EXECUTE=yes; running in SHADOW instead");
  }

  const klinesBase = (env.LOCAL_ENGINE_KLINES_BASE ?? "https://api.binance.com").trim().replace(/\/+$/, "");
  if (!/^https:\/\/[a-z0-9.-]+(:\d+)?$/i.test(klinesBase)) problems.push("LOCAL_ENGINE_KLINES_BASE must be an https origin");

  if (problems.length > 0) return { status: "invalid", problems };
  return {
    status: "ready",
    notes,
    config: { mode, symbols, klinesBase, params, btcSymbol: "BTCUSDT", pollSeconds: 60 },
  };
}
