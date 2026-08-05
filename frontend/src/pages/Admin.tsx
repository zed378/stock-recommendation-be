import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { useAuth } from "@/auth/context";
import { useI18n, type MessageKey } from "@/i18n/context";
import {
  Button,
  Card,
  Caveat,
  Empty,
  ErrorNote,
  Loading,
  Stat,
} from "@/components/primitives";

type Tab = "overview" | "queue" | "providers" | "budget" | "audit";

/**
 * The operations side of the platform.
 *
 * Guarded by role rather than by hiding the link: a route that is merely
 * unlinked is still reachable by typing it, and the interesting failure is a
 * page that renders its shell and then 403s every panel inside it. The backend
 * enforces this independently - this is about telling the user *why*, not about
 * being the control.
 */
export function Admin() {
  const { t } = useI18n();
  const { user } = useAuth();
  const [tab, setTab] = useState<Tab>("overview");

  if (user && user.role !== "admin") {
    return (
      <Card>
        <Empty
          message={t("admin.forbidden")}
          hint={t("admin.forbiddenHint", { email: user.email })}
        />
      </Card>
    );
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: "overview", label: t("admin.tab.overview") },
    { id: "queue", label: t("admin.tab.queue") },
    { id: "providers", label: t("admin.tab.providers") },
    { id: "budget", label: t("admin.tab.budget") },
    { id: "audit", label: t("admin.tab.audit") },
  ];

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold text-ink">{t("admin.title")}</h1>

      <nav className="flex flex-wrap gap-1 border-b border-line">
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

      {tab === "overview" && <Overview />}
      {tab === "queue" && <Queue />}
      {tab === "providers" && <Providers />}
      {tab === "budget" && <Budget />}
      {tab === "audit" && <AuditLog />}
    </div>
  );
}

/**
 * Counts, rendered as counts.
 *
 * Deliberately not a generic renderer any more. The previous one
 * `JSON.stringify`d whatever it did not understand, so a nested `by_agent` map
 * spilled a wall of JSON out of its card and pushed the page wider than the
 * viewport - the same failure the indicator snapshot had. Every panel below now
 * knows the shape it is showing, and anything nested gets a component that can
 * lay it out.
 */
function Counts({ data, labels }: { data: unknown; labels: Record<string, MessageKey> }) {
  const { t, n } = useI18n();
  const entries = Object.entries((data ?? {}) as Record<string, unknown>).filter(
    ([, value]) => typeof value === "number",
  );
  if (!entries.length) return <p className="text-sm text-faint">{t("common.none")}</p>;

  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3 lg:grid-cols-4">
      {entries.map(([key, value]) => (
        <Stat
          key={key}
          label={labels[key] ? t(labels[key]) : key.replace(/_/g, " ")}
          value={n(value as number, 0)}
        />
      ))}
    </dl>
  );
}

function Overview() {
  const { t, dateTime } = useI18n();
  const [windowDays, setWindowDays] = useState(7);

  const query = useQuery({
    queryKey: ["admin-overview", windowDays],
    queryFn: async () => {
      const { data, error } = await api.GET("/admin/overview", {
        params: { query: { window_days: windowDays } },
      });
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data;
    },
  });

  if (query.isLoading) return <Loading />;
  if (query.isError)
    return <ErrorNote message={(query.error as Error).message} onRetry={() => query.refetch()} />;

  const data = query.data;
  const attention = Array.isArray(data?.attention) ? data.attention : [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex overflow-hidden rounded-md border border-line">
          {[1, 7, 30].map((days) => (
            <button
              key={days}
              onClick={() => setWindowDays(days)}
              className={`px-2.5 py-1 font-mono text-xs transition-colors ${
                windowDays === days ? "bg-hover text-ink" : "text-faint hover:text-muted"
              }`}
            >
              {t("admin.windowDays", { days })}
            </button>
          ))}
        </div>
        {data?.generated_at && (
          <span className="text-xs text-faint">
            {t("admin.generatedAt", { time: dateTime(data.generated_at) })}
          </span>
        )}
      </div>

      {/* First, because it is the reason to open this page at all. An empty
          list is stated rather than left blank - "nothing needs attention" and
          "the panel failed to load" must not look the same. */}
      <Card title={t("admin.attention")}>
        {attention.length === 0 ? (
          <p className="text-sm text-rise/80">{t("admin.attentionNone")}</p>
        ) : (
          <ul className="space-y-2">
            {attention.map((item, index) => (
              <li
                key={index}
                className="relative rounded border border-watch/25 bg-watch/5 px-3 py-2 text-sm text-watch"
              >
                {typeof item === "string" ? item : JSON.stringify(item)}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title={t("admin.inventory")}>
        <Counts
          data={data?.inventory}
          labels={{
            users: "admin.users",
            assets: "admin.assets",
            price_bars: "admin.priceBars",
            news_items: "admin.newsItems",
            analyses: "admin.analyses",
            recommendations: "admin.recommendations",
            active_schedules: "admin.activeSchedules",
          }}
        />
      </Card>

      <Ingestion data={data?.ingestion} />
      <AiUsage data={data?.ai_usage} />
    </div>
  );
}

interface IngestionData {
  runs?: number;
  failed?: number;
  success_rate?: number;
  bars_ingested?: number;
  bars_rejected?: number;
  last_run_at?: string | null;
  recent_failures?: unknown[];
}

function Ingestion({ data }: { data: unknown }) {
  const { t, n, dateTime } = useI18n();
  const flow = (data ?? {}) as IngestionData;
  const rate = flow.success_rate;
  const failures = Array.isArray(flow.recent_failures) ? flow.recent_failures : [];

  return (
    <Card title={t("admin.ingestion")}>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3 lg:grid-cols-5">
        <Stat label={t("admin.runs")} value={n(flow.runs ?? null, 0)} />
        <Stat
          label={t("admin.failedRuns")}
          value={n(flow.failed ?? null, 0)}
          tone={(flow.failed ?? 0) > 0 ? "fall" : "neutral"}
        />
        {/* A fraction, not a count. Printing 1.0 as "1" reads as one run
            succeeding rather than as all of them. */}
        <Stat
          label={t("admin.successRate")}
          value={rate === undefined || rate === null ? "—" : `${n(rate * 100, 0)}%`}
          tone={rate !== undefined && rate !== null && rate < 1 ? "fall" : "rise"}
        />
        <Stat label={t("admin.barsIngested")} value={n(flow.bars_ingested ?? null, 0)} />
        <Stat
          label={t("admin.barsRejected")}
          value={n(flow.bars_rejected ?? null, 0)}
          tone={(flow.bars_rejected ?? 0) > 0 ? "watch" : "neutral"}
        />
      </dl>

      <dl className="mt-4 grid gap-x-6 gap-y-4 border-t border-line pt-4 sm:grid-cols-2">
        <Stat
          label={t("admin.lastRun")}
          // Never-run and run-just-now are different facts, so they read
          // differently rather than one showing a raw ISO string.
          value={flow.last_run_at ? dateTime(flow.last_run_at) : t("admin.neverRun")}
          mono={false}
        />
        <div>
          <dt className="text-xs text-faint">{t("admin.recentFailures")}</dt>
          <dd className="mt-0.5 text-sm">
            {failures.length === 0 ? (
              // "None" rather than an empty array printed literally.
              <span className="text-rise/80">{t("admin.noFailures")}</span>
            ) : (
              <ul className="space-y-1">
                {failures.map((failure, index) => (
                  <li key={index} className="text-xs leading-relaxed text-fall/90">
                    {typeof failure === "string" ? failure : JSON.stringify(failure)}
                  </li>
                ))}
              </ul>
            )}
          </dd>
        </div>
      </dl>
    </Card>
  );
}

interface AgentUsage {
  calls?: number;
  tokens?: number;
  cost?: string | number;
}

function AiUsage({ data }: { data: unknown }) {
  const { t, n } = useI18n();
  const usage = (data ?? {}) as {
    total_tokens?: number;
    total_calls?: number;
    estimated_cost?: string | number;
    by_agent?: Record<string, AgentUsage>;
    note?: string;
  };

  // Sorted by spend, because "which agent is costing the most" is the question
  // this panel exists to answer. Alphabetical order answers nothing.
  const agents = Object.entries(usage.by_agent ?? {}).sort(
    (a, b) => (b[1].tokens ?? 0) - (a[1].tokens ?? 0),
  );

  return (
    <Card title={t("admin.aiUsage")}>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3">
        <Stat label={t("admin.totalTokens")} value={n(usage.total_tokens ?? null, 0)} />
        <Stat label={t("admin.totalCalls")} value={n(usage.total_calls ?? null, 0)} />
        <Stat label={t("admin.estimatedCost")} value={n(usage.estimated_cost ?? null, 2)} />
      </dl>

      {agents.length > 0 && (
        <div className="mt-4 border-t border-line pt-4">
          <p className="mb-2 text-xs text-faint">{t("admin.byAgent")}</p>
          {/* A table, because it is tabular. The previous renderer stringified
              this map and pushed the whole page sideways. */}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs text-faint">
                  <th className="pb-2 pr-4 font-medium">{t("admin.agent")}</th>
                  <th className="pb-2 pr-4 text-right font-medium">{t("admin.calls")}</th>
                  <th className="pb-2 pr-4 text-right font-medium">{t("admin.tokens")}</th>
                  <th className="pb-2 text-right font-medium">{t("admin.cost")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {agents.map(([name, row]) => (
                  <tr key={name}>
                    <td className="py-2 pr-4 font-mono text-xs text-ink/90">
                      {name.replace(/_/g, " ")}
                    </td>
                    <td className="py-2 pr-4 text-right font-mono tnum text-muted">
                      {n(row.calls ?? null, 0)}
                    </td>
                    <td className="py-2 pr-4 text-right font-mono tnum text-ink/90">
                      {n(row.tokens ?? null, 0)}
                    </td>
                    <td className="py-2 text-right font-mono tnum text-muted">
                      {n(row.cost ?? null, 2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {usage.note && <Caveat>{usage.note}</Caveat>}
    </Card>
  );
}

function Queue() {
  const { t, n, dateTime } = useI18n();
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<string>("");

  const stats = useQuery({
    queryKey: ["admin-queue"],
    queryFn: async () => {
      const { data, error } = await api.GET("/admin/queue");
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data;
    },
    // The queue is the one panel where a stale number is actively misleading,
    // so it refreshes on its own.
    refetchInterval: 15_000,
  });

  const jobs = useQuery({
    queryKey: ["admin-jobs", statusFilter],
    queryFn: async () => {
      const { data, error } = await api.GET("/jobs", {
        params: {
          query: statusFilter
            ? { status: statusFilter as "pending", limit: 50 }
            : { limit: 50 },
        },
      });
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data ?? [];
    },
    refetchInterval: 15_000,
  });

  const leader = stats.data?.scheduler_leader;
  const statuses = Object.keys(stats.data?.by_status ?? {});

  return (
    <div className="space-y-4">
      {stats.isError ? (
        <ErrorNote message={(stats.error as Error).message} onRetry={() => stats.refetch()} />
      ) : stats.isLoading ? (
        <Loading />
      ) : (
        <>
          <Card title={t("admin.queue.depth")}>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-5">
              {Object.entries(stats.data?.by_status ?? {}).map(([status, count]) => (
                <Stat
                  key={status}
                  label={status}
                  value={n(count as number, 0)}
                  tone={status === "dead" && (count as number) > 0 ? "fall" : "neutral"}
                />
              ))}
            </dl>
            {stats.data?.note && <Caveat>{stats.data.note}</Caveat>}
          </Card>

          <Card title={t("admin.queue.leader")}>
            {leader ? (
              <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3">
                {Object.entries(leader).map(([key, value]) => (
                  <Stat key={key} label={key.replace(/_/g, " ")} value={String(value)} />
                ))}
              </dl>
            ) : (
              <div>
                <p className="text-sm text-fall/90">{t("admin.queue.noLeader")}</p>
                <Caveat>{t("admin.queue.noLeaderWarning")}</Caveat>
              </div>
            )}
          </Card>

          <Card title={t("admin.queue.types")}>
            <div className="flex flex-wrap gap-1.5">
              {(stats.data?.registered_job_types ?? []).map((type) => (
                <span
                  key={type}
                  className="rounded border border-line px-2 py-0.5 font-mono text-xs text-muted"
                >
                  {type}
                </span>
              ))}
            </div>
          </Card>
        </>
      )}

      <Card
        title={t("admin.jobs")}
        action={
          <select
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
            className="rounded-md border border-line bg-surface px-2 py-1 text-xs text-ink"
          >
            <option value="">{t("admin.job.filterAll")}</option>
            {statuses.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
        }
      >
        {jobs.isLoading ? (
          <Loading />
        ) : jobs.isError ? (
          <ErrorNote message={(jobs.error as Error).message} onRetry={() => jobs.refetch()} />
        ) : !jobs.data?.length ? (
          <Empty message={t("admin.jobsEmpty")} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs text-faint">
                  <th className="pb-2 pr-4 font-medium">{t("admin.job.type")}</th>
                  <th className="pb-2 pr-4 font-medium">{t("admin.job.status")}</th>
                  <th className="pb-2 pr-4 text-right font-medium">{t("admin.job.retries")}</th>
                  <th className="pb-2 pr-4 font-medium">{t("admin.job.created")}</th>
                  <th className="pb-2 font-medium">{t("admin.job.error")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {jobs.data.map((job) => (
                  <tr key={job.id}>
                    <td className="py-2 pr-4 font-mono text-xs text-ink/90">{job.job_type}</td>
                    <td className="py-2 pr-4">
                      <span
                        className={`font-mono text-xs ${
                          job.status === "dead"
                            ? "text-fall"
                            : job.status === "succeeded"
                              ? "text-rise"
                              : job.status === "failed"
                                ? "text-watch"
                                : "text-muted"
                        }`}
                      >
                        {job.status}
                      </span>
                    </td>
                    <td className="py-2 pr-4 text-right font-mono text-xs tnum text-muted">
                      {job.retry_count}/{job.max_retries}
                    </td>
                    <td className="py-2 pr-4 text-xs text-faint">{dateTime(job.created_at)}</td>
                    <td className="max-w-md py-2 text-xs text-muted">
                      {/* Truncated, not hidden: a dead job's reason is the
                          whole point of listing it, but a stack trace would
                          push every other row off the screen. */}
                      <span className="line-clamp-2" title={job.last_error ?? ""}>
                        {job.last_error ?? "—"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            queryClient.invalidateQueries({ queryKey: ["admin-queue"] });
            queryClient.invalidateQueries({ queryKey: ["admin-jobs"] });
          }}
        >
          {t("common.retry")}
        </Button>
      </div>
    </div>
  );
}

function Providers() {
  const { t } = useI18n();
  const query = useQuery({
    queryKey: ["admin-providers"],
    queryFn: async () => {
      const { data, error } = await api.GET("/providers");
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data;
    },
  });

  if (query.isLoading) return <Loading />;
  if (query.isError)
    return <ErrorNote message={(query.error as Error).message} onRetry={() => query.refetch()} />;

  const active = (query.data?.active ?? {}) as Record<string, string>;
  const registered = (query.data?.registered ?? {}) as Record<string, string[]>;

  return (
    <div className="space-y-4">
      <Card title={t("admin.providersActive")}>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
          {Object.entries(active).map(([kind, name]) => (
            <Stat key={kind} label={kind.replace(/_/g, " ")} value={name} />
          ))}
        </dl>
        <Caveat>{t("admin.providerNote")}</Caveat>
      </Card>

      <Card title={t("admin.providersRegistered")}>
        <div className="space-y-3">
          {Object.entries(registered).map(([kind, names]) => (
            <div key={kind}>
              <p className="mb-1.5 text-xs text-faint">{kind.replace(/_/g, " ")}</p>
              <div className="flex flex-wrap gap-1.5">
                {names.map((name) => (
                  <span
                    key={name}
                    className={`rounded border px-2 py-0.5 font-mono text-xs ${
                      active[kind] === name
                        ? "border-rise/40 bg-rise/10 text-rise"
                        : "border-line text-muted"
                    }`}
                  >
                    {name}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function Budget() {
  const { t, n, money, dateTime } = useI18n();
  const query = useQuery({
    queryKey: ["admin-budget"],
    queryFn: async () => {
      const { data, error } = await api.GET("/admin/budget");
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data;
    },
  });

  if (query.isLoading) return <Loading />;
  if (query.isError)
    return <ErrorNote message={(query.error as Error).message} onRetry={() => query.refetch()} />;

  const data = query.data;
  const utilisation = data?.utilisation ?? null;
  const tone =
    data?.state === "exceeded" ? "fall" : data?.state === "warning" ? "watch" : "rise";

  return (
    <Card>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
        <Stat label={t("admin.budget.spent")} value={money(data?.spent)} />
        <Stat
          label={t("admin.budget.ceiling")}
          value={data?.ceiling ? money(data.ceiling) : t("admin.budget.noCeiling")}
        />
        <Stat
          label={t("admin.budget.utilisation")}
          value={utilisation === null ? "—" : `${n(utilisation * 100, 1)}%`}
          tone={tone === "fall" ? "fall" : "neutral"}
        />
        <Stat label={t("admin.budget.windowStart")} value={dateTime(data?.window_start)} mono={false} />
      </dl>

      {utilisation !== null && (
        <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-surface">
          <div
            className={`h-full rounded-full ${
              tone === "fall" ? "bg-fall" : tone === "watch" ? "bg-watch" : "bg-rise"
            }`}
            style={{ width: `${Math.max(0, Math.min(1, utilisation)) * 100}%` }}
          />
        </div>
      )}

      {data?.message && <Caveat>{data.message}</Caveat>}
    </Card>
  );
}

function AuditLog() {
  const { t, dateTime } = useI18n();
  const [entity, setEntity] = useState("");

  const query = useQuery({
    queryKey: ["admin-audit", entity],
    queryFn: async () => {
      const { data, error } = await api.GET("/audit-logs", {
        params: { query: entity ? { entity, limit: 100 } : { limit: 100 } },
      });
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data ?? [];
    },
  });

  return (
    <Card
      title={t("admin.tab.audit")}
      action={
        <input
          value={entity}
          onChange={(event) => setEntity(event.target.value)}
          placeholder={t("admin.audit.filterEntity")}
          className="rounded-md border border-line bg-surface px-2 py-1 text-xs text-ink placeholder:text-faint"
        />
      }
    >
      {query.isLoading ? (
        <Loading />
      ) : query.isError ? (
        <ErrorNote message={(query.error as Error).message} onRetry={() => query.refetch()} />
      ) : !query.data?.length ? (
        <Empty message={t("admin.audit.empty")} />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs text-faint">
                <th className="pb-2 pr-4 font-medium">{t("admin.audit.when")}</th>
                <th className="pb-2 pr-4 font-medium">{t("admin.audit.actor")}</th>
                <th className="pb-2 pr-4 font-medium">{t("admin.audit.action")}</th>
                <th className="pb-2 pr-4 font-medium">{t("admin.audit.entity")}</th>
                <th className="pb-2 font-medium">{t("admin.audit.changes")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {query.data.map((entry) => (
                <tr key={entry.id}>
                  <td className="py-2 pr-4 whitespace-nowrap text-xs text-faint">
                    {dateTime(entry.created_at)}
                  </td>
                  <td className="py-2 pr-4 font-mono text-xs text-muted">{entry.actor_type}</td>
                  <td className="py-2 pr-4 font-mono text-xs text-ink/90">{entry.action}</td>
                  <td className="py-2 pr-4 font-mono text-xs text-muted">{entry.entity}</td>
                  <td className="py-2 text-xs text-faint">
                    {entry.before || entry.after ? (
                      <span className="font-mono">
                        {JSON.stringify(entry.before)} → {JSON.stringify(entry.after)}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

export type { Tab as AdminTab, MessageKey };
