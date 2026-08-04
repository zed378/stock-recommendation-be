import { createContext, useContext } from "react";
import type { Locale, MessageKey } from "./messages";

/**
 * The context object and its hook, kept apart from the provider component.
 *
 * Not a style preference. A module that exports both a component and a hook
 * cannot be hot-reloaded: Fast Refresh replaces the module, `createContext`
 * runs again, and every consumer suddenly holds a different context object
 * from the one the provider is filling - so `useI18n` throws and the whole app
 * white-screens on any edit to this file. Splitting the two is what the
 * `only-export-components` rule is actually protecting against.
 */

export interface I18n {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  /** Translate. `{name}` placeholders are replaced from `values`. */
  t: (key: MessageKey, values?: Record<string, string | number>) => string;
  /** A number for reading, with the locale's separators. */
  n: (value: number | string | null | undefined, digits?: number) => string;
  /** Rupiah, abbreviated at scale - a balance sheet in full digits is unreadable. */
  money: (value: number | string | null | undefined) => string;
  /** A percentage from a *fraction*: 0.2066 renders as 20,66%. */
  pct: (fraction: number | string | null | undefined, digits?: number) => string;
  date: (value: string | Date | null | undefined) => string;
  dateTime: (value: string | Date | null | undefined) => string;
}

export const I18nContext = createContext<I18n | null>(null);

export function useI18n(): I18n {
  const context = useContext(I18nContext);
  if (!context) throw new Error("useI18n must be used inside an I18nProvider");
  return context;
}

export type { Locale, MessageKey };
