import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { useI18n, type MessageKey } from "@/i18n/context";
import { Card, Caveat, Empty, ErrorNote, Loading } from "@/components/primitives";

const WINDOWS = [7, 30, 90] as const;

/**
 * Dated events ahead, and nothing about what they mean.
 *
 * This is the only screen in the product that looks forward, which makes it
 * the one most likely to be read as a prediction. Every design choice here
 * pushes against that: no price on the row, no "expected impact" column, and
 * the source of every date visible so a reader can tell an exchange filing
 * from something inferred out of a headline.
 */
export function Agenda() {
  const { t, date: formatDate } = useI18n();
  const [days, setDays] = useState<number>(30);
  const [watchlistOnly, setWatchlistOnly] = useState(false);

  const query = useQuery({
    queryKey: ["agenda", days, watchlistOnly],
    queryFn: async () => {
      const { data, error } = await api.GET("/agenda", {
        params: { query: { days, watchlist_only: watchlistOnly, limit: 100 } },
      });
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data;
    },
  });

  const items = query.data?.items ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-lg font-semibold text-ink">{t("agenda.title")}</h1>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex overflow-hidden rounded-md border border-line">
            {WINDOWS.map((option) => (
              <button
                key={option}
                onClick={() => setDays(option)}
                className={`px-3 py-1 font-mono text-xs transition-colors ${
                  days === option ? "bg-hover text-ink" : "text-faint hover:text-muted"
                }`}
              >
                {option}d
              </button>
            ))}
          </div>
          <label className="flex items-center gap-1.5 text-xs text-muted">
            <input
              type="checkbox"
              checked={watchlistOnly}
              onChange={(event) => setWatchlistOnly(event.target.checked)}
              className="accent-rise"
            />
            {t("agenda.watchlistOnly")}
          </label>
        </div>
      </div>

      {/* Above the list, like the screener's. A calendar of company events
          invites the reading that the platform expects each one to move the
          price, and it does not. */}
      <div className="rounded-lg border border-watch/25 bg-watch/5 px-4 py-3">
        <p className="text-sm font-medium text-watch">{t("agenda.notAForecast")}</p>
        <p className="mt-1 text-xs leading-relaxed text-muted">
          {query.data?.caveat ?? t("agenda.caveatFallback")}
        </p>
      </div>

      {query.isLoading ? (
        <Loading />
      ) : query.isError ? (
        <ErrorNote message={(query.error as Error).message} onRetry={() => query.refetch()} />
      ) : items.length === 0 ? (
        <Card>
          <Empty message={t("agenda.empty")} hint={t("agenda.emptyHint")} />
        </Card>
      ) : (
        <Card>
          <ul className="divide-y divide-line">
            {items.map((item) => (
              <li
                key={`${item.ticker}-${item.kind}-${item.scheduled_for}`}
                className="flex flex-wrap items-baseline gap-x-4 gap-y-1 py-3 first:pt-0 last:pb-0"
              >
                <span className="w-24 shrink-0 font-mono text-xs tnum text-muted">
                  {formatDate(item.scheduled_for)}
                </span>
                <Link
                  to={`/assets/${item.ticker}`}
                  className="font-mono text-sm font-semibold text-ink hover:text-rise"
                >
                  {item.ticker}
                </Link>
                <span className="rounded border border-line px-1.5 py-0.5 text-xs text-faint">
                  {t(`agenda.kind.${item.kind}` as MessageKey)}
                </span>
                <span className="min-w-0 flex-1 truncate text-sm text-ink/85">
                  {item.title}
                </span>
                {/* Where the date came from, on every row. A date lifted out of
                    a headline and one filed with the exchange are not the same
                    claim, and the reader is the only one who can decide how
                    much to lean on either. */}
                {item.source_url ? (
                  <a
                    href={item.source_url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="text-xs text-faint underline hover:text-muted"
                  >
                    {t(`agenda.source.${item.source}` as MessageKey)}
                  </a>
                ) : (
                  <span className="text-xs text-faint">
                    {t(`agenda.source.${item.source}` as MessageKey)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Caveat>{t("agenda.footer")}</Caveat>
    </div>
  );
}
