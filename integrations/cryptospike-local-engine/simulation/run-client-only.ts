/**
 * Klien cryptospike ASLI (database palsu di memori, Tokocrypto dry-run, Binance tanpa kunci)
 * tersambung ke server sinyal di SERVER_URL milik pihak lain, misalnya server AIDSS.
 * Variabel: SIM_URL (wajib), SIM_TOKEN (wajib), SIM_SECONDS (lama menunggu, bawaan 25).
 * Jalankan dari folder server/ klien:  SIM_URL=http://127.0.0.1:3099 SIM_TOKEN=... npx tsx simulation/run-client-only.ts
 */
import { bootClient, say, sleep, TOKEN } from "./sim-common";

async function main() {
  const url = process.env.SIM_URL;
  if (!url || !process.env.SIM_TOKEN) throw new Error("SIM_URL and SIM_TOKEN are required");
  const { state, connectToNestJS, disconnectSocket, isSocketConnected } = await bootClient({ maxOpenPositions: 5 }, url);
  await connectToNestJS(TOKEN);
  const seconds = Number(process.env.SIM_SECONDS ?? 25);
  for (let i = 0; i < seconds * 4; i++) {
    await sleep(250);
    if (state.spot.length > 0 && i > 8) break;
  }
  say(`\nconnected: ${isSocketConnected()}`);
  say(`dry-run spot positions recorded by the client: ${state.spot.map((s) => `${s.symbol} qty ${s.quantity} tp1 ${s.tp1Price} sl ${s.slPrice}`).join("; ") || "-"}`);
  disconnectSocket();
  process.exit(0);
}
main().catch((e) => {
  console.error(e);
  process.exit(1);
});
