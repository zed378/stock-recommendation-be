import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { useI18n, type MessageKey } from "@/i18n/context";
import {
  Button,
  Card,
  Caveat,
  Empty,
  inputClass,
  ErrorNote,
  Loading,
} from "@/components/primitives";
import { PriceChart } from "@/components/PriceChart";
import { Recommendation } from "@/components/Recommendation";
import { IndicatorSnapshotView } from "@/components/Indicators";
import { Strategy } from "@/components/Strategy";
import { LanguageSwitch, TranslationNotice } from "@/components/TranslateToggle";
import { useTranslation } from "@/components/useTranslation";
import type { components } from "@/api/schema";

type Tab = "chart" | "indicators" | "fundamentals" | "analysis" | "strategy" | "news";

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
    { id: "strategy", label: t("tab.strategy") },
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
      {tab === "strategy" && <Strategy ticker={ticker} />}
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
  const { t, dateTime } = useI18n();
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

  /**
   * Queued, not run on the request.
   *
   * A full multi-agent run is a dozen model calls and now several translations
   * on top; holding an HTTP connection open for all of it makes whatever sits
   * in front of the server the real limit on how thorough an analysis can be.
   * Behind Cloudflare that limit is a fixed 100 seconds and the reader gets a
   * 524 error page - the work carries on and its result is thrown away.
   *
   * So the request returns in milliseconds with a job id and this polls it.
   * Nothing in the path can time out, because nothing in the path is slow. The
   * notification that already exists announces the finish, so the reader does
   * not have to sit here either.
   */
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);

  const start = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/assets/{ticker}/analysis/background", {
        params: { path: { ticker } },
        body: { timeframe, exchange: "IDX", include_recommendation: true },
      });
      if (error) throw new Error(errorMessage(error, t("analysis.failed")));
      return data;
    },
    onSuccess: (data) => {
      setJobError(null);
      setJobId(String(data.job_id));
    },
  });

  const job = useQuery({
    queryKey: ["analysis-job", jobId],
    enabled: jobId !== null,
    queryFn: async () => {
      const { data, error } = await api.GET("/jobs/{job_id}", {
        params: { path: { job_id: jobId as string } },
      });
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data;
    },
    // Stops polling once the job reaches a state it cannot leave. Left running,
    // this would keep asking about a finished job for as long as the tab is open.
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && ["succeeded", "failed", "dead"].includes(status) ? false : 4000;
    },
  });

  useEffect(() => {
    const status = job.data?.status;
    if (!status) return;

    if (status === "succeeded") {
      queryClient.invalidateQueries({ queryKey: ["analysis", ticker] });
      setJobId(null);
    } else if (status === "failed" || status === "dead") {
      // `dead` means the retries are exhausted. Either way the reason is on
      // the job, and showing it beats a generic failure the reader cannot act on.
      setJobError(job.data?.last_error || t("analysis.failed"));
      setJobId(null);
    }
  }, [job.data?.status, job.data?.last_error, queryClient, ticker, t]);

  const running = start.isPending || jobId !== null;
  const result = existing.data;

  // Whether there is a second language to switch *to*. Read off what was
  // actually stored rather than off a flag, so a partial rendering - some
  // agents translated, some not - is judged on what a reader would see.
  const bothLanguagesReady = useMemo(() => {
    const agents = (result?.agents ?? {}) as Record<string, AgentPayload>;
    const entries = Object.values(agents);
    if (!entries.length) return false;
    const source = entries[0]?.language ?? "en";
    const target = source === "id" ? "en" : "id";
    return entries.some((agent) => agent?.translations?.[target]?.fields);
  }, [result]);

  // One hook for the whole tab, driven by the recommendation because that is
  // the payload with a fetch fallback for analyses stored before renderings
  // were kept. The agents follow whatever it decides, so the evidence and the
  // conclusion can never end up in different languages at once.
  //
  // Called unconditionally, above the early return below: a hook behind a
  // condition changes the hook order between renders.
  // What the stored prose is actually in, which is what a single-language
  // export has to produce. Read off the agents rather than assumed, because a
  // deployment can change the setting between runs.
  const analysisLanguage = useMemo(() => {
    const agents = (result?.agents ?? {}) as Record<string, AgentPayload>;
    return Object.values(agents)[0]?.language ?? "en";
  }, [result]);

  const translation = useTranslation(
    (result?.recommendation ?? {}) as unknown as Record<string, unknown>,
  );

  // Fetched here as well as in the Strategy tab, because the export covers
  // both and reaching into a sibling tab's state to get it would couple two
  // components that have no other reason to know about each other. React Query
  // dedupes it against the identical key, so it is one request either way.
  const strategy = useQuery({
    queryKey: ["strategy", ticker],
    queryFn: async () => {
      const { data, error } = await api.GET("/assets/{ticker}/strategy", {
        params: { path: { ticker } },
      });
      // A missing strategy is not an error here: the export simply leaves that
      // section out rather than refusing to produce a document.
      return error ? null : data;
    },
    enabled: Boolean(result),
  });

  const exportPdf = useMutation({
    mutationFn: async (language: string) => {
      const { buildAnalysisPdf, downloadPdf } = await import("@/export/analysisPdf");
      const blob = await buildAnalysisPdf({
        ticker: ticker.toUpperCase(),
        language,
        timeframe,
        generatedAt: dateTime(new Date().toISOString()),
        recommendation: result?.recommendation ?? null,
        strategy: strategy.data ?? null,
        agents: (result?.agents ?? {}) as Record<string, Record<string, unknown>>,
        labels: {
          title: t("analysis.title"),
          generated: t("export.generated"),
          timeframe: t("export.timeframe"),
          recommendation: t("rec.title"),
          confidence: t("rec.confidence"),
          horizon: t("rec.horizon"),
          entry: t("export.entry"),
          target: t("rec.target"),
          stop: t("rec.stop"),
          rationale: t("rec.reasoning"),
          strategy: t("tab.strategy"),
          notHolding: t("strategy.notHolding"),
          holding: t("strategy.holding"),
          conditions: t("strategy.conditions"),
          invalidatedIf: t("strategy.invalidatedIf"),
          agents: t("export.agents"),
          disclaimer: t("disclaimer.title"),
          disclaimerBody: t("disclaimer.long"),
          page: t("export.page"),
        },
      });
      downloadPdf(blob, `${ticker.toUpperCase()}-analysis-${language}.pdf`);
    },
  });

  const runButton = (
    <Button busy={running} onClick={() => start.mutate()}>
      {running ? t("analysis.running") : t("analysis.run")}
    </Button>
  );

  if (existing.isLoading) return <Loading />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-medium text-ink">{t("analysis.title")}</h2>
        <div className="flex items-center gap-2">
          {/* One control for the whole tab. There used to be one per card, and
              reading a single analysis in the other language meant finding and
              flipping each of them - which also let the agents and the
              conclusion sit in different languages at the same time. */}
          {/* Only once both languages exist. Translation is a job that runs
              after the analysis, so for a stretch there is exactly one language
              and a switch would offer to change to nothing - the reader presses
              it, nothing happens, and the control has taught them not to trust
              it. It appears by itself when the rendering lands, because the
              event invalidates this query. */}
          {result && !running && bothLanguagesReady && (
            <LanguageSwitch
              showing={translation.showing}
              isPending={translation.isPending}
              source={translation.source}
              target={translation.target}
              onOriginal={translation.showOriginal}
              onTranslate={translation.showTranslation}
            />
          )}
          {/* Only once there is something to export. A button that produces an
              empty document teaches the reader it does not work. */}
          {/* A choice only when there is one. Until the translation job has
              finished there is a single rendering, and a language menu whose
              other option silently produces the same document is worse than a
              plain button - it claims something the file will not deliver. */}
          {result && !running && (
            bothLanguagesReady ? (
              <select
                className={`${inputClass} py-1 text-xs`}
                value=""
                disabled={exportPdf.isPending}
                onChange={(event) => {
                  if (event.target.value) exportPdf.mutate(event.target.value);
                  // Reset, so the control reads as an action rather than as a
                  // setting that now claims to be "Indonesian".
                  event.target.value = "";
                }}
                aria-label={t("export.pdf")}
              >
                <option value="">
                  {exportPdf.isPending ? t("export.building") : t("export.pdf")}
                </option>
                <option value="en">{t("export.inEnglish")}</option>
                <option value="id">{t("export.inIndonesian")}</option>
              </select>
            ) : (
              <Button
                variant="ghost"
                busy={exportPdf.isPending}
                onClick={() => exportPdf.mutate(analysisLanguage)}
              >
                {t("export.pdf")}
              </Button>
            )
          )}
          {runButton}
        </div>
      </div>

      {exportPdf.isError && (
        <ErrorNote message={(exportPdf.error as Error).message} />
      )}

      {running && (
        <Card>
          <div className="flex flex-col items-center gap-2 py-8 text-center">
            <Loading label={t("analysis.running")} />
            <p className="text-xs text-faint">{t("analysis.runningHint")}</p>
          </div>
        </Card>
      )}

      {start.isError && <ErrorNote message={(start.error as Error).message} />}
      {jobError && <ErrorNote message={jobError} onRetry={() => setJobError(null)} />}

      {!running && !result && (
        <Card>
          <Empty message={t("analysis.empty")} action={runButton} />
        </Card>
      )}

      {result && !running && (
        <>
          <AgentRoster result={result} />
          <AgentReports agents={result.agents} showing={translation.showing} />
          {result.recommendation && (
            <RecommendationPanel
              rec={result.recommendation}
              rendered={translation.rendered}
              showing={translation.showing}
              error={translation.error}
            />
          )}
        </>
      )}
    </div>
  );
}

/**
 * The recommendation, with the language switch in the header where it is found.
 *
 * Only the prose is translated. The label, confidence, and prices come from the
 * stored analysis either way, so the two renderings cannot disagree about the
 * stance - which is the whole reason this is a translation rather than a second
 * analysis.
 */
function RecommendationPanel({
  rec,
  rendered,
  showing,
  error,
}: {
  rec: NonNullable<components["schemas"]["AnalysisResponse"]["recommendation"]>;
  /** Already resolved by the tab's single language control. */
  rendered: Record<string, unknown>;
  showing: boolean;
  error: string | null;
}) {
  const { t } = useI18n();

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-medium text-ink">{t("rec.title")}</h3>

      <TranslationNotice showing={false} error={error} />

      <Recommendation rec={{ ...rec, ...rendered } as typeof rec} />

      <TranslationNotice showing={showing} error={null} />
    </div>
  );
}

type AgentPayload = {
  language?: string;
  translations?: Record<string, { fields?: Record<string, unknown> }>;
  [key: string]: unknown;
};

/**
 * What each agent actually found, in either language.
 *
 * The roster above says *which* agents ran; this is what they said. It was
 * never shown - the reasoning behind a stance sat in the database and nothing
 * rendered it.
 *
 * One switch for the whole set rather than one per agent. Flipping six
 * controls to read one analysis is hostile, and every agent in a run is
 * written in the same language anyway.
 *
 * Reads only what the analysis stored. Older runs have no per-agent rendering,
 * and the switch says so instead of quietly fetching six translations - which
 * is the cost this was moved into the analysis to avoid.
 */
function AgentReports({
  agents,
  showing,
}: {
  agents: unknown;
  /** Whether the reader has asked for the other language. The control at the
   *  top of the tab says *whether*; which language that is, is resolved here. */
  showing: boolean;
}) {
  const { t } = useI18n();

  const entries = useMemo(() => {
    if (!agents || typeof agents !== "object") return [];
    return Object.entries(agents as Record<string, AgentPayload>);
  }, [agents]);

  if (!entries.length) return null;

  // Resolved against what these agents say they are, not against what the
  // recommendation says. The two normally agree - one run writes both - but an
  // analysis stored while the output language was changing has agents in
  // English and a recommendation labelled Indonesian, and taking the target
  // from the recommendation then looked for a rendering that was never made
  // while the one that *was* made sat unreachable.
  const source = entries[0][1]?.language ?? "en";
  const target = source === "id" ? "en" : "id";
  const available = entries.some((entry) => entry[1]?.translations?.[target]?.fields);

  return (
    <Card title={t("analysis.agentFindings")}>
      {/* At the top, not the bottom. This card is thousands of pixels tall, and
          an explanation for why the switch appeared to do nothing is useless
          below the content it failed to change - the reader is looking here,
          at the control they just pressed.

          Only while they are asking for the other language: saying it unprompted
          would be a warning about something that has not happened. */}
      {showing && !available && (
        <div className="mb-4 rounded-md border border-watch/30 bg-watch/5 px-3 py-2">
          <p className="text-xs leading-relaxed text-watch">
            {t("analysis.noAgentTranslation")}
          </p>
        </div>
      )}

      <div className="space-y-5">
        {entries.map(([name, payload]) => (
          <AgentReport
            key={name}
            name={name}
            payload={payload}
            translated={showing ? payload?.translations?.[target]?.fields : undefined}
          />
        ))}
      </div>
    </Card>
  );
}

/** One agent's write-up: its prose, and the lists it produced. */
function AgentReport({
  name,
  payload,
  translated,
}: {
  name: string;
  payload: AgentPayload;
  translated: Record<string, unknown> | undefined;
}) {
  const { t } = useI18n();
  const fields = { ...payload, ...(translated ?? {}) };

  const prose = ["summary", "reasoning"]
    .map((key) => fields[key])
    .filter((value): value is string => typeof value === "string" && value.length > 0);

  const lists = (
    [
      ["signals", "analysis.signals"],
      ["supporting_factors", "rec.supporting"],
      ["conflicting_factors", "rec.conflicting"],
      ["risk_factors", "rec.risks"],
      ["watch_items", "analysis.watchItems"],
      ["disagreements", "analysis.disagreements"],
    ] as const
  )
    .map(([key, label]) => [label, fields[key]] as const)
    .filter(([, value]) => Array.isArray(value) && value.length > 0);

  if (!prose.length && !lists.length) return null;

  return (
    <section>
      <h3 className="mb-1.5 font-mono text-xs uppercase tracking-wide text-muted">
        {name.replace(/_/g, " ")}
      </h3>
      {prose.map((text) => (
        <p key={text.slice(0, 40)} className="text-sm leading-relaxed text-ink/90">
          {text}
        </p>
      ))}
      {lists.map(([label, value]) => (
        <div key={label} className="mt-2">
          <p className="text-xs text-faint">{t(label)}</p>
          <ul className="mt-0.5 space-y-0.5">
            {(value as unknown[]).map((item, index) => (
              <li key={index} className="text-xs leading-relaxed text-muted">
                — {typeof item === "string" ? item : JSON.stringify(item)}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
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

  // The API returns `agents` keyed by name, not as a list. This used to test
  // `Array.isArray` and fall back to `[]`, so the roster rendered nothing at
  // all - the panel had been silently empty for as long as it had existed.
  const agents =
    result.agents && typeof result.agents === "object"
      ? Object.keys(result.agents as Record<string, unknown>)
      : [];
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
  // Said "No analysis for this ticker yet" on the News tab, which is a
  // different subsystem's empty state and told the reader nothing true.
  if (!query.data?.length)
    return (
      <Card>
        <Empty message={t("news.empty")} hint={t("news.emptyHint")} />
      </Card>
    );

  return (
    <Card>
      <ul className="divide-y divide-line">
        {query.data.map((item, index) => {
          const others = ((item.tickers as string[]) ?? []).filter((code) => code !== ticker);
          const matched = item.matched_on as { method: string; text: string } | null;
          const url = String(item.source_url ?? "");
          return (
            <li key={index} className="py-3 first:pt-0 last:pb-0">
              <div className="flex items-baseline justify-between gap-4">
                {/* Linked out. A headline with no way to reach the article is
                    a claim the reader cannot check. */}
                {url ? (
                  <a
                    href={url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="text-sm text-ink/90 hover:text-rise"
                  >
                    {String(item.headline ?? "")}
                  </a>
                ) : (
                  <p className="text-sm text-ink/90">{String(item.headline ?? "")}</p>
                )}
                <span className="shrink-0 text-xs text-faint">
                  {dateTime(String(item.published_at ?? ""))}
                </span>
              </div>

              {item.summary ? (
                <p className="mt-1 text-xs leading-relaxed text-muted">
                  {String(item.summary)}
                </p>
              ) : null}

              <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="font-mono text-xs text-faint">{String(item.source ?? "")}</span>

                {/* Why this story is filed here. A tag nobody can account for
                    is how a wrong one survives unnoticed. */}
                {matched && (
                  <span className="text-xs text-faint" title={matched.text}>
                    {t(`news.matched.${matched.method}` as MessageKey)}
                  </span>
                )}

                {/* The other issuers it names, so a sector piece reads as one
                    rather than as news about this ticker alone. */}
                {others.length > 0 && (
                  <span className="flex flex-wrap items-center gap-1 text-xs text-faint">
                    {t("news.alsoAbout")}
                    {others.slice(0, 6).map((code) => (
                      <Link
                        key={code}
                        to={`/assets/${code}`}
                        className="font-mono text-xs text-muted hover:text-rise"
                      >
                        {code}
                      </Link>
                    ))}
                  </span>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
