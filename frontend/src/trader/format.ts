/** Rendering helpers for exact decimal strings. Nothing here parses to a float for display. */

/**
 * Estimated order value, computed from the two strings as a decimal string.
 *
 * A float multiply would turn 0.01 x 1236777000 into 12367770.000000002. The
 * quantity can have up to eight decimals, so the product is done on integers.
 */
export function multiplyDecimals(a: string, b: string): string {
  const [ai, af = ""] = a.split(".");
  const [bi, bf = ""] = b.split(".");
  const scale = af.length + bf.length;
  const product = (BigInt(ai + af) * BigInt(bi + bf)).toString().padStart(scale + 1, "0");
  if (scale === 0) return product;
  const whole = product.slice(0, product.length - scale);
  const frac = product.slice(product.length - scale).replace(/0+$/, "");
  return frac ? `${whole}.${frac}` : whole;
}

/** Group the integer part with the locale separator, leave the decimals exactly as sent. */
export function groupDigits(value: string, locale: string): string {
  const [whole, frac] = value.split(".");
  const negative = whole.startsWith("-");
  const digits = negative ? whole.slice(1) : whole;
  const sep = locale === "id" ? "." : ",";
  const dec = locale === "id" ? "," : ".";
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, sep);
  return `${negative ? "-" : ""}${grouped}${frac ? dec + frac : ""}`;
}

export function ageSeconds(fromMs: number, nowMs: number): number {
  return Math.max(0, Math.round((nowMs - fromMs) / 1000));
}

/** Compare two non-negative decimal strings exactly, without a float. -1, 0, or 1. */
export function compareDecimals(a: string, b: string): number {
  const [ai, af = ""] = a.trim().split(".");
  const [bi, bf = ""] = b.trim().split(".");
  const scale = Math.max(af.length, bf.length);
  const x = BigInt(ai + af.padEnd(scale, "0"));
  const y = BigInt(bi + bf.padEnd(scale, "0"));
  return x < y ? -1 : x > y ? 1 : 0;
}

export const DECIMAL = /^\d+(\.\d+)?$/;
