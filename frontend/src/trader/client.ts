import createClient from "openapi-fetch";
import type { paths } from "@/api/trader-schema";
import { storedToken } from "@/api/client";

/**
 * The Trader's own API, a separate service from the analysis platform's.
 *
 * Same bearer token (the Trader asks the analysis API who it belongs to), but a
 * different client on purpose, for two reasons:
 *
 * - A 401 here must NOT sign the user out of the whole platform. The Trader
 *   answers 401 when the analysis API is unreachable, and ending a research
 *   session because the trading service had a bad minute would be the wrong
 *   blast radius.
 * - Errors have the Trader's own shape (`{error: {class, code, message,
 *   correlation_id}}`), and the screen text for "Unavailable" has to say which
 *   class it was, because "no data", "no answer" and "old data" are different
 *   facts in a trading UI (docs/04-UX-UI/03).
 *
 * Request paths and bodies are typed from the generated `trader-schema.d.ts`
 * (`python -m aidss_trader.api.openapi`, then `openapi-typescript`). Response
 * bodies are not modelled in the API yet, so `types.ts` declares them by hand
 * and this file is the only place that casts.
 */

export const traderApi = createClient<paths>({ baseUrl: "" });

traderApi.use({
  onRequest({ request }) {
    const token = storedToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
});

export type ErrorClass =
  | "AUTH"
  | "FORBIDDEN"
  | "VALIDATION"
  | "NOT_FOUND"
  | "CONFLICT"
  | "UNAVAILABLE"
  | "NETWORK"
  | "UNKNOWN";

export class TraderError extends Error {
  cls: ErrorClass;
  code: string | null;
  correlationId: string | null;
  status: number | null;

  constructor(
    message: string,
    cls: ErrorClass,
    code: string | null,
    correlationId: string | null,
    status: number | null,
  ) {
    super(message);
    this.cls = cls;
    this.code = code;
    this.correlationId = correlationId;
    this.status = status;
  }
}

export interface Meta {
  source: string;
  /** LIVE, PAPER or BACKTEST. Shown on the figure, never only in a heading. */
  origin: "LIVE" | "PAPER" | "BACKTEST";
  as_of: string;
  stale: boolean;
}

export interface Envelope<T> {
  data: T;
  meta: Meta;
}

interface Result {
  data?: unknown;
  error?: unknown;
  response: Response;
}

/** Turn any outcome into an Envelope or a TraderError. Never returns a blank or a zero. */
export async function unwrap<T>(call: Promise<Result>): Promise<Envelope<T>> {
  let result: Result;
  try {
    result = await call;
  } catch {
    // fetch itself failed: no route, DNS, connection refused. Say so plainly.
    throw new TraderError("Could not reach the Trader service.", "NETWORK", null, null, null);
  }
  const { data, error, response } = result;
  if (response.ok && data && typeof data === "object" && "data" in data) {
    return data as Envelope<T>;
  }
  const body = (error ?? {}) as {
    error?: { class?: string; code?: string; message?: string; correlation_id?: string };
    detail?: unknown;
  };
  const e = body.error;
  const status = response.status;
  const cls = ((): ErrorClass => {
    if (e?.class && ["AUTH", "FORBIDDEN", "VALIDATION", "NOT_FOUND", "CONFLICT"].includes(e.class))
      return e.class as ErrorClass;
    if (status >= 500 || status === 0) return "UNAVAILABLE";
    if (status === 401) return "AUTH";
    if (status === 403) return "FORBIDDEN";
    if (status === 422) return "VALIDATION";
    return "UNKNOWN";
  })();
  throw new TraderError(
    e?.message ?? `The Trader answered ${status}.`,
    cls,
    e?.code ?? null,
    e?.correlation_id ?? null,
    status,
  );
}

/** One per attempt, so a double click or a retry cannot repeat an approval or a kill. */
export function idempotencyKey(): string {
  return crypto.randomUUID();
}
