import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { useI18n } from "@/i18n/context";

type Fields = Record<string, unknown>;

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
 * In its own module because a file exporting both a hook and a component
 * cannot be hot-reloaded: Fast Refresh replaces it, the context identity
 * changes underneath every consumer, and the app white-screens. That was
 * learned the expensive way once already.
 */
export function useTranslation(fields: Fields, isPersonal = false) {
  const { t, locale } = useI18n();
  const [showing, setShowing] = useState(false);

  const translation = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/translate", {
        body: {
          fields: fields as never,
          // The opposite of what the interface is currently in: the switch
          // offers the language the reader is *not* reading.
          language: locale === "id" ? "en" : "id",
          is_personal: isPersonal,
        },
      });
      if (error) throw new Error(errorMessage(error, t("translate.failed")));
      return data;
    },
    onSuccess: () => setShowing(true),
  });

  const translated = (translation.data?.fields ?? {}) as Fields;

  return {
    /** The fields to render: the original, or the original with prose replaced. */
    rendered: showing ? { ...fields, ...translated } : fields,
    showing,
    isPending: translation.isPending,
    error: translation.isError ? (translation.error as Error).message : null,
    showOriginal: () => setShowing(false),
    showTranslation: () => (translation.data ? setShowing(true) : translation.mutate()),
  };
}
