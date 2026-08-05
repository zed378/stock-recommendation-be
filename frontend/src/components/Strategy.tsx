import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { useI18n, type MessageKey } from "@/i18n/context";
import { Card, Caveat, Empty, ErrorNote, Loading } from "@/components/primitives";
import type { components } from "@/api/schema";

type Guidance = components["schemas"]["GuidanceResponse"];

/** One language's version of the two readings. */
type Translated = {
  not_holding: Guidance;
  holding: Guidance;
  disclaimer: string;
};

/**
 * One stance, read from both sides of a position.
 *
 * Both are rendered side by side regardless of what the reader actually holds.
 * That is the point of the screen: a `hold` on something you own and a `hold`
 * on something you do not are the same word describing two different
 * situations, and an asset worth keeping but not worth buying today is a real
 * and common case that only shows up when both columns are visible.
 */
export function Strategy({ ticker }: { ticker: string }) {
  const { t, n, locale } = useI18n();
  // Starts on the interface language and then stays where the reader puts it.
  // Independent of the header switch on purpose: someone reading the app in
  // English may still want this panel in Indonesian, and the two choices are
  // about different things.
  const [language, setLanguage] = useState<string>(locale);

  const query = useQuery({
    queryKey: ["strategy", ticker],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/assets/{ticker}/strategy", {
        params: { path: { ticker } },
      });
      // No stored recommendation is a normal state, not a failure to report.
      if (response.status === 404) return null;
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data ?? null;
    },
  });

  if (query.isLoading) return <Loading />;
  if (query.isError)
    return <ErrorNote message={(query.error as Error).message} onRetry={() => query.refetch()} />;
  if (!query.data)
    return (
      <Card>
        <Empty message={t("strategy.empty")} hint={t("strategy.emptyHint")} />
      </Card>
    );

  const data = query.data;

  // Every language the server built this view in. The response carries the
  // English one at the top level and the rest under `translations`, so the
  // switch never needs a request - and this text is product copy with a price
  // interpolated into it, so no model is involved either.
  const other = (data.translations ?? {}) as Record<string, Translated>;
  const available = ["en", ...Object.keys(other)];
  const shown = available.includes(language) ? language : "en";
  const view = shown === "en" ? data : other[shown];

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
          <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2">
            <div>
              <p className="text-xs text-faint">{t("rec.title")}</p>
              <p className="mt-0.5 text-sm font-medium text-ink">
                {t(`rec.label.${data.label}` as MessageKey)}
              </p>
            </div>
            <div>
              <p className="text-xs text-faint">{t("rec.confidence")}</p>
              <p className="mt-0.5 font-mono text-sm tnum text-ink">{n(data.confidence, 1)}</p>
            </div>
          </div>

          {/* Standalone: it changes what these cards say and nothing else.
              Both languages are written by hand, so neither is "the original"
              and the control offers them side by side rather than as an
              original and a translation. */}
          {available.length > 1 && (
            <div
              role="group"
              aria-label={t("strategy.language")}
              className="flex overflow-hidden rounded-md border border-line"
            >
              {available.map((option) => (
                <button
                  key={option}
                  onClick={() => setLanguage(option)}
                  aria-pressed={shown === option}
                  className={`px-2.5 py-1 text-xs uppercase transition-colors ${
                    shown === option ? "bg-hover text-ink" : "text-faint hover:text-muted"
                  }`}
                >
                  {option}
                </button>
              ))}
            </div>
          )}
        </div>
        <Caveat>{t("strategy.bothNote")}</Caveat>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <GuidancePanel title={t("strategy.notHolding")} guidance={view.not_holding} />
        <GuidancePanel title={t("strategy.holding")} guidance={view.holding} />
      </div>

      <p className="text-xs leading-relaxed text-faint">{view.disclaimer}</p>
    </div>
  );
}

function GuidancePanel({ title, guidance }: { title: string; guidance: Guidance }) {
  const { t } = useI18n();
  const stanceKey = `stance.${guidance.stance}` as MessageKey;

  // Colour by direction of travel, not by "good" and "bad". `avoid` and
  // `exit_candidate` are not failures - they are conclusions.
  const tone =
    guidance.stance === "entry_candidate" || guidance.stance === "accumulate_candidate"
      ? "border-buy/40 bg-buy/10 text-buy"
      : guidance.stance === "exit_candidate" || guidance.stance === "avoid"
        ? "border-sell/40 bg-sell/10 text-sell"
        : guidance.stance === "trim_candidate" || guidance.stance === "wait_for_level"
          ? "border-watch/40 bg-watch/10 text-watch"
          : "border-hold/40 bg-hold/10 text-hold";

  return (
    <Card title={title} className="h-full">
      <p className={`inline-block rounded-md border px-2.5 py-1 text-sm font-medium ${tone}`}>
        {t(stanceKey)}
      </p>

      <p className="mt-3 text-sm leading-relaxed text-ink/90">{guidance.rationale}</p>

      {guidance.conditions.length > 0 && (
        <div className="mt-4">
          <p className="mb-1.5 text-xs text-faint">{t("strategy.conditions")}</p>
          <ul className="space-y-1.5">
            {guidance.conditions.map((line, index) => (
              <li
                key={index}
                className="relative pl-4 text-sm leading-relaxed text-ink/85 before:absolute before:left-0 before:top-2 before:size-1.5 before:rounded-full before:bg-muted/60"
              >
                {line}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Never empty by construction: a stance with no stated invalidation is
          one that can never be shown to have been mistaken, and those are the
          ones people hold on to longest. */}
      <div className="mt-4 border-t border-line pt-3">
        <p className="mb-1.5 text-xs text-faint">{t("strategy.invalidatedIf")}</p>
        <ul className="space-y-1.5">
          {guidance.invalidated_if.map((line, index) => (
            <li
              key={index}
              className="relative pl-4 text-sm leading-relaxed text-fall/80 before:absolute before:left-0 before:top-2 before:size-1.5 before:rounded-full before:bg-fall/50"
            >
              {line}
            </li>
          ))}
        </ul>
      </div>

      {Object.keys(guidance.reference_levels).length > 0 && (
        <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 border-t border-line pt-3">
          {Object.entries(guidance.reference_levels).map(([key, value]) => (
            <div key={key} className="flex items-baseline justify-between gap-2">
              <dt className="text-xs text-faint">{key.replace(/_/g, " ")}</dt>
              <dd className="font-mono text-xs tnum text-ink/90">{value}</dd>
            </div>
          ))}
        </dl>
      )}
    </Card>
  );
}
