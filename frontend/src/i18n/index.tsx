import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { locales, type Locale } from "./messages";
import { I18nContext, type I18n } from "./context";

/**
 * Language, number formatting, and date formatting - one decision, not three.
 *
 * A locale switch that changed the words and left `1.234,56` rendered as
 * `1,234.56` would be worse than not switching at all: in Indonesian the dot is
 * a thousands separator, so the same string reads as a different number.
 *
 * This module exports only the provider. The hook lives in `./context` so that
 * editing either one hot-reloads instead of throwing.
 */

const STORAGE_KEY = "aidss.locale";

function initialLocale(): Locale {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved === "id" || saved === "en") return saved;
  // Indonesian unless the browser clearly says otherwise: this is an IDX
  // product, so it is the majority case rather than the fallback.
  return navigator.language.toLowerCase().startsWith("en") ? "en" : "id";
}

function toNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>(initialLocale);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, locale);
    document.documentElement.lang = locale;
  }, [locale]);

  const value = useMemo<I18n>(() => {
    const tag = locale === "id" ? "id-ID" : "en-US";
    const messages = locales[locale];

    const n = (raw: number | string | null | undefined, digits = 2) => {
      const parsed = toNumber(raw);
      if (parsed === null) return "—";
      return parsed.toLocaleString(tag, {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });
    };

    return {
      locale,
      setLocale,

      t: (key, values) => {
        const template = messages[key] ?? key;
        if (!values) return template;
        return template.replace(/\{(\w+)\}/g, (match, name: string) =>
          name in values ? String(values[name]) : match,
        );
      },

      n,

      money: (raw) => {
        const parsed = toNumber(raw);
        if (parsed === null) return "—";
        const abs = Math.abs(parsed);
        // Abbreviated above a million. Indonesian issuers report in trillions
        // of rupiah, and 1.538.501.810.000.000 is a number nobody reads - they
        // count the digits, and miscount.
        const units: [number, string, string][] = [
          [1e12, "T", "T"],
          [1e9, "M", "B"],
          [1e6, "jt", "M"],
        ];
        for (const [scale, idSuffix, enSuffix] of units) {
          if (abs >= scale) {
            const suffix = locale === "id" ? idSuffix : enSuffix;
            return `Rp ${n(parsed / scale, 2)} ${suffix}`;
          }
        }
        return `Rp ${n(parsed, abs < 100 ? 2 : 0)}`;
      },

      pct: (raw, digits = 2) => {
        const parsed = toNumber(raw);
        if (parsed === null) return "—";
        return `${n(parsed * 100, digits)}%`;
      },

      date: (raw) => {
        if (!raw) return "—";
        const parsed = raw instanceof Date ? raw : new Date(raw);
        if (Number.isNaN(parsed.getTime())) return "—";
        return parsed.toLocaleDateString(tag, {
          day: "2-digit",
          month: "short",
          year: "numeric",
        });
      },

      dateTime: (raw) => {
        if (!raw) return "—";
        const parsed = raw instanceof Date ? raw : new Date(raw);
        if (Number.isNaN(parsed.getTime())) return "—";
        return parsed.toLocaleString(tag, {
          day: "2-digit",
          month: "short",
          year: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        });
      },
    };
  }, [locale]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}
