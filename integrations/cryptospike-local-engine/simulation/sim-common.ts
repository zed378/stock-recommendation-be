import fs from "fs";
import os from "os";
import path from "path";
import { startMockSignalServer } from "./mock-signal-server";

export const TOKEN = "sim-token-not-a-real-token";
export const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
export const say = (s = "") => console.log(s);

/**
 * Menyalakan server sinyal palsu dan memuat KODE ASLI klien dengan database Prisma diganti memori.
 * Tidak ada koneksi keluar, tidak ada kunci, tidak ada bursa. Tokocrypto dalam mode dry-run;
 * Binance tanpa kunci (selalu DISABLED). Jalankan dari folder server/ klien.
 */
export async function bootClient(tokoOverrides: Record<string, unknown> = {}) {
  const work = fs.mkdtempSync(path.join(os.tmpdir(), "cs-sim-"));
  process.chdir(work);
  process.env.SIGNAL_DEDUPE_FILE = path.join(work, "processed.json");
  const server = await startMockSignalServer(TOKEN);
  process.env.SERVER_URL = server.url;

  const serverDir = path.resolve(__dirname, "..");
  const dbFile = require.resolve(path.join(serverDir, "src/lib/db"));
  const state = {
    app: { id: 1, targetExchange: "BOTH", clientToken: TOKEN },
    binance: { id: 1, environment: "TESTNET" },
    toko: {
      id: 1, autoExecute: true, dryRun: true, quoteAsset: "USDT", riskPerTradePct: 10,
      maxOpenPositions: 3, coinFilterMode: "BLACKLIST", targetCoins: "SCAMUSDT", ...tokoOverrides,
    },
    spot: [] as any[],
  };
  const fakePrisma = {
    appConfig: { findUnique: async () => state.app },
    binanceConfig: { findUnique: async () => state.binance },
    tokocryptoConfig: { findUnique: async () => state.toko },
    spotTrade: {
      count: async () => state.spot.filter((s) => s.status === "OPEN").length,
      create: async ({ data }: any) => (state.spot.push(data), data),
    },
  };
  (require as any).cache[dbFile] = { id: dbFile, filename: dbFile, loaded: true, exports: { prisma: fakePrisma } };
  const svc = await import("../src/services/socket.service");
  return { server, state, ...svc };
}
