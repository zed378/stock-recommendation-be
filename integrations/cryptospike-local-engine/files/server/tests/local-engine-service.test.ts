import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { loadEngineConfig } from "../src/engine/config";
import { createLocalEngine, type LocalSignal } from "../src/engine/local-engine";
import { fetchClosedKlines, KlinesError } from "../src/engine/klines";
import { at, type Candle } from "../src/engine/indicators";

/** Tanpa jaringan: semua panggilan dialihkan ke fungsi palsu. Jalankan: npx tsx --test tests/local-engine-service.test.ts */
const ENV = {
  LOCAL_ENGINE_ENABLED: "true",
  LOCAL_ENGINE_SYMBOLS: "ETHUSDT,SOLUSDT",
  LOCAL_ENGINE_EMA_FAST: "3",
  LOCAL_ENGINE_EMA_SLOW: "6",
  LOCAL_ENGINE_ADX_PERIOD: "3",
  LOCAL_ENGINE_ADX_THRESHOLD: "20",
  LOCAL_ENGINE_ATR_PERIOD: "3",
  LOCAL_ENGINE_ATR_STOP_MULTIPLE: "2",
  LOCAL_ENGINE_DI_MARGIN: "0",
  LOCAL_ENGINE_TP_R1: "1.5",
  LOCAL_ENGINE_TP_R2: "2.5",
  LOCAL_ENGINE_TP_R3: "4",
} as NodeJS.ProcessEnv;
const H4 = 4 * 3600_000;
const NOW = 100 * H4 + 5_000; // 5 detik setelah candle ke-99 tutup

function rows(n: number, step: number, from: number, includeOpen = true, lastOpen = 99): unknown[][] {
  const out: unknown[][] = [];
  for (let i = 0; i < n; i++) {
    const c = from + step * i;
    const open = (lastOpen - (n - 1) + i) * H4;
    out.push([open, String(c - step), String(c + 0.4), String(c - 0.4), String(c), "1", open + H4 - 1]);
  }
  if (includeOpen) out.push([(lastOpen + 1) * H4, "1", "2", "1", "1.5", "1", (lastOpen + 2) * H4 - 1]); // candle berjalan
  return out;
}

function harness(overrides: Partial<NodeJS.ProcessEnv> = {}, perSymbol?: (s: string) => unknown) {
  const loaded = loadEngineConfig({ ...ENV, ...overrides });
  assert.equal(loaded.status, "ready");
  if (loaded.status !== "ready") throw new Error("not ready");
  const sent: LocalSignal[] = [];
  const logs: string[] = [];
  const calls: string[] = [];
  let now = NOW;
  const engine = createLocalEngine({
    config: loaded.config,
    fetchFn: async (url) => {
      const symbol = new URL(url).searchParams.get("symbol")!;
      calls.push(symbol);
      const body = perSymbol ? perSymbol(symbol) : symbol === "BTCUSDT" ? rows(60, 1, 100) : rows(60, 1, 100);
      if (body instanceof Error) throw body;
      return { ok: true, status: 200, json: async () => body };
    },
    handleSignal: async (s) => void sent.push(s),
    log: (_l, m) => void logs.push(m),
    now: () => now,
  });
  return { engine, sent, logs, calls, setNow: (n: number) => (now = n), loaded };
}

describe("konfigurasi", () => {
  test("mati secara bawaan", () => assert.deepEqual(loadEngineConfig({}), { status: "disabled" }));
  test("satu angka kosong: tidak jalan, dan menyebut yang kurang", () => {
    const { LOCAL_ENGINE_TP_R2, ...rest } = ENV;
    void LOCAL_ENGINE_TP_R2;
    const r = loadEngineConfig(rest as NodeJS.ProcessEnv);
    assert.equal(r.status, "invalid");
    if (r.status === "invalid") assert.ok(r.problems.some((p) => p.includes("LOCAL_ENGINE_TP_R2")));
  });
  test("simbol dan angka tidak sah ditolak", () => {
    for (const bad of [{ LOCAL_ENGINE_SYMBOLS: "btc/usdt" }, { LOCAL_ENGINE_SYMBOLS: "" }, { LOCAL_ENGINE_EMA_FAST: "9" }, { LOCAL_ENGINE_MODE: "LIVE" }, { LOCAL_ENGINE_KLINES_BASE: "http://x" }]) {
      assert.equal(loadEngineConfig({ ...ENV, ...bad }).status, "invalid", JSON.stringify(bad));
    }
  });
  test("mode bawaan SHADOW; EXECUTE tanpa konfirmasi turun ke SHADOW dan memberi tahu", () => {
    const a = loadEngineConfig(ENV);
    assert.ok(a.status === "ready" && a.config.mode === "SHADOW");
    const b = loadEngineConfig({ ...ENV, LOCAL_ENGINE_MODE: "EXECUTE" });
    assert.ok(b.status === "ready" && b.config.mode === "SHADOW" && b.notes.length === 1);
    const c = loadEngineConfig({ ...ENV, LOCAL_ENGINE_MODE: "EXECUTE", LOCAL_ENGINE_CONFIRM_EXECUTE: "yes" });
    assert.ok(c.status === "ready" && c.config.mode === "EXECUTE");
  });
});

describe("mesin", () => {
  test("SHADOW: sinyal hanya dicatat, tidak pernah dikirim", async () => {
    const h = harness();
    const r = await h.engine.tick();
    assert.equal(r.signals.length, 2);
    assert.equal(h.sent.length, 0);
    assert.ok(h.logs.some((l) => l.includes("SHADOW") && l.includes("not sent to any exchange")));
  });
  test("EXECUTE: satu sinyal per simbol, dengan id, SL, tiga TP dan arah BTC", async () => {
    const h = harness({ LOCAL_ENGINE_MODE: "EXECUTE", LOCAL_ENGINE_CONFIRM_EXECUTE: "yes" });
    await h.engine.tick();
    assert.equal(h.sent.length, 2);
    const s = at(h.sent, 0);
    assert.equal(s.id, `local-ETHUSDT-${99 * H4}`);
    assert.ok(s.sl < s.entryPrice && s.entryPrice < s.tp1 && s.tp1 < s.tp2 && s.tp2 < s.tp3);
    assert.equal(s.btcTrendBias, "bullish");
    assert.equal(s.side, "LONG");
  });
  test("candle yang sama tidak diputuskan dua kali; candle baru diputuskan", async () => {
    let data = (_s: string): unknown => rows(60, 1, 100);
    const h = harness({ LOCAL_ENGINE_MODE: "EXECUTE", LOCAL_ENGINE_CONFIRM_EXECUTE: "yes" }, (s) => data(s));
    await h.engine.tick();
    await h.engine.tick();
    assert.equal(h.sent.length, 2); // dua simbol, sekali
    // satu candle lagi sudah tutup
    h.setNow(NOW + H4);
    data = () => rows(61, 1, 100, true, 100);
    await h.engine.tick();
    assert.equal(h.sent.length, 4);
    assert.ok(h.sent.some((s) => s.id === `local-ETHUSDT-${100 * H4}`));
  });
  test("candle yang belum tutup tidak pernah dipakai", async () => {
    const out: Candle[] = await fetchClosedKlines("https://x", "ETHUSDT", async () => ({ ok: true, status: 200, json: async () => rows(10, 1, 100, true) }), NOW);
    assert.equal(out.length, 10); // 11 baris diterima, yang berjalan dibuang
    assert.ok(out.every((c) => c.closeTime < NOW));
  });
  test("satu simbol gagal tidak menghentikan yang lain", async () => {
    const h = harness({}, (s) => (s === "ETHUSDT" ? new Error("boom") : rows(60, 1, 100)));
    const r = await h.engine.tick();
    assert.equal(r.errors.length, 1);
    assert.equal(r.signals.length, 1);
    assert.equal(at(r.signals, 0).symbol, "SOLUSDT");
  });
  test("arah BTC tidak tersedia: tidak ada sinyal sama sekali", async () => {
    const h = harness({ LOCAL_ENGINE_MODE: "EXECUTE", LOCAL_ENGINE_CONFIRM_EXECUTE: "yes" }, (s) => (s === "BTCUSDT" ? new Error("down") : rows(60, 1, 100)));
    const r = await h.engine.tick();
    assert.equal(h.sent.length, 0);
    assert.equal(r.signals.length, 0);
    assert.ok(r.errors.length === 1);
  });
  test("pasar turun: tidak ada sinyal", async () => {
    const h = harness({}, () => rows(60, -1, 200));
    assert.equal((await h.engine.tick()).signals.length, 0);
  });
  test("data rusak ditolak seluruhnya", async () => {
    const bad = async (body: unknown) =>
      fetchClosedKlines("https://x", "ETHUSDT", async () => ({ ok: true, status: 200, json: async () => body }), NOW);
    await assert.rejects(() => bad({ not: "a list" }), KlinesError);
    await assert.rejects(() => bad([[1, "a", "b", "c", "d", "e", 9]]), KlinesError);
    await assert.rejects(() => bad([[1, "5", "4", "6", "5", "1", 9]]), KlinesError); // high < low
    await assert.rejects(() => bad([[1, "5", "6", "4", "5", "1", 9], [1, "5", "6", "4", "5", "1", 9]]), KlinesError);
    await assert.rejects(
      () => fetchClosedKlines("https://x", "ETHUSDT", async () => ({ ok: false, status: 418, json: async () => [] }), NOW),
      KlinesError,
    );
  });
});
