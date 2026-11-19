import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useI18n, type MessageKey } from "@/i18n/context";
import { Button, Card, ConfirmDialog, Empty } from "@/components/primitives";
import { TabStrip } from "@/components/TabStrip";
import { OriginBadge, PanelBody } from "@/trader/components";
import { traderApi } from "@/trader/client";
import { roundDecimal, trimZeros } from "@/trader/format";
import { useTraderQuery } from "@/trader/hooks";
import { useDeleteStrategyDef, useSetStrategyPaper, useStartBacktests } from "@/trader/mutations";
import { StrategyBuilder, type BuilderStart } from "@/trader/StrategyBuilder";
import { StrategyCard } from "@/trader/StrategyCard";
import type {
  BacktestJob,
  Strategy,
  StrategyBacktests,
  StrategyDef,
  StrategyKind,
  StrategyPaper,
} from "@/trader/types";

const COMPARE = "__compare__";
const POLL_MS = 1500;

const pct = (v: string | null | undefined) => (v == null ? "-" : `${trimZeros(roundDecimal(v, 3))}%`);

/**
 * The strategies, one tab each, plus a comparison tab and the builder.
 *
 * Every number on these tabs is a BACKTEST: the stored candles replayed with the owner's paper
 * costs. Only the reference strategy runs in the paper loop today; a strategy built here is
 * tested, not traded, and the tab says so.
 */
export function StrategyWorkspace() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const defs = useTraderQuery<StrategyDef[]>(["strategy-defs"], () => traderApi.GET("/trader/v1/strategy-defs"));
  const kinds = useTraderQuery<StrategyKind[]>(
    ["strategy-kinds"],
    () => traderApi.GET("/trader/v1/strategy-kinds"),
    { interval: false },
  );
  const modes = useTraderQuery<Strategy[]>(["strategies"], () => traderApi.GET("/trader/v1/strategies"));
  const [tab, setTab] = useState<string>(COMPARE);
  const [builder, setBuilder] = useState<BuilderStart | null>(null);

  const start = useStartBacktests();
  const [jobId, setJobId] = useState<string | null>(null);
  const jobQuery = useTraderQuery<BacktestJob>(
    ["backtest-job", jobId ?? "none"],
    () =>
      traderApi.GET("/trader/v1/backtests/{job_id}", { params: { path: { job_id: jobId ?? "" } } }),
    { enabled: jobId !== null, interval: POLL_MS },
  );
  const job = jobQuery.data?.data;
  const running = start.isPending || (jobId !== null && (job === undefined || job.state === "RUNNING"));

  const state = job?.state;
  useEffect(() => {
    if (state === "DONE" || state === "FAILED") void queryClient.invalidateQueries({ queryKey: ["trader"] });
  }, [state, queryClient]);

  const run = (ids: string[] | null) =>
    start.mutate({ strategyIds: ids }, { onSuccess: (j) => setJobId(j.id) });

  return (
    <div className="space-y-4">
      <PanelBody query={defs}>
        {(list) => {
          const active = list.some((d) => d.id === tab) ? tab : COMPARE;
          return (
            <div className="space-y-4">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <TabStrip
                    label={t("trader.strat.tabs")}
                    active={active}
                    onChange={setTab}
                    tabs={[
                      { id: COMPARE, label: t("trader.strat.tab.compare") },
                      ...list.map((d) => ({ id: d.id, label: d.label || d.id })),
                    ]}
                  />
                </div>
                <Button
                  size="sm"
                  disabled={kinds.data === undefined}
                  onClick={() =>
                    kinds.data &&
                    setBuilder({ existing: false, id: "", label: "", kind: kinds.data.data[0]?.kind ?? "", params: {} })
                  }
                >
                  {t("trader.strat.new")}
                </Button>
              </div>

              <RunStatus job={job} running={running} error={start.error?.message ?? null} />

              {active === COMPARE ? (
                <CompareTab list={list} running={running} onRun={() => run(null)} onOpen={setTab} />
              ) : (
                (() => {
                  const def = list.find((d) => d.id === active);
                  return def ? (
                    <StrategyPanel
                      key={def.id}
                      def={def}
                      mode={modes.data?.data.find((m) => m.strategy_id === def.id)}
                      running={running}
                      onRun={() => run([def.id])}
                      onEdit={() =>
                        setBuilder({ existing: true, id: def.id, label: def.label, kind: def.kind, params: def.params })
                      }
                      onDuplicate={() =>
                        setBuilder({
                          existing: false,
                          id: "",
                          label: `${def.label || def.id} (copy)`,
                          kind: def.kind,
                          params: def.params,
                        })
                      }
                      onDeleted={() => setTab(COMPARE)}
                    />
                  ) : null;
                })()
              )}
            </div>
          );
        }}
      </PanelBody>
      {builder && kinds.data && (
        <StrategyBuilder
          kinds={kinds.data.data}
          start={builder}
          onClose={() => setBuilder(null)}
          onSaved={(id) => {
            setBuilder(null);
            setTab(id);
          }}
        />
      )}
    </div>
  );
}

function RunStatus({ job, running, error }: { job: BacktestJob | undefined; running: boolean; error: string | null }) {
  const { t } = useI18n();
  let text: string | null = null;
  let bad = false;
  if (error) {
    text = error;
    bad = true;
  } else if (running) {
    text = t("trader.strat.run.running", {
      current: job?.current ?? "…",
      done: job?.done_strategies ?? 0,
      total: job?.strategy_ids.length ?? 0,
    });
  } else if (job?.state === "FAILED") {
    text = t("trader.strat.run.failed", { reason: job.error ?? "" });
    bad = true;
  } else if (job?.state === "DONE") {
    text = t("trader.strat.run.done", { count: job.results.length });
  }
  return (
    <div role="status" aria-live="polite" className="min-h-5">
      {text && <p className={`text-sm ${bad ? "text-fall" : "text-muted"}`}>{text}</p>}
    </div>
  );
}

function CompareTab({
  list,
  running,
  onRun,
  onOpen,
}: {
  list: StrategyDef[];
  running: boolean;
  onRun: () => void;
  onOpen: (id: string) => void;
}) {
  const { t, dateTime } = useI18n();
  return (
    <Card
      title={
        <h2 className="flex items-center gap-2 text-sm font-medium text-ink">
          {t("trader.strat.compare.title")}
          <OriginBadge origin="BACKTEST" />
        </h2>
      }
      action={
        <Button size="sm" busy={running} disabled={running || list.length === 0} onClick={onRun}>
          {t("trader.strat.run.all")}
        </Button>
      }
    >
      <p className="mb-4 max-w-prose text-sm text-muted">{t("trader.strat.compare.intro")}</p>
      {list.length === 0 ? (
        <Empty message={t("trader.strategies.empty")} />
      ) : (
        <div className="-mx-4 overflow-x-auto px-4">
          <table className="w-full min-w-[44rem] text-left text-sm">
            <thead className="text-xs text-muted">
              <tr>
                <th className="pb-2 pr-3 font-medium">{t("trader.strat.col.name")}</th>
                <th className="pb-2 pr-3 font-medium">{t("trader.strat.col.kind")}</th>
                <th className="pb-2 pr-3 font-medium">{t("trader.strat.col.version")}</th>
                <th className="pb-2 pr-3 font-medium">{t("trader.strat.col.paper")}</th>
                <th className="pb-2 pr-3 text-right font-medium">{t("trader.strat.col.return")}</th>
                <th className="pb-2 pr-3 text-right font-medium">{t("trader.strat.col.trades")}</th>
                <th className="pb-2 pr-3 text-right font-medium">{t("trader.strat.col.pairs")}</th>
                <th className="pb-2 font-medium">{t("trader.strat.col.ranAt")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {list.map((d) => (
                <tr key={d.id}>
                  <td className="py-2 pr-3">
                    <button
                      type="button"
                      className="font-mono text-ink underline-offset-2 hover:underline max-sm:min-h-11"
                      onClick={() => onOpen(d.id)}
                    >
                      {d.label || d.id}
                    </button>
                  </td>
                  <td className="py-2 pr-3 text-xs text-muted">{t(`trader.strat.kind.${d.kind}` as MessageKey)}</td>
                  <td className="py-2 pr-3 font-mono text-xs text-muted">{d.version?.slice(-12) ?? "-"}</td>
                  <td className="py-2 pr-3 text-xs text-muted">
                    {d.legacy
                      ? t("trader.strat.paper.follows")
                      : d.paper_enabled
                        ? t("trader.strat.paper.yes")
                        : t("trader.strat.paper.no")}
                  </td>
                  <td className="py-2 pr-3 text-right font-mono tnum">{pct(d.backtest_return_pct)}</td>
                  <td className="py-2 pr-3 text-right font-mono tnum">{d.backtest_pairs ? d.backtest_trades : "-"}</td>
                  <td className="py-2 pr-3 text-right font-mono tnum">{d.backtest_pairs || "-"}</td>
                  <td className="py-2 text-xs text-muted">
                    {d.backtest_ran_at ? dateTime(d.backtest_ran_at) : t("trader.strat.neverRun")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-4 max-w-prose text-xs text-muted">{t("trader.strat.compare.caveat")}</p>
    </Card>
  );
}

function StrategyPanel({
  def,
  mode,
  running,
  onRun,
  onEdit,
  onDuplicate,
  onDeleted,
}: {
  def: StrategyDef;
  mode: Strategy | undefined;
  running: boolean;
  onRun: () => void;
  onEdit: () => void;
  onDuplicate: () => void;
  onDeleted: () => void;
}) {
  const { t, dateTime } = useI18n();
  const del = useDeleteStrategyDef();
  const [confirm, setConfirm] = useState(false);
  const results = useTraderQuery<StrategyBacktests>(["strategy-backtests", def.id, def.version ?? ""], () =>
    traderApi.GET("/trader/v1/strategy-defs/{strategy_id}/backtests", {
      params: { path: { strategy_id: def.id } },
    }),
  );

  return (
    <div className="space-y-6">
      <Card
        title={
          <h2 className="flex flex-wrap items-center gap-2 text-sm font-medium text-ink">
            <span className="font-mono">{def.label || def.id}</span>
            <span className="rounded border border-line px-1.5 py-0.5 text-[0.65rem] font-semibold tracking-wide">
              {t(`trader.strat.kind.${def.kind}` as MessageKey)}
            </span>
          </h2>
        }
        action={
          <div className="flex flex-wrap gap-2">
            <Button size="sm" busy={running} disabled={running || def.error !== null} onClick={onRun}>
              {t("trader.strat.run.one")}
            </Button>
            {def.legacy ? (
              <Link
                to="/trader/parameters"
                className="inline-flex items-center rounded-md border border-line px-3 py-1.5 text-sm text-ink hover:bg-hover max-sm:min-h-11"
              >
                {t("trader.strat.editReference")}
              </Link>
            ) : (
              <Button size="sm" variant="ghost" onClick={onEdit}>
                {t("trader.strat.edit")}
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={onDuplicate}>
              {t("trader.strat.duplicate")}
            </Button>
            <Button size="sm" variant="danger" onClick={() => setConfirm(true)}>
              {t("common.delete")}
            </Button>
          </div>
        }
      >
        <p className="mb-3 max-w-prose text-sm text-muted">{t(`trader.strat.kind.${def.kind}.desc` as MessageKey)}</p>
        <p className="mb-4 text-xs text-muted">
          {def.legacy
            ? t("trader.strat.runsInPaper")
            : t("trader.strat.backtestOnly")}
        </p>
        {def.error && (
          <p role="alert" className="mb-3 text-sm text-fall">
            {def.error}
          </p>
        )}
        <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">{t("trader.strat.params")}</h3>
        <dl className="grid grid-cols-1 gap-x-8 gap-y-1 sm:grid-cols-2">
          {Object.entries(def.params).map(([name, value]) => (
            <div key={name} className="flex justify-between gap-4 border-b border-line py-1.5 text-sm">
              <dt className="font-mono text-xs text-muted">{name}</dt>
              <dd className="font-mono tnum text-ink">{value}</dd>
            </div>
          ))}
        </dl>
        {def.version && <p className="mt-3 font-mono text-xs text-muted">{def.version}</p>}
        {del.error && (
          <p role="alert" className="mt-3 text-sm text-fall">
            {del.error.message}
          </p>
        )}
      </Card>

      <PaperCard def={def} />

      <Card
        title={
          <h2 className="flex items-center gap-2 text-sm font-medium text-ink">
            {t("trader.strat.results")}
            <OriginBadge origin="BACKTEST" />
          </h2>
        }
      >
        <PanelBody query={results}>
          {(data) =>
            data.pairs.length === 0 ? (
              <Empty message={t("trader.strat.noResults")} />
            ) : (
              <div className="-mx-4 overflow-x-auto px-4">
                <table className="w-full min-w-[32rem] text-left text-sm">
                  <thead className="text-xs text-muted">
                    <tr>
                      <th className="pb-2 pr-3 font-medium">{t("trader.backtests.col.pair")}</th>
                      <th className="pb-2 pr-3 text-right font-medium">{t("trader.backtests.col.trades")}</th>
                      <th className="pb-2 pr-3 text-right font-medium">{t("trader.strat.col.wins")}</th>
                      <th className="pb-2 pr-3 text-right font-medium">{t("trader.backtests.col.return")}</th>
                      <th className="pb-2 pr-3 text-right font-medium">{t("trader.backtests.col.drawdown")}</th>
                      <th className="pb-2 font-medium">{t("trader.backtests.col.ranAt")}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {data.pairs.map((p) => (
                      <tr key={p.pair}>
                        <td className="py-2 pr-3 font-mono">{p.pair}</td>
                        <td className="py-2 pr-3 text-right font-mono tnum">{p.trades}</td>
                        <td className="py-2 pr-3 text-right font-mono tnum">{p.wins}</td>
                        <td className="py-2 pr-3 text-right font-mono tnum">{pct(p.total_return_pct)}</td>
                        <td className="py-2 pr-3 text-right font-mono tnum">{pct(p.max_drawdown_pct)}</td>
                        <td className="py-2 text-xs text-muted">{dateTime(p.ran_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          }
        </PanelBody>
      </Card>

      {def.legacy && mode && <StrategyCard strategy={mode} />}

      {confirm && (
        <ConfirmDialog
          title={t("trader.strat.deleteTitle")}
          message={t(def.legacy ? "trader.strat.deleteReference" : "trader.strat.deleteConfirm", {
            name: def.label || def.id,
          })}
          confirmLabel={t("common.delete")}
          destructive
          busy={del.isPending}
          onCancel={() => setConfirm(false)}
          onConfirm={() =>
            del.mutate(
              { id: def.id },
              {
                onSuccess: onDeleted,
                onSettled: () => setConfirm(false),
              },
            )
          }
        />
      )}
    </div>
  );
}

function PaperCard({ def }: { def: StrategyDef }) {
  const { t } = useI18n();
  const paper = useTraderQuery<StrategyPaper>(["strategy-paper", def.id], () =>
    traderApi.GET("/trader/v1/strategy-defs/{strategy_id}/paper", {
      params: { path: { strategy_id: def.id } },
    }),
  );
  const toggle = useSetStrategyPaper();
  const [confirm, setConfirm] = useState(false);
  const name = def.label || def.id;
  return (
    <Card
      title={
        <h2 className="flex items-center gap-2 text-sm font-medium text-ink">
          {t("trader.strat.paper.title")}
          <OriginBadge origin="PAPER" />
        </h2>
      }
    >
      <p className="mb-4 max-w-prose text-sm text-muted">{t("trader.strat.paper.intro")}</p>
      <PanelBody query={paper}>
        {(data) => (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-3">
              <p className="text-sm font-medium text-ink">
                {def.legacy
                  ? t("trader.strat.paper.reference")
                  : data.enabled
                    ? t("trader.strat.paper.on")
                    : t("trader.strat.paper.off")}
              </p>
              {!def.legacy &&
                (data.enabled ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    busy={toggle.isPending}
                    onClick={() => toggle.mutate({ id: def.id, enabled: false })}
                  >
                    {t("trader.strat.paper.disable")}
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    busy={toggle.isPending}
                    disabled={def.error !== null}
                    onClick={() => setConfirm(true)}
                  >
                    {t("trader.strat.paper.enable")}
                  </Button>
                ))}
            </div>
            <p className="text-sm text-ink">
              {data.owned_pairs.length > 0
                ? t("trader.strat.paper.owned", { pairs: data.owned_pairs.join(", ") })
                : t("trader.strat.paper.none")}
            </p>
            {data.claimed_pairs.length > 0 && (
              <p className="text-sm text-muted">
                {t("trader.strat.paper.claimed", { pairs: data.claimed_pairs.join(", ") })}
              </p>
            )}
            <p className="font-mono text-sm tnum text-ink">
              {data.stats.trades === 0
                ? t("trader.strat.paper.noStats")
                : t("trader.strat.paper.stats", {
                    trades: data.stats.trades,
                    wins: data.stats.wins,
                    pnl: trimZeros(roundDecimal(data.stats.pnl_idr, 2)),
                    drawdown: pct(data.stats.drawdown_pct),
                  })}
            </p>
            {!def.legacy && (
              <p className="text-xs text-muted">
                {t("trader.strat.paper.disableNote")} {t("trader.strat.paper.limit", { max: data.max_enabled })}
              </p>
            )}
            {toggle.error && (
              <p role="alert" className="text-sm text-fall">
                {toggle.error.message}
              </p>
            )}
          </div>
        )}
      </PanelBody>
      {confirm && (
        <ConfirmDialog
          title={t("trader.strat.paper.enableTitle")}
          message={t("trader.strat.paper.enableConfirm", { name })}
          confirmLabel={t("trader.strat.paper.enable")}
          busy={toggle.isPending}
          onCancel={() => setConfirm(false)}
          onConfirm={() =>
            toggle.mutate({ id: def.id, enabled: true }, { onSettled: () => setConfirm(false) })
          }
        />
      )}
    </Card>
  );
}
