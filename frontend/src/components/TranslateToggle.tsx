import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { useI18n } from "@/i18n/context";
import { Button, Caveat, ErrorNote } from "@/components/primitives";

type Fields = Record<string, unknown>;

/**
 * Show a stored analysis in the other language.
 *
 * A *rendering*, not a second analysis, and the interface says so. Generating
 * the analysis twice could produce two different stances for one asset with
 * equal authority, and a reader seeing "beli" beside "hold" would have no way
 * to resolve it. So the original is always one click away, the translation is
 * labelled as machine-produced, and the labels, prices, and confidence are
 * never translated - they come from the stored analysis either way.
 */
export function TranslateToggle({
  fields,
  isPersonal = false,
  children,
}: {
  fields: Fields;
  isPersonal?: boolean;
  children: (rendered: Fields, translated: boolean) => React.ReactNode;
}) {
  const { t, locale } = useI18n();
  const [showing, setShowing] = useState(false);

  const translation = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/translate", {
        body: {
          fields: fields as never,
          // The opposite of what the interface is currently in: the button
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
  const rendered = showing ? { ...fields, ...translated } : fields;

  return (
    <div>
      <div className="mb-3 flex items-center gap-3">
        {showing ? (
          <Button variant="ghost" size="sm" onClick={() => setShowing(false)}>
            {t("translate.showOriginal")}
          </Button>
        ) : (
          <Button
            variant="ghost"
            size="sm"
            busy={translation.isPending}
            onClick={() =>
              translation.data ? setShowing(true) : translation.mutate()
            }
          >
            {translation.isPending ? t("translate.working") : t("translate.show")}
          </Button>
        )}
      </div>

      {translation.isError && (
        <div className="mb-3">
          <ErrorNote message={(translation.error as Error).message} />
        </div>
      )}

      {children(rendered, showing)}

      {showing && <Caveat>{t("translate.machineNote")}</Caveat>}
    </div>
  );
}
