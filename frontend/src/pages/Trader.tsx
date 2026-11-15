import { useState } from "react";
import { Link } from "react-router-dom";
import { useI18n } from "@/i18n/context";
import { Card, Button, Empty } from "@/components/primitives";
import { OriginBadge, PanelBody } from "@/trader/components";
import { traderApi, TraderError } from "@/trader/client";
import { groupDigits } from "@/trader/format";
import { useTraderQuery } from "@/trader/hooks";
import { KillControls } from "@/trader/KillControls";
import { exportTraderCsv, useAcknowledge } from "@/trader/mutations";
import type {
  Dashboard,
  LedgerEntry,
  Limits,
  OriginPortfolio,
  Portfolio,
  Reconciliation,
  TradingEvent,
} from "@/trader/types";

/**
 * The operator's overview: what state is the Trader in, what is it holding open,
 * what has it refused to do, and the means to stop it.
 *
 * Deliberately not a trading terminal (docs/04-UX-UI/00): there is no order
 * ticket and no chart. The first thing on the page is the stop controls, because
 * the page exists to approve, observe, and stop.
 */
export function Trader() {
  const { t } = useI18n();
  const dashboard = useTraderQuery<Dashboard>(["dashboard"], () =>
    traderApi.GET("/trader/v1/dashboard"),
  );

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-lg font-semibold text-ink">{t("trader.title")}</h1>
        <p className="mt-1 max-w-prose text-sm text-muted">{t("trader.subtitle")}</p>
      </header>

      <Card title={t("trader.section.controls")}>
        <KillControls
          state={dashboard.data?.data.trading_state ?? "RUNNING"}
          openOrderCount={dashboard.data ? dashboard.data.data.open_orders.length : null}
        />
      </Card>

      <PortfolioPanels />

      <OpenOrders query={dashboard} />

      <div className="grid gap-6 lg:grid-cols-2">
        <LimitsPanel />
        <ReconciliationPanel />
      </div>

      <LedgerAndExportPanel />

      <EventsPanel />
    </div>
  );
}

export function OriginPortfolioBlock({ data }: { data: OriginPortfolio }) {
  const { t, locale } = useI18n();
  const idr = (v: string | null) => (v === null ? "-" : `Rp ${groupDigits(v, locale)}`);
  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
        {data.start_equity_idr !== null && (
          <div>
            <dt className="text-xs text-muted">{t("trader.portfolio.startEquity")}</dt>
            <dd className="mt-0.5 flex items-center gap-1.5 font-mono text-xs tnum text-ink">
              {idr(data.start_equity_idr)}
              <OriginBadge origin={data.origin} />
            </dd>
          </div>
        )}
        <div>
          <dt className="text-xs text-muted">{t("trader.portfolio.latestEquity")}</dt>
          <dd className="mt-0.5 flex items-center gap-1.5 font-mono text-xs tnum text-ink">
            {idr(data.latest_equity_idr)}
            <OriginBadge origin={data.origin} />
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">{t("trader.portfolio.realisedPnl")}</dt>
          <dd className="mt-0.5 flex items-center gap-1.5 font-mono text-xs tnum text-ink">
            {idr(data.realised_pnl_idr)}
            <OriginBadge origin={data.origin} />
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">{t("trader.portfolio.drawdown")}</dt>
          <dd className="mt-0.5 flex items-center gap-1.5 font-mono text-xs tnum text-ink">
            {data.drawdown_pct === null ? "-" : `${data.drawdown_pct}%`}
            <OriginBadge origin={data.origin} />
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">{t("trader.portfolio.dailyLoss")}</dt>
          <dd className="mt-0.5 flex items-center gap-1.5 font-mono text-xs tnum text-ink">
            {idr(data.daily_loss_idr)}
            <OriginBadge origin={data.origin} />
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">{t("trader.portfolio.closedTrades")}</dt>
          <dd className="mt-0.5 flex items-center gap-1.5 font-mono text-xs tnum text-ink">
            {data.trades_closed}
            <OriginBadge origin={data.origin} />
          </dd>
        </div>
      </dl>

      {data.positions.length === 0 ? (
        <p className="text-xs text-muted">{t("trader.portfolio.noPositions")}</p>
      ) : (
        <div className="-mx-4 overflow-x-auto px-4">
          <table className="w-full min-w-[32rem] text-left text-sm">
            <thead className="text-xs text-muted">
              <tr>
                <th className="pb-2 pr-3 font-medium">{t("trader.portfolio.col.pair")}</th>
                <th className="pb-2 pr-3 font-medium">{t("trader.portfolio.col.qty")}</th>
                <th className="pb-2 pr-3 font-medium">{t("trader.portfolio.col.avgCost")}</th>
                <th className="pb-2 pr-3 font-medium">{t("trader.portfolio.col.costBasis")}</th>
                <th className="pb-2 pr-3 font-medium">{t("trader.portfolio.col.stop")}</th>
                <th className="pb-2 font-medium">{t("trader.portfolio.col.target")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {data.positions.map((p) => (
                <tr key={`${p.origin}-${p.pair}`}>
                  <td className="py-2 pr-3 font-mono">
                    {p.pair} <OriginBadge origin={p.origin} />
                  </td>
                  <td className="py-2 pr-3 font-mono tnum">{p.quantity}</td>
                  <td className="py-2 pr-3 font-mono tnum">{idr(p.avg_cost)}</td>
                  <td className="py-2 pr-3 font-mono tnum">{idr(p.cost_basis_idr)}</td>
                  <td className="py-2 pr-3 font-mono tnum">{idr(p.stop_price)}</td>
                  <td className="py-2 font-mono tnum">{idr(p.target_price)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function PortfolioPanels() {
  const { t } = useI18n();
  const query = useTraderQuery<Portfolio>(["portfolio"], () =>
    traderApi.GET("/trader/v1/portfolio"),
  );
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted">{t("trader.portfolio.noMixNote")}</p>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card
          title={
            <h2 className="flex items-center gap-2 text-sm font-medium text-ink">
              {t("trader.portfolio.liveTitle")}
              <OriginBadge origin="LIVE" />
            </h2>
          }
        >
          <PanelBody query={query}>
            {(data) => <OriginPortfolioBlock data={data.live} />}
          </PanelBody>
        </Card>
        <Card
          title={
            <h2 className="flex items-center gap-2 text-sm font-medium text-ink">
              {t("trader.portfolio.paperTitle")}
              <OriginBadge origin="PAPER" />
            </h2>
          }
        >
          <PanelBody query={query}>
            {(data) => <OriginPortfolioBlock data={data.paper} />}
          </PanelBody>
        </Card>
      </div>
    </div>
  );
}

function LedgerAndExportPanel() {
  const { t, dateTime, locale } = useI18n();
  const ledger = useTraderQuery<LedgerEntry[]>(["ledger"], () =>
    traderApi.GET("/trader/v1/ledger"),
  );
  const [busyKind, setBusyKind] = useState<"ledger" | "audit" | null>(null);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const runExport = async (kind: "ledger" | "audit") => {
    setBusyKind(kind);
    setStatusMsg(null);
    setErrorMsg(null);
    try {
      const start = "2020-01-01T00:00:00Z";
      const end = new Date(Date.now() + 86_400_000).toISOString();
      const { csv, rowCount } = await exportTraderCsv(kind, start, end);
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
      if (typeof URL.createObjectURL === "function") {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `trader-${kind}-${new Date().toISOString().slice(0, 10)}.csv`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      }
      setStatusMsg(t("trader.export.done", { kind, count: rowCount }));
    } catch (err) {
      setErrorMsg(err instanceof TraderError ? err.message : "Export failed.");
    } finally {
      setBusyKind(null);
    }
  };

  return (
    <Card
      title={t("trader.export.title")}
      action={
        <div className="flex flex-wrap gap-2">
          <Button
            variant="ghost"
            size="sm"
            busy={busyKind === "ledger"}
            disabled={busyKind !== null}
            onClick={() => void runExport("ledger")}
          >
            {busyKind === "ledger" ? t("trader.export.downloading") : t("trader.export.ledgerBtn")}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            busy={busyKind === "audit"}
            disabled={busyKind !== null}
            onClick={() => void runExport("audit")}
          >
            {busyKind === "audit" ? t("trader.export.downloading") : t("trader.export.auditBtn")}
          </Button>
        </div>
      }
    >
      <div role="status" aria-live="polite" className="mb-3">
        {statusMsg && <p className="text-xs text-rise">{statusMsg}</p>}
        {errorMsg && <p className="text-xs text-fall">{errorMsg}</p>}
      </div>
      <PanelBody query={ledger}>
        {(entries) =>
          entries.length === 0 ? (
            <Empty message={t("trader.export.emptyLedger")} />
          ) : (
            <div className="-mx-4 overflow-x-auto px-4">
              <table className="w-full min-w-[32rem] text-left text-sm">
                <thead className="text-xs text-muted">
                  <tr>
                    <th className="pb-2 pr-3 font-medium">{locale === "id" ? "Waktu" : "At"}</th>
                    <th className="pb-2 pr-3 font-medium">{locale === "id" ? "Asal" : "Origin"}</th>
                    <th className="pb-2 pr-3 font-medium">{locale === "id" ? "Jenis" : "Type"}</th>
                    <th className="pb-2 pr-3 font-medium">{locale === "id" ? "Aset" : "Asset"}</th>
                    <th className="pb-2 pr-3 font-medium">{locale === "id" ? "Jumlah" : "Amount"}</th>
                    <th className="pb-2 font-medium">{locale === "id" ? "Alasan" : "Reason"}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {entries.slice(0, 15).map((e, idx) => (
                    <tr key={`${e.at}-${e.asset}-${idx}`}>
                      <td className="py-1.5 pr-3 text-xs text-muted">{dateTime(e.at)}</td>
                      <td className="py-1.5 pr-3">
                        <OriginBadge origin={e.origin === "PAPER" ? "PAPER" : "LIVE"} />
                      </td>
                      <td className="py-1.5 pr-3 font-mono text-xs">{e.entry_type}</td>
                      <td className="py-1.5 pr-3 font-mono text-xs">{e.asset}</td>
                      <td className="py-1.5 pr-3 font-mono text-xs tnum">
                        {e.asset === "IDR" ? groupDigits(e.amount, locale) : e.amount}
                      </td>
                      <td className="py-1.5 text-xs text-muted">{e.reason ?? "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
      </PanelBody>
    </Card>
  );
}

function OpenOrders({ query }: { query: ReturnType<typeof useTraderQuery<Dashboard>> }) {
  const { t, dateTime } = useI18n();
  return (
    <Card
      title={t("trader.orders.title")}
      action={
        query.data && <OriginBadge origin={query.data.meta.origin} />
      }
    >
      <PanelBody query={query}>
        {(data) =>
          data.open_orders.length === 0 ? (
            <Empty
              message={t("trader.orders.empty")}
              hint={t("trader.orders.checked", { when: dateTime(new Date(query.dataUpdatedAt)) })}
            />
          ) : (
            <div className="-mx-4 overflow-x-auto px-4">
              <table className="w-full min-w-[32rem] text-left text-sm">
                <thead className="text-xs text-muted">
                  <tr>
                    <th className="pb-2 pr-3 font-medium">{t("trader.orders.pair")}</th>
                    <th className="pb-2 pr-3 font-medium">{t("trader.orders.side")}</th>
                    <th className="pb-2 pr-3 font-medium">{t("trader.orders.type")}</th>
                    <th className="pb-2 font-medium">{t("trader.orders.state")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {data.open_orders.map((o) => (
                    <tr key={o.client_order_id} className={o.state === "UNKNOWN" ? "bg-fall/5" : undefined}>
                      <td className="py-2 pr-3 font-mono">{o.pair}</td>
                      <td className="py-2 pr-3">{o.side}</td>
                      <td className="py-2 pr-3">{o.type}</td>
                      <td className="py-2">
                        <span className={o.state === "UNKNOWN" ? "font-medium text-fall" : ""}>
                          {o.state}
                        </span>
                        {o.state === "UNKNOWN" && (
                          <p className="mt-0.5 max-w-xs text-xs text-muted">{t("trader.orders.unknown")}</p>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
      </PanelBody>
      {query.data && query.data.data.approvals_pending.length > 0 && (
        <p className="mt-3 text-sm">
          <Link to="/trader/approvals" className="text-rise underline-offset-2 hover:underline">
            {t("nav.traderApprovals")} ({query.data.data.approvals_pending.length})
          </Link>
        </p>
      )}
    </Card>
  );
}

function LimitsPanel() {
  const { t } = useI18n();
  const query = useTraderQuery<Limits>(["limits"], () => traderApi.GET("/trader/v1/limits"));
  return (
    <Card title={t("trader.limits.title")}>
      <PanelBody query={query}>
        {(data) => (
          <div className="space-y-3">
            <p className="text-xs text-muted">{t("trader.limits.unsetNote")}</p>
            {data.unset.length === 0 ? (
              <p className="text-sm text-muted">{t("trader.limits.allSet")}</p>
            ) : null}
            <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1.5 text-sm">
              {/* Unset is shown as unset, never as 0 and never omitted. */}
              {[...Object.keys(data.limits ?? {}), ...data.unset.filter((k) => !(data.limits && k in data.limits))]
                .filter((name, i, all) => all.indexOf(name) === i)
                .map((name) => {
                  const value = data.limits?.[name] ?? null;
                  return (
                    <div key={name} className="contents">
                      <dt className="font-mono text-xs text-muted">{name}</dt>
                      <dd className={value === null ? "text-watch" : "font-mono tnum text-ink"}>
                        {value === null ? t("trader.limits.unset") : value}
                      </dd>
                    </div>
                  );
                })}
            </dl>
          </div>
        )}
      </PanelBody>
    </Card>
  );
}

function ReconciliationPanel() {
  const { t, dateTime } = useI18n();
  const query = useTraderQuery<Reconciliation>(["reconciliation"], () =>
    traderApi.GET("/trader/v1/reconciliation"),
  );
  return (
    <Card title={t("trader.recon.title")}>
      <PanelBody query={query}>
        {(data) =>
          data.runs.length === 0 ? (
            <Empty message={t("trader.recon.empty")} />
          ) : (
            <div className="space-y-3 text-sm">
              <p className={data.runs[0].result === "clean" ? "text-muted" : "font-medium text-fall"}>
                {t("trader.recon.last", { result: data.runs[0].result, count: data.runs[0].differences })}
                <span className="ml-2 text-xs text-muted">{dateTime(data.runs[0].started_at)}</span>
              </p>
              {data.unresolved.length > 0 && (
                <div>
                  <p className="mb-1 text-xs font-medium text-fall">{t("trader.recon.open")}</p>
                  <ul className="space-y-1 font-mono text-xs text-muted">
                    {data.unresolved.map((d) => (
                      <li key={`${d.kind}-${d.reference}`}>
                        {d.kind}: {d.reference}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )
        }
      </PanelBody>
    </Card>
  );
}

function EventsPanel() {
  const { t, dateTime } = useI18n();
  const query = useTraderQuery<TradingEvent[]>(["events"], () => traderApi.GET("/trader/v1/events"));
  const ack = useAcknowledge();
  return (
    <Card title={t("trader.events.title")}>
      <PanelBody query={query}>
        {(events) =>
          events.length === 0 ? (
            <Empty message={t("trader.events.empty")} />
          ) : (
            <ul className="divide-y divide-line">
              {events.map((e) => {
                const needsAck = e.severity === "CRITICAL" && !e.acked_at;
                return (
                  <li key={e.id} className="flex flex-wrap items-start gap-x-3 gap-y-1 py-2.5">
                    <span
                      className={`w-24 shrink-0 text-[0.65rem] font-semibold uppercase tracking-wide ${
                        e.severity === "CRITICAL" ? "text-fall" : e.severity === "WARN" ? "text-watch" : "text-muted"
                      }`}
                    >
                      {t(`trader.sev.${e.severity}`)}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-ink">{e.message}</p>
                      <p className="text-xs text-muted">
                        {dateTime(e.created_at)}
                        {e.severity === "CRITICAL" && (
                          <span className="ml-2">{e.acked_at ? t("trader.events.acked") : t("trader.events.needsAck")}</span>
                        )}
                      </p>
                    </div>
                    {needsAck && (
                      <Button
                        variant="ghost"
                        size="sm"
                        busy={ack.isPending && ack.variables?.id === e.id}
                        onClick={() => ack.mutate({ id: e.id })}
                      >
                        {t("trader.events.ack")}
                      </Button>
                    )}
                  </li>
                );
              })}
            </ul>
          )
        }
      </PanelBody>
    </Card>
  );
}
