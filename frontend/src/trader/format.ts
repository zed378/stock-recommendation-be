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

/**
 * Round a decimal string to `places` decimals, half away from zero, on integers: no float, so a
 * value never changes in the last digit the way `toFixed` can. Display only; what is sent to the
 * server stays the exact string.
 */
export function roundDecimal(value: string, places: number): string {
  const negative = value.startsWith("-");
  const [whole, frac = ""] = (negative ? value.slice(1) : value).split(".");
  if (frac.length <= places) return value;
  const kept = BigInt(whole + frac.slice(0, places));
  const next = frac.charCodeAt(places) - 48;
  const rounded = (next >= 5 ? kept + 1n : kept).toString().padStart(places + 1, "0");
  const intPart = rounded.slice(0, rounded.length - places);
  const fracPart = rounded.slice(rounded.length - places);
  const out = places > 0 ? `${intPart}.${fracPart}` : intPart;
  return negative && /[1-9]/.test(out) ? `-${out}` : out;
}

/** Drop trailing zeros of the fraction, and the point when nothing is left. */
export function trimZeros(value: string): string {
  return value.includes(".") ? value.replace(/\.?0+$/, "") : value;
}

const absGreaterOrEqual = (value: string, bound: number): boolean =>
  compareDecimals(value.replace(/^-/, ""), String(bound)) >= 0;

/** An amount of money for a table or a tile: whole rupiah from 1,000 up, two decimals below. */
export function displayAmount(value: string): string {
  return trimZeros(roundDecimal(value, absGreaterOrEqual(value, 1000) ? 0 : 2));
}

/** A price: more decimals the smaller it is, so a 0.000001 coin is not shown as 0. */
export function displayPrice(value: string): string {
  const places = absGreaterOrEqual(value, 1000) ? 2 : absGreaterOrEqual(value, 1) ? 4 : 6;
  return trimZeros(roundDecimal(value, places));
}

/** A quantity: up to eight decimals, which is as fine as the exchange's own steps. */
export function displayQuantity(value: string): string {
  return trimZeros(roundDecimal(value, 8));
}

/** A percentage with two decimals. */
export function displayPercent(value: string): string {
  return trimZeros(roundDecimal(value, 2));
}
