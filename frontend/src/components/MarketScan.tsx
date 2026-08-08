import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { useI18n, type MessageKey } from "@/i18n/context";
import { Pager, type PageState } from "@/components/Pager";
import { MultiSelect } from "@/components/MultiSelect";
import { Card, Empty, ErrorNote, Loading } from "@/components/primitives";

/**
 * Today's criteria matches across the exchange, optionally narrowed to a
 * watchlist.
 *
 * Not a separate feature from the alerts, and deliberately not presented as
 * one: these are the same conditions the alert rules evaluate, run over every
 * issuer rather than only the ones somebody happens to follow. It lives inside
 * the alerts card so a reader has one place to look, with the whole index as
 * the default and their own tickers a filter away.
 *
 * Nothing here is acknowledgeable, and that is the honest difference from a
 * stored alert. An alert is an event that happened to *you* and stays until
 * you have seen it; this is the state of the market today, recomputed every
 * session. Offering "mark read" on a row that will simply be recalculated
 * tomorrow would be a control that does nothing.
 */

export type Scope = "watchlist" | "global";

export function MarketScan({
  scope,
  bare = false,
}: {
  scope: Scope;
  /** Rendered without its own card, for embedding in one. */
  bare?: boolean;
}) {
  const { t, money, date } = useI18n();

  const [criteria, setCriteria] = useState<string[]>([]);
  const [page, setPage] = useState<PageState>({ limit: 25, offset: 0 });

  const options = useQuery({
    queryKey: ["scan-criteria"],
    queryFn: async () => {
      const { data, error } = await api.GET("/market-scan/criteria");
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data ?? [];
    },
    // The vocabulary changes only when the code does.
    staleTime: Infinity,
  });

  const scan = useQuery({
    queryKey: ["market-scan", scope, criteria, page],
    queryFn: async () => {
      const { data, error } = await api.GET("/market-scan", {
        params: {
          query: { scope, matched: criteria, limit: page.limit, offset: page.offset },
        },
      });
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data ?? { items: [], total: 0, limit: page.limit, offset: page.offset };
    },
    placeholderData: (previous) => previous,
  });

  const rows = scan.data?.items ?? [];

  const body = (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <MultiSelect
          label={t("scan.criteria")}
          placeholder={t("scan.criteria")}
          options={options.data ?? []}
          selected={criteria}
          onChange={(next) => {
            setCriteria(next);
            setPage((current) => ({ ...current, offset: 0 }));
          }}
        />
        {scan.data?.items?.[0] && (
          <span className="text-xs text-faint">
            {t("scan.asOf", { when: date(scan.data.items[0].session_date) })}
          </span>
        )}
      </div>

      {scan.isLoading ? (
        <Loading />
      ) : scan.isError ? (
        <ErrorNote message={(scan.error as Error).message} onRetry={() => scan.refetch()} />
      ) : rows.length === 0 ? (
        <Empty
          message={
            scope === "watchlist" ? t("scan.emptyWatchlist") : t("scan.emptyGlobal")
          }
          hint={t("scan.emptyHint")}
        />
      ) : (
        <ul className="divide-y divide-line">
          {rows.map((row) => (
            <li key={row.ticker} className="py-3 first:pt-0 last:pb-0">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <Link
                  to={`/assets/${row.ticker}`}
                  className="font-mono text-sm font-medium text-ink hover:text-rise"
                >
                  {row.ticker}
                </Link>
                {row.close !== null && row.close !== undefined && (
                  <span className="font-mono text-xs tnum text-muted">{money(row.close)}</span>
                )}
                <span className="ml-auto text-xs text-faint">
                  {t("scan.matchedCount", { count: String(row.matched_count) })}
                </span>
              </div>

              {/* The criteria themselves, not a score. A tally is a count of
                  conditions met; rendering it as a single number invites
                  reading it as a probability of something. */}
              <div className="mt-1.5 flex flex-wrap gap-1">
                {(row.matched ?? []).map((kind) => (
                  <span
                    key={kind}
                    className="rounded border border-line px-1.5 py-0.5 text-[0.7rem] text-muted"
                  >
                    {t(`alert.${kind}` as MessageKey)}
                  </span>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}

      <Pager
        total={scan.data?.total ?? 0}
        shown={rows.length}
        page={page}
        onChange={setPage}
      />
    </>
  );

  return bare ? body : <Card title={t("scan.title")}>{body}</Card>;
}
