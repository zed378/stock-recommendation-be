/**
 * Simulasi: bagaimana klien menangkap sinyal dari luar, dengan KODE ASLI klien.
 *
 * Yang asli (tidak diubah): server/src/services/socket.service.ts (koneksi, auth, event, ACK,
 * handleIncomingSignal), jalur Tokocrypto dry-run, pelindung eksekusi Binance, logger.
 * Yang palsu: server sinyal (mock-signal-server.ts) dan database (Prisma diganti memori), supaya
 * tidak ada file, kunci, atau bursa yang tersentuh. Tidak ada koneksi keluar dari mesin ini.
 *
 * Jalankan dari folder server/ klien:  npx tsx simulation/run-signal-capture.ts
 */
import { bootClient, say, sleep, TOKEN } from "./sim-common";

async function main() {
  const { server, state, connectToNestJS, disconnectSocket, isSocketConnected } = await bootClient();
  const sig = (over: Record<string, unknown>) => ({
    id: "sig-1", symbol: "BTCUSDT", side: "LONG", entryPrice: 65000,
    tp1: 67000, tp2: 69000, tp3: 72000, sl: 63000, strategy: "demo", score: 91, strength: "HIGH", ...over,
  });
  const step = async (title: string, payload: unknown, wait = 500) => {
    say(`\n=== ${title} ===`);
    say(`  server mengirim new_signal: ${JSON.stringify(payload)}`);
    const before = server.acks.length;
    const delivered = server.emit(payload);
    await sleep(wait);
    say(`  diterima oleh ${delivered} klien; baris bertanda waktu di atas adalah log klien asli`);
    for (const a of server.acks.slice(before)) say(`  ACK ke server: ${JSON.stringify(a)}`);
  };

  say("=== 1. Tanpa token / token salah ===");
  await connectToNestJS("token-salah");
  await sleep(700);
  say(`  tersambung: ${isSocketConnected()}; handshake ditolak server: ${server.rejected}x`);
  disconnectSocket();

  say("\n=== 2. Token benar ===");
  await connectToNestJS(TOKEN);
  await sleep(700);
  say(`  tersambung: ${isSocketConnected()}`);

  await step("3. Sinyal LONG sah", sig({}));
  await step("4. Sinyal SHORT (Tokocrypto spot hanya bisa beli)", sig({ id: "sig-2", side: "SHORT", symbol: "ETHUSDT" }));
  await step("5. Koin di daftar hitam", sig({ id: "sig-3", symbol: "SCAMUSDT" }));
  await step("6. Payload cacat (tanpa simbol dan sisi)", { id: "sig-4", side: null });
  await step("7. Sinyal LONG sah kedua", sig({ id: "sig-5", symbol: "SOLUSDT", entryPrice: 150, tp1: 160, tp2: 170, tp3: 180, sl: 140 }));
  await step("8. Sinyal yang SAMA dengan no. 3 dikirim ulang (id sama, misalnya replay setelah reconnect)", sig({}));
  await step("9. Sinyal LONG berikutnya melewati batas posisi (3)", sig({ id: "sig-6", symbol: "ADAUSDT", entryPrice: 0.5, tp1: 0.55, tp2: 0.6, tp3: 0.65, sl: 0.46 }));

  say("\n=== 10. Jaringan putus (transport ditutup tanpa pesan): apakah klien tersambung lagi? ===");
  server.dropTransport();
  await sleep(300);
  say(`  setelah diputus, tersambung: ${isSocketConnected()}`);
  await sleep(4500); // reconnectionDelay klien 3 detik
  say(`  setelah menunggu 4,5 detik, tersambung: ${isSocketConnected()} (klien di server: ${server.connectedCount()})`);

  say("\n=== 11. Server SENGAJA memutus klien (disconnect dari sisi server): apakah klien tersambung lagi? ===");
  server.dropClients();
  await sleep(300);
  say(`  setelah diputus, tersambung: ${isSocketConnected()}`);
  await sleep(4500);
  say(`  setelah menunggu 4,5 detik, tersambung: ${isSocketConnected()} (klien di server: ${server.connectedCount()})`);
  await step("12. Sinyal setelah itu", sig({ id: "sig-7", symbol: "XRPUSDT", entryPrice: 0.6, tp1: 0.66, tp2: 0.7, tp3: 0.75, sl: 0.55 }));

  say("\n=== Ringkasan ===");
  say(`  posisi spot yang tercatat (database palsu): ${state.spot.map((s) => s.symbol).join(", ") || "-"}`);
  say(`  jumlah ACK diterima server: ${server.acks.length} (RECEIVED: ${server.acks.filter((a) => a.stage === "RECEIVED").length})`);
  disconnectSocket();
  await server.close();
  process.exit(0);
}
main().catch((e) => {
  console.error(e);
  process.exit(1);
});
