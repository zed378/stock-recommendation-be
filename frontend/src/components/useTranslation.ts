import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { useI18n } from "@/i18n/context";

type Fields = Record<string, unknown>;

/** The two languages this platform writes prose in. */
type Lang = "id" | "en";

const isLang = (value: unknown): value is Lang => value === "id" || value === "en";

/**
 * Show a stored analysis in the other language.
 *
 * A *rendering*, not a second analysis. Generating the analysis twice could
 * produce two different stances for one asset with equal authority, and a
 * reader seeing "beli" beside "hold" would have no way to resolve it. So the
 * original is always one click away, the translation is labelled as
 * machine-produced, and the labels, prices, and confidence are never
 * translated - they come from the stored analysis either way.
 *
 * **The source language comes from the content, not from the interface.** The
 * output language is a server setting: on a default deployment the prose is
 * Indonesian whatever the reader has the interface set to. An earlier version
 * inferred it from the locale, so a reader in English saw Indonesian prose
 * labelled EN and clicking ID asked for a translation into the language it was
 * already written in - which no stored rendering could satisfy, so it fired a
 * request every time and the switch spun for a translation that existed.
 *
 * In its own module because a file exporting both a hook and a component
 * cannot be hot-reloaded: Fast Refresh replaces it, the context identity
 * changes underneath every consumer, and the app white-screens. That was
 * learned the expensive way once already.
 */
export function useTranslation(fields: Fields, isPersonal = false) {
  const { t, locale } = useI18n();
  const [showing, setShowing] = useState(false);

  // What the prose is actually in. `id` is the backend's default output
  // language and the fallback for a payload written before this field existed.
  const source: Lang = isLang(fields.language) ? fields.language : "id";

  const stored = fields.translations as
    | Record<string, { fields?: Fields } | undefined>
    | undefined;

  // Which language to offer. The reader's own locale first, when it differs
  // from what they are looking at - that is the one they asked for. Failing
  // that, whatever rendering was stored. Failing that, simply the other of the
  // two, so the switch still works with no translation on hand.
  const target: Lang =
    locale !== source && isLang(locale)
      ? locale
      : (Object.keys(stored ?? {}).find(
          (key): key is Lang => isLang(key) && key !== source,
        ) ?? (source === "id" ? "en" : "id"));

  const ready = stored?.[target]?.fields;

  const translation = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/translate", {
        body: {
          fields: fields as never,
          language: target,
          is_personal: isPersonal,
        },
      });
      if (error) throw new Error(errorMessage(error, t("translate.failed")));
      return data;
    },
    onSuccess: () => setShowing(true),
  });

  // Stored first, fetched only if there is none. A stored rendering is the
  // same text the endpoint would return, so preferring it costs nothing and
  // removes the wait entirely.
  const translated = ready ?? ((translation.data?.fields ?? {}) as Fields);

  return {
    /** The fields to render: the original, or the original with prose replaced. */
    rendered: showing ? { ...fields, ...translated } : fields,
    showing,
    /** The language the prose is written in, for labelling the switch. */
    source,
    /** The language the switch offers. */
    target,
    /** True when the switch is instant, because the analysis already stored it. */
    isReady: Boolean(ready),
    isPending: translation.isPending,
    error: translation.isError ? (translation.error as Error).message : null,
    showOriginal: () => setShowing(false),
    showTranslation: () => {
      if (ready || translation.data) setShowing(true);
      else translation.mutate();
    },
  };
}
