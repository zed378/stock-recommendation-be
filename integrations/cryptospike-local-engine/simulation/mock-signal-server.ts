import { createServer, type Server as HttpServer } from "http";
import { Server } from "socket.io";

/**
 * Pengganti server sinyal luar untuk simulasi LOKAL (hanya 127.0.0.1, tanpa internet).
 * Meniru kontrak yang terbaca dari kode klien:
 *   - klien menyambung dengan `auth: { token }`; token salah ditolak saat handshake,
 *   - server mengirim event `new_signal` dengan payload sinyal,
 *   - klien membalas event `signal_ack` ({ signalId, stage: RECEIVED | RESULT, ... }),
 *   - klien mengirim `ping` tiap 20 detik.
 * Kontrak ini disimpulkan dari kode klien, bukan dari dokumen server aslinya.
 */
export interface Ack {
  signalId: string | null;
  stage: "RECEIVED" | "RESULT";
  environment?: string;
  status?: string;
  reason?: string;
}

export function startMockSignalServer(validToken: string): Promise<{
  url: string;
  acks: Ack[];
  rejected: number;
  emit(signal: unknown): number;
  /** Server memutus klien dengan sengaja (event disconnect: "io server disconnect"). */
  dropClients(): void;
  /** Memutus transport tanpa pesan, seperti jaringan putus atau server restart. */
  dropTransport(): void;
  connectedCount(): number;
  close(): Promise<void>;
}> {
  const http: HttpServer = createServer();
  const io = new Server(http, { cors: { origin: "*" } });
  const acks: Ack[] = [];
  const state = { rejected: 0 };
  io.use((socket, next) => {
    const token = (socket.handshake.auth as { token?: string } | undefined)?.token;
    if (token !== validToken) {
      state.rejected++;
      return next(new Error("invalid client token"));
    }
    next();
  });
  io.on("connection", (socket) => {
    socket.on("signal_ack", (ack: Ack) => acks.push(ack));
  });
  return new Promise((resolve) => {
    http.listen(0, "127.0.0.1", () => {
      const port = (http.address() as { port: number }).port;
      resolve({
        url: `http://127.0.0.1:${port}`,
        acks,
        get rejected() {
          return state.rejected;
        },
        emit: (signal) => {
          io.emit("new_signal", signal);
          return io.sockets.sockets.size;
        },
        dropClients: () => io.sockets.sockets.forEach((s) => s.disconnect(true)),
        dropTransport: () => {
          for (const c of Object.values((io.engine as any).clients ?? {})) (c as any).close();
        },
        connectedCount: () => io.sockets.sockets.size,
        close: () =>
          new Promise<void>((r) => {
            io.close(() => r());
          }),
      });
    });
  });
}
