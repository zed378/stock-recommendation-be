import { useI18n } from "@/i18n/context";
import { Caveat, ErrorNote, Spinner } from "@/components/primitives";

/**
 * The controls that go with `useTranslation`, which lives in its own module.
 *
 * The switch belongs in the panel's header, beside the other actions, while the
 * content it governs is further down - so the hook and the control are separate
 * pieces rather than one wrapper. The first version rendered a quiet ghost
 * button floating above the card; it was there, and a reader looking for it
 * could not find it.
 */

/**
 * A segmented control, matching the language switch in the page header.
 *
 * The same shape the reader already uses to change the interface language, so
 * it needs no explaining: two languages, the current one lit. What it changes
 * is the *content*, which is why it sits in the panel rather than the header.
 */
export function LanguageSwitch({
  showing,
  isPending,
  onOriginal,
  onTranslate,
}: {
  showing: boolean;
  isPending: boolean;
  onOriginal: () => void;
  onTranslate: () => void;
}) {
  const { locale, t } = useI18n();
  const original = locale === "id" ? "ID" : "EN";
  const other = locale === "id" ? "EN" : "ID";

  return (
    <div
      role="group"
      aria-label={t("nav.language")}
      className="flex items-center overflow-hidden rounded-md border border-line"
    >
      <button
        onClick={onOriginal}
        aria-pressed={!showing}
        className={`px-2.5 py-1 text-xs uppercase transition-colors ${
          !showing ? "bg-hover text-ink" : "text-faint hover:text-muted"
        }`}
      >
        {original}
      </button>
      <button
        onClick={onTranslate}
        aria-pressed={showing}
        disabled={isPending}
        className={`flex items-center gap-1.5 px-2.5 py-1 text-xs uppercase transition-colors disabled:opacity-60 ${
          showing ? "bg-hover text-ink" : "text-faint hover:text-muted"
        }`}
      >
        {isPending && <Spinner />}
        {other}
      </button>
    </div>
  );
}

/** The note and error that accompany a translated panel. */
export function TranslationNotice({
  showing,
  error,
}: {
  showing: boolean;
  error: string | null;
}) {
  const { t } = useI18n();
  if (error) {
    return (
      <div className="mt-3">
        <ErrorNote message={error} />
      </div>
    );
  }
  // Shown only while a translation is on screen, so the reader is never
  // looking at machine-rendered prose without knowing it.
  return showing ? <Caveat>{t("translate.machineNote")}</Caveat> : null;
}
