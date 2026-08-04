import { useState } from "react";
import { useParams } from "react-router-dom";
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
import { PriceChart } from "@/components/PriceChart";
import { Recommendation } from "@/components/Recommendation";
import { IndicatorSnapshotView } from "@/components/Indicators";
import type { components } from "@/api/schema";

type Tab = "chart" | "indicators" | "fundamentals" | "analysis" | "news";

// Typed from the API's own enum rather than as loose strings, so an invented
// timeframe is a compile error rather than a 422 at runtime.
type Timeframe = components["schemas"]["Timeframe"];

const TIMEFRAMES: Timeframe[] = ["1d", "1w", "1M"];

export function AssetDetail() {
  const { ticker = "" } = useParams();
  const { t, n, money, date } = useI18n();
  const queryClient = useQueryClient();

  const [tab, setTab] = useState<Tab>("chart");
  const [timeframe, setTimeframe] = useState<Timeframe>("1d");

  const candles = useQuery({
    queryKey: ["candles", ticker, timeframe],
    queryFn: async () => {
      const { data, error } = await api.GET("/assets/{ticker}/candles", {
        params: { path: { ticker }, query: { timeframe, limit: 400 } },
      });
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data ?? [];
    },
  });

  const ingest = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/assets/{ticker}/ingest", {
        params: { path: { ticker } },
        body: { timeframe, days: 400 },
      });
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["candles", ticker] });
      queryClient.invalidateQueries({ queryKey: ["indicators", ticker] });
    },
  });

  const latest = candles.data?.at(-1);
  const previous = candles.data?.at(-2);
  const change =
    latest && previous ? Number(latest.close) - Number(previous.close) : null;
  const changePct =
    change !== null && previous ? change / Number(previous.close) : null;

  const tabs: { id: Tab; label: string }[] = [
    { id: "chart", label: t("tab.chart") },
    { id: "indicators", label: t("tab.indicators") },
    { id: "fundamentals", label: t("tab.fundamentals") },
    { id: "analysis", label: t("tab.analysis") },
    { id: "news", label: t("tab.news") },
  ];

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-mono text-2xl font-semibold tracking-tight text-ink">
            {ticker.toUpperCase()}
          </h1>
          {latest && (
            <div className="mt-1 flex items-baseline gap-3">
              <span className="font-mono text-lg tnum text-ink">{money(latest.close)}</span>
              {change !== null && changePct !== null && (
                <span
                  className={`font-mono text-sm tnum ${change >= 0 ? "text-rise" : "text-fall"}`}
                >
                  {change >= 0 ? "+" : ""}
                  {n(change, 2)} ({change >= 0 ? "+" : ""}
                  {n(changePct * 100, 2)}%)
                </span>
              )}
              <span className="text-xs text-faint">{date(latest.timestamp)}</span>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2">
          <div className="flex overflow-hidden rounded-md border border-line">
            {TIMEFRAMES.map((option) => (
              <button
                key={option}
                onClick={() => setTimeframe(option)}
                className={`px-2.5 py-1 font-mono text-xs transition-colors ${
                  timeframe === option ? "bg-hover text-ink" : "text-faint hover:text-muted"
                }`}
              >
                {option}
              </button>
            ))}
          </div>
          <Button variant="ghost" busy={ingest.isPending} onClick={() => ingest.mutate()}>
            {ingest.isPending ? t("asset.ingesting") : t("asset.ingest")}
          </Button>
        </div>
      </header>

      {ingest.isSuccess && ingest.data && (
        <p className="rounded-md border border-rise/25 bg-rise/5 px-3 py-2 text-xs text-rise">
          {t("asset.ingestDone", { count: ingest.data.inserted + ingest.data.updated })}
        </p>
      )}
      {ingest.isError && <ErrorNote message={(ingest.error as Error).message} />}

      <nav className="flex gap-1 border-b border-line">
        {tabs.map((item) => (
          <button
            key={item.id}
            onClick={() => setTab(item.id)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm transition-colors ${
              tab === item.id
                ? "border-rise text-ink"
                : "border-transparent text-muted hover:text-ink"
            }`}
          >
            {item.label}
          </button>
        ))}
      </nav>

      {tab === "chart" && (
        <Card>
          {candles.isLoading ? (
            <Loading />
          ) : candles.isError ? (
            <ErrorNote
              message={(candles.error as Error).message}
              onRetry={() => candles.refetch()}
            />
          ) : !candles.data?.length ? (
            <Empty
              message={t("asset.noCandles")}
              hint={t("asset.noCandlesHint")}
              action={
                <Button busy={ingest.isPending} onClick={() => ingest.mutate()}>
                  {t("asset.ingest")}
                </Button>
              }
            />
          ) : (
            <PriceChart candles={candles.data} />
          )}
        </Card>
      )}

      {tab === "indicators" && <Indicators ticker={ticker} timeframe={timeframe} />}
      {tab === "fundamentals" && <Fundamentals ticker={ticker} />}
      {tab === "analysis" && <Analysis ticker={ticker} timeframe={timeframe} />}
      {tab === "news" && <News ticker={ticker} />}
    </div>
  );
}

// --- indicators ------------------------------------------------------------

function Indicators({ ticker, timeframe }: { ticker: string; timeframe: Timeframe }) {
  const { t } = useI18n();
  const query = useQuery({
    queryKey: ["indicators", ticker, timeframe],
    queryFn: async () => {
      const { data, error } = await api.GET("/assets/{ticker}/indicators", {
        params: { path: { ticker }, query: { timeframe } },
      });
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data;
    },
  });

  if (query.isLoading) return <Loading />;
  if (query.isError)
    return <ErrorNote message={(query.error as Error).message} onRetry={() => query.refetch()} />;

  return (
    <IndicatorSnapshotView
      snapshot={query.data?.snapshot}
      features={query.data?.features}
    />
  );
}

// --- fundamentals ----------------------------------------------------------

function Fundamentals({ ticker }: { ticker: string }) {
  const { t, n, money, date } = useI18n();
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ["fundamentals", ticker],
    queryFn: async () => {
      const { data, error } = await api.GET("/assets/{ticker}/fundamentals", {
        params: { path: { ticker } },
      });
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data ?? [];
    },
  });

  const ingest = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/assets/{ticker}/fundamentals/ingest", {
        params: { path: { ticker } },
      });
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["fundamentals", ticker] }),
  });

  const fetchButton = (
    <Button variant="ghost" size="sm" busy={ingest.isPending} onClick={() => ingest.mutate()}>
      {t("fundamentals.ingest")}
    </Button>
  );

  if (query.isLoading) return <Loading />;
  if (query.isError)
    return <ErrorNote message={(query.error as Error).message} onRetry={() => query.refetch()} />;

  if (!query.data?.length) {
    return (
      <Card>
        <Empty
          message={t("fundamentals.empty")}
          hint={t("fundamentals.emptyHint")}
          action={fetchButton}
        />
        {ingest.data?.unsupported && (
          <p className="text-center text-xs text-watch">{ingest.data.note}</p>
        )}
      </Card>
    );
  }

  // Ratios are fractions and money is money; formatting them the same way would
  // print a P/E ratio as "Rp 17,42" and a revenue figure as "77140900000000".
  const isRatio = (metric: string) =>
    /(ratio|margin|return_on|growth|yield|to_book|to_ebitda|to_revenue|to_sales|beta|_pe$|^pe_)/.test(
      metric,
    );
  const isPercentage = (metric: string) =>
    /(return_on|margin|growth|yield)/.test(metric);

  const hasYtd = query.data.some((row) => row.period_type === "ytd");

  return (
    <Card title={t("fundamentals.title")} action={fetchButton}>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-faint">
              <th className="pb-2 pr-4 font-medium">{t("fundamentals.metric")}</th>
              <th className="pb-2 pr-4 text-right font-medium">{t("fundamentals.value")}</th>
              <th className="pb-2 pr-4 font-medium">{t("fundamentals.period")}</th>
              <th className="pb-2 pr-4 font-medium">{t("fundamentals.basis")}</th>
              <th className="pb-2 font-medium">{t("fundamentals.source")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {query.data.map((row, index) => (
              <tr key={`${row.metric}-${index}`}>
                <td className="py-2 pr-4 text-ink/90">{row.metric.replace(/_/g, " ")}</td>
                <td className="py-2 pr-4 text-right font-mono tnum text-ink">
                  {row.value === null
                    ? "—"
                    : isPercentage(row.metric)
                      ? `${n(Number(row.value) * 100, 2)}%`
                      : isRatio(row.metric)
                        ? n(row.value, 2)
                        : money(row.value)}
                </td>
                <td className="py-2 pr-4 text-xs text-muted">{date(row.period)}</td>
                <td className="py-2 pr-4 text-xs text-muted">
                  {t(`fundamentals.basis.${row.period_type}` as MessageKey)}
                </td>
                <td className="py-2 font-mono text-xs text-faint">{row.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Shown only when it applies, so it stays meaningful rather than becoming
          boilerplate the eye skips. */}
      {hasYtd && <Caveat>{t("fundamentals.basisNote")}</Caveat>}
    </Card>
  );
}

// --- analysis --------------------------------------------------------------

// Running an analysis takes the timeframe in the request *body*; reading the
// last one back takes no timeframe at all, because the stored result is the
// latest whatever it was run on. So the two share a query key without it.
function Analysis({ ticker, timeframe }: { ticker: string; timeframe: Timeframe }) {
  const { t } = useI18n();
  const queryClient = useQueryClient();

  const existing = useQuery({
    queryKey: ["analysis", ticker],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/assets/{ticker}/analysis", {
        params: { path: { ticker } },
      });
      // No analysis yet is a normal state, not a failure to report.
      if (response.status === 404) return null;
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data ?? null;
    },
  });

  const run = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/assets/{ticker}/analysis", {
        params: { path: { ticker } },
        body: { timeframe, exchange: "IDX", include_recommendation: true },
      });
      if (error) throw new Error(errorMessage(error, t("analysis.failed")));
      return data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(["analysis", ticker], data);
    },
  });

  const result = run.data ?? existing.data;

  const runButton = (
    <Button busy={run.isPending} onClick={() => run.mutate()}>
      {run.isPending ? t("analysis.running") : t("analysis.run")}
    </Button>
  );

  if (existing.isLoading) return <Loading />;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-sm font-medium text-ink">{t("analysis.title")}</h2>
        {runButton}
      </div>

      {run.isPending && (
        <Card>
          <div className="flex flex-col items-center gap-2 py-8 text-center">
            <Loading label={t("analysis.running")} />
            <p className="text-xs text-faint">{t("analysis.runningHint")}</p>
          </div>
        </Card>
      )}

      {run.isError && <ErrorNote message={(run.error as Error).message} />}

      {!run.isPending && !result && (
        <Card>
          <Empty message={t("analysis.empty")} action={runButton} />
        </Card>
      )}

      {result && !run.isPending && (
        <>
          <AgentRoster result={result} />
          {result.recommendation && <Recommendation rec={result.recommendation} />}
        </>
      )}
    </div>
  );
}

/**
 * Which agents ran, and which did not.
 *
 * A skipped agent is not a hidden implementation detail: it is the direct cause
 * of a lower confidence score, so showing the score without the reason would
 * make the score look arbitrary.
 */
function AgentRoster({
  result,
}: {
  result: { agents?: unknown; skipped?: unknown; failed?: unknown };
}) {
  const { t } = useI18n();

  const agents = Array.isArray(result.agents) ? result.agents : [];
  const skipped = Array.isArray(result.skipped) ? result.skipped : [];
  const failed = Array.isArray(result.failed) ? result.failed : [];

  const nameOf = (entry: unknown) =>
    typeof entry === "string" ? entry : String((entry as { agent?: string })?.agent ?? "");
  const reasonOf = (entry: unknown) =>
    typeof entry === "object" && entry
      ? String((entry as { reason?: string }).reason ?? "")
      : "";

  return (
    <Card>
      <div className="flex flex-wrap items-start gap-x-8 gap-y-4">
        <div>
          <p className="mb-1.5 text-xs text-faint">{t("analysis.agentsRan")}</p>
          <div className="flex flex-wrap gap-1.5">
            {agents.map((agent, index) => (
              <span
                key={index}
                className="rounded border border-rise/25 bg-rise/5 px-2 py-0.5 font-mono text-xs text-rise/90"
              >
                {nameOf(agent).replace(/_/g, " ")}
              </span>
            ))}
          </div>
        </div>

        {skipped.length > 0 && (
          <div className="min-w-64 flex-1">
            <p className="mb-1.5 text-xs text-faint">{t("analysis.skipped")}</p>
            <ul className="space-y-1">
              {skipped.map((entry, index) => (
                <li key={index} className="text-xs text-muted">
                  <span className="font-mono text-watch">
                    {nameOf(entry).replace(/_/g, " ")}
                  </span>
                  {reasonOf(entry) && <span className="text-faint"> — {reasonOf(entry)}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}

        {failed.length > 0 && (
          <div className="min-w-64 flex-1">
            <p className="mb-1.5 text-xs text-faint">{t("analysis.agentFailed")}</p>
            <ul className="space-y-1">
              {failed.map((entry, index) => (
                <li key={index} className="text-xs text-fall/80">
                  <span className="font-mono">{nameOf(entry).replace(/_/g, " ")}</span>
                  {reasonOf(entry) && <span className="text-faint"> — {reasonOf(entry)}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {skipped.length > 0 && <Caveat>{t("analysis.skippedNote")}</Caveat>}
    </Card>
  );
}

// --- news ------------------------------------------------------------------

function News({ ticker }: { ticker: string }) {
  const { t, dateTime } = useI18n();
  const query = useQuery({
    queryKey: ["news", ticker],
    queryFn: async () => {
      const { data, error } = await api.GET("/assets/{ticker}/news", {
        params: { path: { ticker }, query: { limit: 30 } },
      });
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return (data ?? []) as Record<string, unknown>[];
    },
  });

  if (query.isLoading) return <Loading />;
  if (query.isError)
    return <ErrorNote message={(query.error as Error).message} onRetry={() => query.refetch()} />;
  if (!query.data?.length)
    return <Card><Empty message={t("analysis.empty")} /></Card>;

  return (
    <Card>
      <ul className="divide-y divide-line">
        {query.data.map((item, index) => (
          <li key={index} className="py-3 first:pt-0 last:pb-0">
            <div className="flex items-baseline justify-between gap-4">
              <p className="text-sm text-ink/90">{String(item.headline ?? "")}</p>
              <span className="shrink-0 text-xs text-faint">
                {dateTime(String(item.published_at ?? ""))}
              </span>
            </div>
            {item.body_summary ? (
              <p className="mt-1 text-xs leading-relaxed text-muted">
                {String(item.body_summary)}
              </p>
            ) : null}
            <p className="mt-1 font-mono text-xs text-faint">{String(item.source ?? "")}</p>
          </li>
        ))}
      </ul>
    </Card>
  );
}
