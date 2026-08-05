import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { useI18n, type MessageKey } from "@/i18n/context";
import {
  Button,
  Card,
  Caveat,
  Empty,
  ErrorNote,
  Loading,
} from "@/components/primitives";

/**
 * Near-real-time observation, presented as near-real-time.
 *
 * The delay is shown on every row rather than mentioned once in a footnote.
 * The free sources are roughly fifteen minutes behind, and an interface that
 * renders a delayed price the way a live one would invites decisions on numbers
 * that have already moved.
 */
export function Monitoring() {
  const { t, money, dateTime, n } = useI18n();
  const queryClient = useQueryClient();
  const [unreadOnly, setUnreadOnly] = useState(false);

  const quotes = useQuery({
    queryKey: ["monitoring-quotes"],
    queryFn: async () => {
      const { data, error } = await api.GET("/monitoring/quotes");
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data ?? [];
    },
    // Polls the *store*, not the provider: the worker does the fetching, and
    // the browser asking more often would not make the data newer.
    refetchInterval: 30_000,
  });

  const alerts = useQuery({
    queryKey: ["alerts", unreadOnly],
    queryFn: async () => {
      const { data, error } = await api.GET("/alerts", {
        params: { query: { unacknowledged_only: unreadOnly, limit: 100 } },
      });
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data ?? [];
    },
    refetchInterval: 30_000,
  });

  const poll = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/monitoring/poll");
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["monitoring-quotes"] });
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
    },
  });

  const acknowledge = useMutation({
    mutationFn: async (id: string) => {
      const { error } = await api.POST("/alerts/{alert_id}/acknowledge", {
        params: { path: { alert_id: id } },
      });
      if (error) throw new Error(errorMessage(error, t("common.error")));
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alerts"] }),
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-lg font-semibold text-ink">{t("monitoring.title")}</h1>
        <Button variant="ghost" busy={poll.isPending} onClick={() => poll.mutate()}>
          {poll.isPending ? t("monitoring.polling") : t("monitoring.pollNow")}
        </Button>
      </div>

      {poll.isError && <ErrorNote message={(poll.error as Error).message} />}

      <Card title={t("monitoring.quotes")}>
        {quotes.isLoading ? (
          <Loading />
        ) : quotes.isError ? (
          <ErrorNote
            message={(quotes.error as Error).message}
            onRetry={() => quotes.refetch()}
          />
        ) : !quotes.data?.length ? (
          <Empty message={t("monitoring.empty")} hint={t("monitoring.emptyHint")} />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-xs text-faint">
                    <th className="pb-2 pr-4 font-medium">{t("portfolio.ticker")}</th>
                    <th className="pb-2 pr-4 text-right font-medium">{t("asset.price")}</th>
                    <th className="pb-2 pr-4 text-right font-medium">{t("asset.change")}</th>
                    <th className="pb-2 pr-4 font-medium">{t("monitoring.observedAt")}</th>
                    <th className="pb-2 font-medium" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {quotes.data.map((quote) => {
                    const price = quote.price === null ? null : Number(quote.price);
                    const previous =
                      quote.previous_close === null ? null : Number(quote.previous_close);
                    const change =
                      price !== null && previous ? (price - previous) / previous : null;
                    return (
                      <tr key={quote.ticker}>
                        <td className="py-2.5 pr-4">
                          <Link
                            to={`/assets/${quote.ticker}`}
                            className="font-mono text-ink hover:text-rise"
                          >
                            {quote.ticker}
                          </Link>
                        </td>
                        <td className="py-2.5 pr-4 text-right font-mono tnum text-ink/90">
                          {price === null ? "—" : money(price)}
                        </td>
                        <td
                          className={`py-2.5 pr-4 text-right font-mono tnum ${
                            change === null
                              ? "text-faint"
                              : change >= 0
                                ? "text-rise"
                                : "text-fall"
                          }`}
                        >
                          {change === null
                            ? "—"
                            : `${change >= 0 ? "+" : ""}${n(change * 100, 2)}%`}
                        </td>
                        <td className="py-2.5 pr-4 text-xs text-faint">
                          {/* Never observed and observed-but-unchanged are
                              different facts, so they read differently. */}
                          {quote.observed_at
                            ? dateTime(quote.observed_at)
                            : t("monitoring.neverPolled")}
                        </td>
                        <td className="py-2.5 text-right">
                          {quote.is_delayed && quote.observed_at && (
                            <span className="rounded border border-watch/30 px-1.5 py-0.5 text-xs text-watch">
                              {t("monitoring.delayed")}
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <Caveat>{t("monitoring.delayedNote")}</Caveat>
          </>
        )}
      </Card>

      <Card
        title={t("alerts.title")}
        action={
          <label className="flex items-center gap-1.5 text-xs text-muted">
            <input
              type="checkbox"
              checked={unreadOnly}
              onChange={(e) => setUnreadOnly(e.target.checked)}
              className="accent-rise"
            />
            {t("alerts.unacknowledgedOnly")}
          </label>
        }
      >
        {alerts.isLoading ? (
          <Loading />
        ) : alerts.isError ? (
          <ErrorNote
            message={(alerts.error as Error).message}
            onRetry={() => alerts.refetch()}
          />
        ) : !alerts.data?.length ? (
          <Empty message={t("alerts.empty")} hint={t("alerts.emptyHint")} />
        ) : (
          <ul className="divide-y divide-line">
            {alerts.data.map((alert) => (
              <li key={alert.id} className="py-3 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <Link
                    to={`/assets/${alert.ticker}`}
                    className="font-mono text-sm text-ink hover:text-rise"
                  >
                    {alert.ticker}
                  </Link>
                  <span
                    className={`rounded border px-1.5 py-0.5 text-xs ${
                      alert.direction === "up"
                        ? "border-rise/30 text-rise"
                        : alert.direction === "down"
                          ? "border-fall/30 text-fall"
                          : "border-line text-muted"
                    }`}
                  >
                    {t(`alert.${alert.kind}` as MessageKey)}
                  </span>
                  <span className="ml-auto text-xs text-faint">
                    {dateTime(alert.triggered_at)}
                  </span>
                  {alert.acknowledged_at ? (
                    <span className="text-xs text-faint">{t("alerts.acknowledged")}</span>
                  ) : (
                    <Button
                      variant="ghost"
                      size="sm"
                      busy={acknowledge.isPending && acknowledge.variables === alert.id}
                      onClick={() => acknowledge.mutate(alert.id)}
                    >
                      {t("alerts.acknowledge")}
                    </Button>
                  )}
                </div>

                <p className="mt-1 text-sm leading-relaxed text-ink/85">{alert.message}</p>

                {/* Where a stance travels: as data, next to a link back to the
                    analysis. Never as a sentence in the message. */}
                {alert.context?.from && alert.context?.to ? (
                  <p className="mt-1 text-xs text-muted">
                    {t("alert.stanceFrom")}{" "}
                    <span className="font-mono text-faint">{String(alert.context.from)}</span>{" "}
                    {t("alert.stanceTo")}{" "}
                    <span className="font-mono text-ink/80">{String(alert.context.to)}</span>
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
        <Caveat>{t("alerts.note")}</Caveat>
      </Card>
    </div>
  );
}
