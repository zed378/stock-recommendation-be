import createClient from "openapi-fetch";
import type { paths } from "./schema";

/**
 * The one place that talks to the backend.
 *
 * Typed from `schema.d.ts`, which is generated from the API's own OpenAPI
 * document rather than written by hand. That is the point: a field renamed in
 * FastAPI becomes a TypeScript compile error here instead of `undefined` on a
 * screen three months later. Regenerate with `npm run api:types`.
 */

const TOKEN_KEY = "aidss.token";
const TOKEN_EXPIRY_KEY = "aidss.token.expires";

export function storedToken(): string | null {
  const token = localStorage.getItem(TOKEN_KEY);
  if (!token) return null;

  // Checked before use rather than waiting for a 401. An expired token would
  // otherwise let the app render its shell, fire a dozen requests, and fail all
  // of them - which looks like an outage instead of a finished session.
  const expiresAt = localStorage.getItem(TOKEN_EXPIRY_KEY);
  if (expiresAt && Date.parse(expiresAt) <= Date.now()) {
    clearToken();
    window.dispatchEvent(new CustomEvent(SESSION_EXPIRED));
    return null;
  }
  return token;
}

export function storeToken(token: string, expiresAt: string): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(TOKEN_EXPIRY_KEY, expiresAt);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(TOKEN_EXPIRY_KEY);
}

/** Fired when the server rejects our token, so the app can return to login. */
export const SESSION_EXPIRED = "aidss:session-expired";

export const api = createClient<paths>({ baseUrl: "/api" });

api.use({
  onRequest({ request }) {
    const token = storedToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
  onResponse({ response }) {
    // A 401 from the server outranks whatever we believed about expiry: the
    // secret may have been rotated or the account disabled.
    if (response.status === 401 && storedToken()) {
      clearToken();
      window.dispatchEvent(new CustomEvent(SESSION_EXPIRED));
    }
    return response;
  },
});

/**
 * Turn an API error into something worth showing a person.
 *
 * FastAPI's `detail` is either a string or a list of validation objects, and
 * rendering the second as `[object Object]` is the usual outcome of not
 * checking. The fallback names the status rather than saying "something went
 * wrong", which tells the reader nothing they did not already know.
 */
/**
 * A response body that is not this API's JSON error shape.
 *
 * When something between the browser and the server answers instead - a proxy
 * timing out, a gateway with no upstream - the body is an HTML page, and
 * `openapi-fetch` hands it over as a plain string. Rendered as-is it filled the
 * analysis panel with a thousand characters of Cloudflare markup, which tells
 * the reader nothing and hides the one sentence that would have.
 */
function looksLikeMarkup(value: string): boolean {
  const head = value.trimStart().slice(0, 200).toLowerCase();
  return head.startsWith("<") || head.includes("<!doctype") || head.includes("<html");
}

export function errorMessage(error: unknown, fallback: string): string {
  if (typeof error === "string") {
    // Length matters as well as markup: a body this long is a document, and a
    // document is never the message.
    return looksLikeMarkup(error) || error.length > 400 ? fallback : error;
  }
  if (!error || typeof error !== "object") return fallback;

  const detail = (error as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;

  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === "string") return item;
        const message = (item as { msg?: string }).msg;
        const location = (item as { loc?: (string | number)[] }).loc;
        const field = location?.filter((p) => p !== "body").join(".");
        return field && message ? `${field}: ${message}` : message;
      })
      .filter(Boolean);
    if (parts.length) return parts.join("; ");
  }

  const message = (error as { message?: string }).message;
  return typeof message === "string" ? message : fallback;
}
