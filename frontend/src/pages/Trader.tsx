import { Link } from "react-router-dom";
import { useI18n } from "@/i18n/context";
import { Card, Button, Empty } from "@/components/primitives";
import { OriginBadge, PanelBody } from "@/trader/components";
import { traderApi } from "@/trader/client";
import { useTraderQuery } from "@/trader/hooks";
import { KillControls } from "@/trader/KillControls";
import { useAcknowledge } from "@/trader/mutations";
import type { Dashboard, Limits, Reconciliation, TradingEvent } from "@/trader/types";

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

      <OpenOrders query={dashboard} />

      <div className="grid gap-6 lg:grid-cols-2">
        <LimitsPanel />
        <ReconciliationPanel />
      </div>

      <EventsPanel />
    </div>
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
                <thead className="text-xs text-faint">
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
            <p className="text-xs text-faint">{t("trader.limits.unsetNote")}</p>
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
                <span className="ml-2 text-xs text-faint">{dateTime(data.runs[0].started_at)}</span>
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
                        e.severity === "CRITICAL" ? "text-fall" : e.severity === "WARN" ? "text-watch" : "text-faint"
                      }`}
                    >
                      {t(`trader.sev.${e.severity}`)}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-ink">{e.message}</p>
                      <p className="text-xs text-faint">
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
