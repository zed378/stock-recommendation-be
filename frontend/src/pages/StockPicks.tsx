import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { useI18n } from "@/i18n/context";
import { Card, Caveat, Empty, ErrorNote, Loading } from "@/components/primitives";

const HORIZONS = ["1d", "7d", "14d", "30d"] as const;
type Horizon = (typeof HORIZONS)[number];

interface Pick {
  ticker: string;
  name: string | null;
  sector: string | null;
  close: string | null;
  score: number;
  out_of: number;
  met: { key: string; describes: string; weight: number }[];
  unmet: string[];
  limit_proximity: {
    consumed: number;
    ceiling: string;
    limit_percent: number;
    reference_price: string;
  } | null;
}

/**
 * A screen, presented as one.
 *
 * A ranked list of tickers is read as a forecast unless the screen says
 * otherwise, so the caveat is not tucked into a footer: it sits above the
 * results, and every row carries the conditions it actually met rather than
 * only a score. "Score 3.1 of 4.1, because these four things are true" can be
 * argued with; "score 0.72" cannot.
 */
export function StockPicks() {
  const { t, n, money } = useI18n();
  const [horizon, setHorizon] = useState<Horizon>("7d");
  const [watchlistOnly, setWatchlistOnly] = useState(false);
  const [nearLimitOnly, setNearLimitOnly] = useState(false);

  const query = useQuery({
    queryKey: ["stock-picks", horizon, watchlistOnly, nearLimitOnly],
    queryFn: async () => {
      const { data, error } = await api.GET("/stock-picks", {
        params: {
          query: {
            horizon,
            watchlist_only: watchlistOnly,
            near_limit_only: nearLimitOnly,
            limit: 30,
          },
        },
      });
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data;
    },
  });

  const picks = (query.data?.picks ?? []) as unknown as Pick[];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-lg font-semibold text-ink">{t("picks.title")}</h1>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex overflow-hidden rounded-md border border-line">
            {HORIZONS.map((option) => (
              <button
                key={option}
                onClick={() => setHorizon(option)}
                className={`px-3 py-1 font-mono text-xs transition-colors ${
                  horizon === option ? "bg-hover text-ink" : "text-faint hover:text-muted"
                }`}
              >
                {option}
              </button>
            ))}
          </div>

          <label className="flex items-center gap-1.5 text-xs text-muted">
            <input
              type="checkbox"
              checked={watchlistOnly}
              onChange={(e) => setWatchlistOnly(e.target.checked)}
              className="accent-rise"
            />
            {t("picks.watchlistOnly")}
          </label>

          <label className="flex items-center gap-1.5 text-xs text-muted">
            <input
              type="checkbox"
              checked={nearLimitOnly}
              onChange={(e) => setNearLimitOnly(e.target.checked)}
              className="accent-watch"
            />
            {t("picks.nearLimitOnly")}
          </label>
        </div>
      </div>

      {/* Above the results, not below them. */}
      <div className="rounded-lg border border-watch/25 bg-watch/5 px-4 py-3">
        <p className="text-sm font-medium text-watch">{t("picks.notAForecast")}</p>
        <p className="mt-1 text-xs leading-relaxed text-muted">
          {query.data?.caveat ?? t("picks.horizonNote")}
        </p>
      </div>

      {query.isLoading ? (
        <Loading />
      ) : query.isError ? (
        <ErrorNote message={(query.error as Error).message} onRetry={() => query.refetch()} />
      ) : (
        <>
          <p className="text-xs text-faint">
            {t("picks.considered", { count: query.data?.considered ?? 0 })}
            {query.data?.insufficient_history?.length ? (
              <>
                {" · "}
                {t("picks.insufficient", {
                  count: query.data.insufficient_history.length,
                })}
              </>
            ) : null}
          </p>

          {picks.length === 0 ? (
            <Card>
              <Empty message={t("picks.empty")} hint={t("picks.emptyHint")} />
            </Card>
          ) : (
            <div className="space-y-3">
              {picks.map((pick) => (
                <Card key={pick.ticker}>
                  <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                    <Link
                      to={`/assets/${pick.ticker}`}
                      className="font-mono text-base font-semibold text-ink hover:text-rise"
                    >
                      {pick.ticker}
                    </Link>
                    {pick.name && (
                      <span className="min-w-0 truncate text-sm text-muted">{pick.name}</span>
                    )}
                    {pick.sector && (
                      <span className="rounded border border-line px-1.5 py-0.5 text-xs text-faint">
                        {pick.sector}
                      </span>
                    )}
                    <span className="ml-auto font-mono text-sm tnum text-ink">
                      {money(pick.close)}
                    </span>
                    {/* Reported with its ceiling, so the number is readable
                        rather than being on an unstated scale. */}
                    <span className="font-mono text-xs tnum text-muted">
                      {t("picks.score")} {n(pick.score, 1)}/{n(pick.out_of, 1)}
                    </span>
                  </div>

                  <div className="mt-3">
                    <p className="mb-1.5 text-xs text-faint">{t("picks.met")}</p>
                    <ul className="space-y-1">
                      {pick.met.map((item) => (
                        <li
                          key={item.key}
                          className="relative pl-4 text-sm leading-relaxed text-ink/85 before:absolute before:left-0 before:top-2 before:size-1.5 before:rounded-full before:bg-rise/60"
                        >
                          {item.describes}
                        </li>
                      ))}
                    </ul>
                  </div>

                  {pick.unmet.length > 0 && (
                    <p className="mt-2 text-xs text-faint">
                      {t("picks.unmet")}: {pick.unmet.join(", ").replace(/_/g, " ")}
                    </p>
                  )}

                  {pick.limit_proximity && (
                    <div className="mt-3 border-t border-line pt-3">
                      <div className="flex items-baseline justify-between gap-4">
                        <span className="text-xs text-faint">{t("picks.limitProximity")}</span>
                        <span className="font-mono text-xs tnum text-watch">
                          {n(pick.limit_proximity.consumed * 100, 0)}% ·{" "}
                          {t("picks.limitCeiling")} {money(pick.limit_proximity.ceiling)} (
                          {n(pick.limit_proximity.limit_percent, 0)}%)
                        </span>
                      </div>
                      <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-surface">
                        <div
                          className="h-full rounded-full bg-watch"
                          style={{
                            width: `${Math.min(100, pick.limit_proximity.consumed * 100)}%`,
                          }}
                        />
                      </div>
                    </div>
                  )}
                </Card>
              ))}
            </div>
          )}

          <Caveat>{t("picks.horizonNote")}</Caveat>
        </>
      )}
    </div>
  );
}
