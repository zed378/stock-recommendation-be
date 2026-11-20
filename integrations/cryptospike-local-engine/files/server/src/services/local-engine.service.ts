import { addAppLog } from "../lib/logger";
import { loadEngineConfig } from "../engine/config";
import { createLocalEngine } from "../engine/local-engine";
import { handleIncomingSignal } from "./socket.service";

/**
 * Menyalakan mesin strategi lokal bila LOCAL_ENGINE_ENABLED=true. Mati secara bawaan dan tidak
 * mengubah apa pun pada alur sinyal dari server luar. Di mode EXECUTE sinyal masuk ke
 * `handleIncomingSignal`, jadi semua pengaman klien tetap berlaku: autoExecute per bursa,
 * dry-run, filter koin, batas posisi, dedupe id sinyal, dan SL wajib.
 */
export function startLocalEngine(): void {
  const loaded = loadEngineConfig(process.env);
  if (loaded.status === "disabled") return;
  if (loaded.status === "invalid") {
    addAppLog("ERROR", "LocalEngine", `Not started: ${loaded.problems.join("; ")}`);
    return;
  }
  for (const note of loaded.notes) addAppLog("WARN", "LocalEngine", note);
  const engine = createLocalEngine({
    config: loaded.config,
    fetchFn: (url, init) => fetch(url, init) as ReturnType<Parameters<typeof createLocalEngine>[0]["fetchFn"]>,
    handleSignal: (signal) => handleIncomingSignal(signal),
    log: (level, message) => addAppLog(level, "LocalEngine", message),
    now: () => Date.now(),
  });
  addAppLog(
    "INFO",
    "LocalEngine",
    `Started in ${loaded.config.mode} mode for ${loaded.config.symbols.join(", ")}`,
  );
  engine.start();
}
