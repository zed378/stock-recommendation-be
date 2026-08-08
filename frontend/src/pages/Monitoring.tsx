import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { useI18n, type MessageKey } from "@/i18n/context";
import { useToast } from "@/components/toastContext";
import { MarketScan, type Scope as AlertScope } from "@/components/MarketScan";
import {
  Button,
  Card,
  Caveat,
  ConfirmDialog,
  Empty,
  ErrorNote,
  inputClass,
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
  // A Set of ids rather than a flag per alert: the list is refetched on every
  // change, so a selection keyed to array positions would silently point at
  // different rows after a poll.
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [batchError, setBatchError] = useState<string | null>(null);
  // Deleting is not undoable, so it asks. Acknowledging is, so it does not.
  const [confirming, setConfirming] = useState<"delete" | "delete-all" | null>(
    null,
  );
  const toast = useToast();
  // The whole index by default. A screen that only ever shows what you already
  // follow cannot tell you about a stock you have not thought of, which is most
  // of them - and the same criteria are evaluated either way, so the scope is
  // a filter rather than a different feature.
  const [scope, setScope] = useState<AlertScope>("watchlist");

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
    queryKey: ["alerts", unreadOnly, alertSearch],
    queryFn: async () => {
      const { data, error } = await api.GET("/alerts", {
        params: {
          query: {
            unacknowledged_only: unreadOnly,
            search: alertSearch.trim() || undefined,
            limit: 100,
          },
        },
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

  const visibleAlerts = alerts.data ?? [];
  const unacknowledgedCount = visibleAlerts.filter(
    (a) => !a.acknowledged_at,
  ).length;
  const allVisibleSelected =
    visibleAlerts.length > 0 && visibleAlerts.every((a) => selected.has(a.id));

  const toggleSelected = (id: string) =>
    setSelected((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  /**
   * The four batch actions, through one mutation.
   *
   * One server call each, rather than a loop of per-alert requests. Fifty
   * round trips can fail in the middle and leave the list half-acted-on with
   * nothing recording where it stopped; one statement either applies or does
   * not.
   *
   * The count comes back from the server rather than being assumed equal to
   * the selection: ids that were already acknowledged, or that the list has
   * since moved past, are skipped, and saying "3 marked read" when five were
   * ticked is the honest report.
   */
  const batch = useMutation({
    mutationFn: async (input: {
      action: "acknowledge" | "acknowledge-all" | "delete" | "delete-all";
      ids?: string[];
    }) => {
      const path = `/alerts/${input.action}` as
        | "/alerts/acknowledge"
        | "/alerts/acknowledge-all"
        | "/alerts/delete"
        | "/alerts/delete-all";
      const { data, error } = await api.POST(
        path,
        input.ids ? { body: { ids: input.ids } } : {},
      );
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data;
    },
    onSuccess: (result) => {
      // Cleared unconditionally. After a delete the ids no longer exist, and
      // after an acknowledge keeping them ticked invites pressing the same
      // button again on rows that have already changed.
      setSelected(new Set());
      setBatchError(null);
      toast.show({
        title: t("alerts.batchDone", { count: String(result?.affected ?? 0) }),
        tone: "success",
      });
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
      queryClient.invalidateQueries({
        queryKey: ["notifications-unread-count"],
      });
    },
    onError: (caught: Error) => setBatchError(caught.message),
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
        <h1 className="text-lg font-semibold text-ink">
          {t("monitoring.title")}
        </h1>
        <Button
          variant="ghost"
          busy={poll.isPending}
          onClick={() => poll.mutate()}
        >
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
          <Empty
            message={t("monitoring.empty")}
            hint={t("monitoring.emptyHint")}
          />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-xs text-faint">
                    <th className="pb-2 pr-4 font-medium">
                      {t("portfolio.ticker")}
                    </th>
                    <th className="pb-2 pr-4 text-right font-medium">
                      {t("asset.price")}
                    </th>
                    <th className="pb-2 pr-4 text-right font-medium">
                      {t("asset.change")}
                    </th>
                    <th className="pb-2 pr-4 font-medium">
                      {t("monitoring.observedAt")}
                    </th>
                    <th className="pb-2 font-medium" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {quotes.data.map((quote) => {
                    const price =
                      quote.price === null ? null : Number(quote.price);
                    const previous =
                      quote.previous_close === null
                        ? null
                        : Number(quote.previous_close);
                    const change =
                      price !== null && previous
                        ? (price - previous) / previous
                        : null;
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
          <div className="flex flex-wrap items-center gap-3">
            {scope !== "watchlist" ? null : (
              <label className="flex items-center gap-1.5 text-xs text-muted">
                <input
                  type="checkbox"
                  checked={unreadOnly}
                  onChange={(e) => setUnreadOnly(e.target.checked)}
                  className="accent-rise"
                />
                {t("alerts.unacknowledgedOnly")}
              </label>
            )}
            {/* The two whole-list actions live here rather than in the
                selection bar, because they do not act on the selection and a
                button that ignores what is ticked should not sit among the
                ones that do not.

                Both are hidden on the index view: nothing there is stored
                against this account, so there is nothing to mark or clear. */}
            {scope === "watchlist" && (
              <>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={!unacknowledgedCount || batch.isPending}
                  onClick={() => batch.mutate({ action: "acknowledge-all" })}
                >
                  {t("alerts.readAll")}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={!visibleAlerts.length || batch.isPending}
                  onClick={() => setConfirming("delete-all")}
                >
                  {t("alerts.deleteAll")}
                </Button>
              </>
            )}
          </div>
        }
      >
        <nav className="mb-3 flex gap-1 border-b border-line">
          {(
            [
              { id: "watchlist", label: "scan.tab.watchlist" },
              { id: "global", label: "scan.tab.global" },
            ] as { id: AlertScope; label: MessageKey }[]
          ).map((tab) => (
            <button
              key={tab.id}
              onClick={() => {
                setScope(tab.id);
                // The selection belongs to the stored list; carrying it across
                // would leave ids ticked that the other view cannot act on.
                setSelected(new Set());
              }}
              className={`-mb-px border-b-2 px-3 py-2 text-sm transition-colors ${
                scope === tab.id
                  ? "border-rise text-ink"
                  : "border-transparent text-muted hover:text-ink"
              }`}
            >
              {t(tab.label)}
            </button>
          ))}
        </nav>

        <input
          className={`${inputClass} mb-3`}
          value={alertSearch}
          onChange={(event) => setAlertSearch(event.target.value)}
          placeholder={t("alerts.searchPlaceholder")}
          aria-label={t("common.search")}
        />

        {/* The whole index, as the scan computed it this session. Rendered
            inside this card rather than beside it, because it is the same set
            of criteria and a reader should have one place to look. */}
        {scope === "global" && <MarketScan scope="global" bare search={alertSearch} />}

        {scope === "watchlist" && (
          <>
            {/* Only rendered when something is ticked. A bar of disabled buttons
            occupying the top of the list permanently is noise for the far more
            common case of reading alerts rather than managing them. */}
            {selected.size > 0 && (
              <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-line bg-raised/60 p-2">
                <span className="text-xs text-muted">
                  {t("alerts.selectedCount", { count: String(selected.size) })}
                </span>
                <div className="ml-auto flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="ghost"
                    busy={
                      batch.isPending &&
                      batch.variables?.action === "acknowledge"
                    }
                    onClick={() =>
                      batch.mutate({
                        action: "acknowledge",
                        ids: [...selected],
                      })
                    }
                  >
                    {t("alerts.readSelected")}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    busy={
                      batch.isPending && batch.variables?.action === "delete"
                    }
                    onClick={() => setConfirming("delete")}
                  >
                    {t("alerts.deleteSelected")}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setSelected(new Set())}
                  >
                    {t("alerts.clearSelection")}
                  </Button>
                </div>
              </div>
            )}

            {batchError && (
              <div className="mb-3">
                <ErrorNote
                  message={batchError}
                  onRetry={() => setBatchError(null)}
                />
              </div>
            )}

            {visibleAlerts.length > 0 && (
              <label className="mb-2 flex items-center gap-2 text-xs text-muted">
                <input
                  type="checkbox"
                  className="accent-rise"
                  checked={allVisibleSelected}
                  // Indeterminate cannot be expressed as a boolean prop; without
                  // it a partial selection renders as "none selected" and clicking
                  // twice is the only way to work out which way it will go.
                  ref={(node) => {
                    if (node) {
                      node.indeterminate =
                        selected.size > 0 && !allVisibleSelected;
                    }
                  }}
                  onChange={(event) =>
                    setSelected(
                      event.target.checked
                        ? new Set(visibleAlerts.map((a) => a.id))
                        : new Set(),
                    )
                  }
                />
                {t("alerts.selectAll")}
              </label>
            )}

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
                      <input
                        type="checkbox"
                        className="accent-rise"
                        checked={selected.has(alert.id)}
                        onChange={() => toggleSelected(alert.id)}
                        aria-label={t("alerts.selectOne", {
                          ticker: alert.ticker,
                        })}
                      />
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
                        {(() => {
                          let key = `alert.${alert.kind}`;
                          if (alert.kind === "level_approached") {
                            key = "alert.resistance_approached";
                          } else if (alert.kind === "level_crossed") {
                            if (alert.direction === "up")
                              key = "alert.resistance_broken";
                            else if (alert.direction === "down")
                              key = "alert.support_broken";
                          }
                          return t(key as MessageKey);
                        })()}
                      </span>
                      <span className="ml-auto text-xs text-faint">
                        {dateTime(alert.triggered_at)}
                      </span>
                      {alert.acknowledged_at ? (
                        <span className="text-xs text-faint">
                          {t("alerts.acknowledged")}
                        </span>
                      ) : (
                        <Button
                          variant="ghost"
                          size="sm"
                          busy={
                            acknowledge.isPending &&
                            acknowledge.variables === alert.id
                          }
                          onClick={() => acknowledge.mutate(alert.id)}
                        >
                          {t("alerts.acknowledge")}
                        </Button>
                      )}
                    </div>

                    <p className="mt-1 text-sm leading-relaxed text-ink/85">
                      {alert.message}
                    </p>

                    {/* Where a stance travels: as data, next to a link back to the
                    analysis. Never as a sentence in the message. */}
                    {alert.context?.from && alert.context?.to ? (
                      <p className="mt-1 text-xs text-muted">
                        {t("alert.stanceFrom")}{" "}
                        <span className="font-mono text-faint">
                          {String(alert.context.from)}
                        </span>{" "}
                        {t("alert.stanceTo")}{" "}
                        <span className="font-mono text-ink/80">
                          {String(alert.context.to)}
                        </span>
                      </p>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}

        <Caveat>{t("alerts.note")}</Caveat>
      </Card>

      {/* Deleting alerts is not undoable and "delete all" is the one action
          whose scope is not visible from what is ticked, so both ask first.
          Acknowledging does not: it is reversible by the filter and asking
          about it would train people to dismiss the dialog that matters. */}
      {confirming && (
        <ConfirmDialog
          destructive
          busy={batch.isPending}
          title={
            confirming === "delete-all"
              ? t("alerts.deleteAllTitle")
              : t("alerts.deleteSelectedTitle")
          }
          message={
            confirming === "delete-all"
              ? t("alerts.deleteAllBody")
              : t("alerts.deleteSelectedBody", { count: String(selected.size) })
          }
          confirmLabel={t("common.delete")}
          onCancel={() => setConfirming(null)}
          onConfirm={() => {
            const action = confirming;
            setConfirming(null);
            batch.mutate(
              action === "delete-all"
                ? { action: "delete-all" }
                : { action: "delete", ids: [...selected] },
            );
          }}
        />
      )}
    </div>
  );
}
