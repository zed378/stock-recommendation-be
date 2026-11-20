import { useEffect, useMemo, useState } from "react";
import { useI18n, type MessageKey } from "@/i18n/context";
import { Button, Card, Empty, Field, inputClass } from "@/components/primitives";
import { TabStrip } from "@/components/TabStrip";
import { PanelBody } from "@/trader/components";
import { traderApi } from "@/trader/client";
import { useTraderQuery } from "@/trader/hooks";
import { useRunSignals, useSaveSignalsConfig } from "@/trader/mutations";
import { StepUpDialog } from "@/trader/StepUpDialog";
import {
  bodyFrom,
  formFrom,
  H4_STRATEGIES,
  HORIZON_ORDER,
  loosensSignals,
  sameForm,
  type SignalsForm,
} from "@/trader/signalsForm";
import type {
  SignalAck,
  SignalCandidate,
  SignalCandidates,
  SignalsConfig,
  SignalsStatus,
  SignalTradeSummary,
  SignalTrades,
} from "@/trader/types";

type Tab = "settings" | "qualified" | "history" | "h4" | "receiver";
const PAGE = 50;
const KINDS = ["SCHEDULED", "MANUAL", "H4", "H4MANUAL"];

const pct = (ratio: string) => `${Math.round(Number(ratio) * 100)}%`;
const words = (key: string) => key.replace(/_/g, " ");

/**
 * The crypto signal worker, from the operator's side (ADR-066): its settings (kept in the database
 * and changed here, never in a file), what it found, and what the receiving client answered.
 *
 * Nothing on this screen can place an order. In SHADOW the worker only records; in PUBLISH it hands
 * signals to the receiving client, which decides under its own settings, and every change that makes
 * the worker act more readily asks for the password.
 */
export function TraderSignals() {
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>("settings");
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-ink">{t("trader.signals.title")}</h1>
        <p className="mt-1 max-w-prose text-sm text-muted">{t("trader.signals.intro")}</p>
        <p className="mt-1 max-w-prose text-xs text-muted">{t("trader.signals.caveat")}</p>
      </div>
      <StatusCard />
      <TabStrip
        label={t("trader.signals.tabs")}
        active={tab}
        onChange={setTab}
        tabs={[
          { id: "settings", label: t("trader.signals.tab.settings") },
          { id: "qualified", label: t("trader.signals.tab.qualified") },
          { id: "history", label: t("trader.signals.tab.history") },
          { id: "h4", label: t("trader.signals.tab.h4") },
          { id: "receiver", label: t("trader.signals.tab.receiver") },
        ]}
      />
      {tab === "settings" && <SettingsTab />}
      {tab === "qualified" && <CandidateList meets key="qualified" />}
      {tab === "history" && <CandidateList key="history" />}
      {tab === "h4" && <H4Tab />}
      {tab === "receiver" && <ReceiverTab />}
    </div>
  );
}

function ModeBadge({ mode }: { mode: string }) {
  const { t } = useI18n();
  return (
    <span className="rounded border border-line px-1.5 py-0.5 text-[0.65rem] font-semibold tracking-wide">
      {t(`trader.signals.mode.${mode === "PUBLISH" ? "PUBLISH" : "SHADOW"}` as MessageKey)}
    </span>
  );
}

function StatusCard() {
  const { t, dateTime } = useI18n();
  const status = useTraderQuery<SignalsStatus>(["signals", "status"], () => traderApi.GET("/trader/v1/signals/status"));
  const config = useTraderQuery<SignalsConfig>(["signals", "config"], () => traderApi.GET("/trader/v1/signals/config"));
  const run = useRunSignals();
  return (
    <Card title={<h2 className="text-sm font-medium text-ink">{t("trader.signals.status.title")}</h2>}>
      <PanelBody query={status}>
        {(s) => {
          const last = s.last_scan;
          const missing = config.data?.data.unset ?? [];
          const canRun = s.enabled && s.ready && !s.run_pending;
          return (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-3">
                <ModeBadge mode={s.mode} />
                <Button size="sm" busy={run.isPending} disabled={!canRun} onClick={() => run.mutate()}>
                  {t("trader.signals.run")}
                </Button>
              </div>
              {!s.enabled && <p className="text-sm text-muted">{t("trader.signals.status.off")}</p>}
              {s.enabled && !s.ready && (
                <p className="text-sm text-watch">
                  {t("trader.signals.status.unset", { fields: missing.join(", ") || "-" })}
                </p>
              )}
              <p className="text-sm text-ink">
                {last
                  ? t("trader.signals.status.last", {
                      when: dateTime(last.started_at),
                      kind: t(`trader.signals.kind.${KINDS.includes(last.kind) ? last.kind : "SCHEDULED"}` as MessageKey),
                      mode: last.mode,
                      signals: last.signals,
                      calls: last.ai_calls,
                    })
                  : t("trader.signals.status.never")}
              </p>
              {last && last.errors.length > 0 && (
                <p className="text-xs text-watch">{t("trader.signals.status.errors", { errors: last.errors.join("; ") })}</p>
              )}
              {s.stale && <p role="alert" className="text-sm text-fall">{t("trader.signals.status.stale")}</p>}
              <div role="status" aria-live="polite" className="text-sm">
                {s.run_pending && <p className="text-muted">{t("trader.signals.status.pending")}</p>}
                {run.isSuccess && !s.run_pending && <p className="text-muted">{t("trader.signals.runQueued")}</p>}
                {run.error && <p className="text-fall">{run.error.message}</p>}
              </div>
            </div>
          );
        }}
      </PanelBody>
    </Card>
  );
}

const H4_FIELDS: ReadonlyArray<
  readonly [
    "donchianN" | "volPeriod" | "volMult" | "rangeMult" | "minScore" | "maxHold" | "fee" | "slip" | "drift",
    MessageKey,
    "numeric" | "decimal",
  ]
> = [
  ["donchianN", "trader.signals.f.h4.donchianN", "numeric"],
  ["volPeriod", "trader.signals.f.h4.volPeriod", "numeric"],
  ["volMult", "trader.signals.f.h4.volMult", "decimal"],
  ["rangeMult", "trader.signals.f.h4.rangeMult", "decimal"],
  ["minScore", "trader.signals.f.h4.minScore", "numeric"],
  ["maxHold", "trader.signals.f.h4.maxHold", "numeric"],
  ["fee", "trader.signals.f.h4.fee", "decimal"],
  ["slip", "trader.signals.f.h4.slip", "decimal"],
  ["drift", "trader.signals.f.h4.drift", "decimal"],
];

function SettingsTab() {
  const query = useTraderQuery<SignalsConfig>(
    ["signals", "config"],
    () => traderApi.GET("/trader/v1/signals/config"),
    { interval: false },
  );
  return (
    <Card>
      <PanelBody query={query}>{(config) => <SettingsForm key={config.updated_at ?? "new"} config={config} />}</PanelBody>
    </Card>
  );
}

function SettingsForm({ config }: { config: SignalsConfig }) {
  const { t, dateTime } = useI18n();
  const save = useSaveSignalsConfig();
  const initial = useMemo(() => formFrom(config), [config]);
  const [form, setForm] = useState<SignalsForm>(initial);
  const [stepUp, setStepUp] = useState(false);
  const [saved, setSaved] = useState(false);
  useEffect(() => setForm(initial), [initial]);

  const set = <K extends keyof SignalsForm>(key: K, value: SignalsForm[K]) => {
    setSaved(false);
    setForm((f) => ({ ...f, [key]: value }));
  };
  const changed = !sameForm(form, initial);
  const needsPassword = changed && loosensSignals(config, form);
  const publishUnconfirmed = form.mode === "PUBLISH" && config.settings.mode !== "PUBLISH" && !form.confirmPublish;

  const send = (grant?: string) =>
    save.mutate(
      { values: bodyFrom(form), stepUp: grant },
      {
        onSuccess: () => {
          setSaved(true);
          setStepUp(false);
        },
        onError: (e) => {
          // The server is the judge: if it wants a password the screen did not predict, ask now.
          if (e.code === "step_up_required" && !grant) setStepUp(true);
          else setStepUp(false);
        },
      },
    );

  const setH4 = (patch: Partial<SignalsForm["h4"]>) => {
    setSaved(false);
    setForm((f) => ({ ...f, h4: { ...f.h4, ...patch } }));
  };

  const toggleHorizon = (h: string) =>
    set("horizons", form.horizons.includes(h) ? form.horizons.filter((x) => x !== h) : [...form.horizons, h]);

  return (
    <form
      className="space-y-5"
      onSubmit={(e) => {
        e.preventDefault();
        if (!changed || publishUnconfirmed) return;
        if (needsPassword) setStepUp(true);
        else send();
      }}
    >
      {config.unset.length > 0 && (
        <p className="text-sm text-watch" role="status">
          {t("trader.signals.f.unset", { fields: config.unset.join(", ") })}
        </p>
      )}
      <label className="flex min-h-9 items-center gap-3 text-sm text-ink max-sm:min-h-11">
        <input type="checkbox" className="h-4 w-4" checked={form.enabled} onChange={(e) => set("enabled", e.target.checked)} />
        {t("trader.signals.f.enabled")}
      </label>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("trader.signals.f.mode")} hint={t("trader.signals.f.publishNote")}>
          <select className={inputClass} value={form.mode} onChange={(e) => set("mode", e.target.value as SignalsForm["mode"])}>
            <option value="SHADOW">{t("trader.signals.mode.SHADOW")}</option>
            <option value="PUBLISH">{t("trader.signals.mode.PUBLISH")}</option>
          </select>
        </Field>
        <Field label={t("trader.signals.f.symbols")} hint={t("trader.signals.f.symbolsHint")}>
          <textarea
            className={`${inputClass} font-mono`}
            rows={2}
            spellCheck={false}
            value={form.symbols}
            onChange={(e) => set("symbols", e.target.value)}
          />
        </Field>
      </div>
      {form.mode === "PUBLISH" && config.settings.mode !== "PUBLISH" && (
        <label className="flex items-start gap-3 text-sm text-watch">
          <input
            type="checkbox"
            className="mt-1 h-4 w-4"
            checked={form.confirmPublish}
            onChange={(e) => set("confirmPublish", e.target.checked)}
          />
          {t("trader.signals.f.confirmPublish")}
        </label>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Field
          label={t("trader.signals.f.topN")}
          hint={t("trader.signals.f.topNHint", { default: config.default_top_n, max: config.max_top_n })}
        >
          <input className={`${inputClass} font-mono tnum`} inputMode="numeric" value={form.topN} onChange={(e) => set("topN", e.target.value)} />
        </Field>
        <Field label={t("trader.signals.f.minVolume")}>
          <input className={`${inputClass} font-mono tnum`} inputMode="decimal" value={form.minVolume} onChange={(e) => set("minVolume", e.target.value)} />
        </Field>
        <Field label={t("trader.signals.f.minRatio")} hint={t("trader.signals.f.minRatioHint")}>
          <input className={`${inputClass} font-mono tnum`} inputMode="decimal" value={form.minRatio} onChange={(e) => set("minRatio", e.target.value)} />
        </Field>
        <Field label={t("trader.signals.f.atrStop")}>
          <input className={`${inputClass} font-mono tnum`} inputMode="decimal" value={form.atrStop} onChange={(e) => set("atrStop", e.target.value)} />
        </Field>
        <Field label={t("trader.signals.f.aiMin")}>
          <input className={`${inputClass} font-mono tnum`} inputMode="numeric" value={form.aiMin} onChange={(e) => set("aiMin", e.target.value)} />
        </Field>
        <Field label={t("trader.signals.f.aiCalls")}>
          <input className={`${inputClass} font-mono tnum`} inputMode="numeric" value={form.aiCalls} onChange={(e) => set("aiCalls", e.target.value)} />
        </Field>
      </div>

      <fieldset className="space-y-2">
        <legend className="text-xs font-medium text-muted">{t("trader.signals.f.tp")}</legend>
        <div className="grid max-w-md grid-cols-3 gap-3">
          {(["tp1", "tp2", "tp3"] as const).map((k) => (
            <input
              key={k}
              aria-label={k.toUpperCase()}
              className={`${inputClass} font-mono tnum`}
              inputMode="decimal"
              value={form[k]}
              onChange={(e) => set(k, e.target.value)}
            />
          ))}
        </div>
        <p className="text-xs text-muted">{t("trader.signals.f.levelsNote")}</p>
      </fieldset>

      <fieldset className="space-y-2">
        <legend className="text-xs font-medium text-muted">{t("trader.signals.f.horizons")}</legend>
        <div className="flex flex-wrap gap-4">
          {HORIZON_ORDER.map((h) => (
            <label key={h} className="flex min-h-9 items-center gap-2 text-sm text-ink max-sm:min-h-11">
              <input type="checkbox" className="h-4 w-4" checked={form.horizons.includes(h)} onChange={() => toggleHorizon(h)} />
              <span className="font-mono">{h}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset className="space-y-4 border-t border-line pt-4">
        <legend className="text-sm font-medium text-ink">{t("trader.signals.f.h4.title")}</legend>
        <p className="max-w-prose text-xs text-muted">{t("trader.signals.f.h4.note")}</p>
        <label className="flex min-h-9 items-center gap-3 text-sm text-ink max-sm:min-h-11">
          <input type="checkbox" className="h-4 w-4" checked={form.h4.enabled} onChange={(e) => setH4({ enabled: e.target.checked })} />
          {t("trader.signals.f.h4.enabled")}
        </label>
        <div className="flex flex-wrap gap-4" role="group" aria-label={t("trader.signals.f.h4.strategies")}>
          {H4_STRATEGIES.map((x) => (
            <label key={x} className="flex min-h-9 items-center gap-2 text-sm text-ink max-sm:min-h-11">
              <input
                type="checkbox"
                className="h-4 w-4"
                checked={form.h4.strategies.includes(x)}
                onChange={() =>
                  setH4({
                    strategies: form.h4.strategies.includes(x)
                      ? form.h4.strategies.filter((y) => y !== x)
                      : [...form.h4.strategies, x],
                  })
                }
              />
              {t(`trader.signals.f.h4.strategy.${x}` as MessageKey)}
            </label>
          ))}
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {H4_FIELDS.map(([key, label, mode]) => (
            <Field key={key} label={t(label)}>
              <input
                className={`${inputClass} font-mono tnum`}
                inputMode={mode}
                value={form.h4[key]}
                onChange={(e) => setH4({ [key]: e.target.value })}
              />
            </Field>
          ))}
        </div>
        <label className="flex min-h-9 items-center gap-3 text-sm text-ink max-sm:min-h-11">
          <input type="checkbox" className="h-4 w-4" checked={form.h4.allowShort} onChange={(e) => setH4({ allowShort: e.target.checked })} />
          {t("trader.signals.f.h4.allowShort")}
        </label>
      </fieldset>

      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
        <Button type="submit" busy={save.isPending} disabled={!changed || publishUnconfirmed}>
          {t("trader.signals.save")}
        </Button>
        <p className="text-sm text-muted" role="status" aria-live="polite">
          {saved ? t("trader.signals.saved") : needsPassword ? t("trader.signals.stepUpNote") : !changed ? t("trader.signals.noChange") : ""}
        </p>
      </div>
      {save.error && !stepUp && (
        <p role="alert" className="text-sm text-fall">
          {save.error.message}
        </p>
      )}
      {config.updated_at && (
        <p className="text-xs text-muted">
          {t("trader.signals.updated", { when: dateTime(config.updated_at), who: config.updated_by ?? "-" })}
        </p>
      )}
      {stepUp && <StepUpDialog scope="RAISE_LIMIT" onCancel={() => setStepUp(false)} onGranted={(grant) => send(grant)} />}
    </form>
  );
}

type Group = {
  closed: number;
  win_rate: number | null;
  tp1_rate: number | null;
  mean_net_r: number | null;
  stderr_net_r: number | null;
  sum_net_r: number | null;
};

const fixed = (v: number | null | undefined, digits = 2) => (v === null || v === undefined ? "-" : v.toFixed(digits));
const share = (v: number | null | undefined) => (v === null || v === undefined ? "-" : `${Math.round(v * 100)}%`);
const FEW = 30;

function GroupTable({ title, groups }: { title: string; groups: Record<string, Group> }) {
  const { t } = useI18n();
  const rows = Object.entries(groups);
  if (rows.length === 0) return null;
  return (
    <div className="space-y-2">
      <h3 className="text-xs font-medium text-muted">{title}</h3>
      <div className="-mx-4 overflow-x-auto px-4">
        <table className="w-full min-w-[28rem] text-left text-sm">
          <thead className="text-xs text-muted">
            <tr>
              <th className="pb-2 pr-3 font-medium" />
              <th className="pb-2 pr-3 text-right font-medium">{t("trader.signals.h4.closed")}</th>
              <th className="pb-2 pr-3 text-right font-medium">{t("trader.signals.h4.winRate")}</th>
              <th className="pb-2 pr-3 text-right font-medium">{t("trader.signals.h4.tp1Rate")}</th>
              <th className="pb-2 text-right font-medium">{t("trader.signals.h4.meanR")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map(([name, g]) => (
              <tr key={name}>
                <td className="py-2 pr-3 font-mono text-xs">{name}</td>
                <td className="py-2 pr-3 text-right font-mono tnum">{g.closed}</td>
                <td className="py-2 pr-3 text-right font-mono tnum">{share(g.win_rate)}</td>
                <td className="py-2 pr-3 text-right font-mono tnum">{share(g.tp1_rate)}</td>
                <td className="py-2 text-right font-mono tnum">
                  {fixed(g.mean_net_r)}
                  {g.stderr_net_r !== null && g.stderr_net_r !== undefined ? ` ±${fixed(g.stderr_net_r)}` : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function H4Summary() {
  const { t } = useI18n();
  const query = useTraderQuery<SignalTradeSummary>(["signals", "h4", "summary"], () =>
    traderApi.GET("/trader/v1/signals/trades/summary"),
  );
  return (
    <Card title={<h2 className="text-sm font-medium text-ink">{t("trader.signals.h4.summary")}</h2>}>
      <PanelBody query={query}>
        {(d) => {
          if (d.total === 0) return <Empty message={t("trader.signals.h4.none")} />;
          const o = d.overall as unknown as Group;
          return (
            <div className="space-y-5">
              <p className="text-xs text-watch">{t("trader.signals.h4.caveat")}</p>
              <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                {(
                  [
                    ["trader.signals.h4.closed", String(o.closed)],
                    ["trader.signals.h4.winRate", share(o.win_rate)],
                    ["trader.signals.h4.tp1Rate", share(o.tp1_rate)],
                    [
                      "trader.signals.h4.meanR",
                      `${fixed(o.mean_net_r)}${o.stderr_net_r !== null && o.stderr_net_r !== undefined ? ` ±${fixed(o.stderr_net_r)}` : ""}`,
                    ],
                  ] as const
                ).map(([label, value]) => (
                  <div key={label}>
                    <dt className="text-xs text-muted">{t(label)}</dt>
                    <dd className="font-mono text-lg tnum text-ink">{value}</dd>
                  </div>
                ))}
              </dl>
              {o.closed < FEW && <p className="text-xs text-muted">{t("trader.signals.h4.few")}</p>}
              <p className="font-mono text-xs text-muted">
                {t("trader.signals.h4.states")}:{" "}
                {Object.entries(d.states)
                  .map(([k, v]) => `${t(`trader.signals.h4.state.${k}` as MessageKey)} ${v}`)
                  .join(", ")}
              </p>
              <GroupTable title={t("trader.signals.h4.byStrategy")} groups={d.by_strategy as unknown as Record<string, Group>} />
              <GroupTable title={t("trader.signals.h4.bySide")} groups={d.by_side as unknown as Record<string, Group>} />
              <GroupTable title={t("trader.signals.h4.byScore")} groups={d.by_score as unknown as Record<string, Group>} />
              <p className="text-xs text-muted">
                {t("trader.signals.h4.corr")}:{" "}
                {d.score_correlation === null
                  ? t("trader.signals.h4.corrWithheld", { n: d.correlation_min_closed })
                  : fixed(d.score_correlation)}
              </p>
            </div>
          );
        }}
      </PanelBody>
    </Card>
  );
}

function H4Tab() {
  const { t, dateTime } = useI18n();
  const [strategy, setStrategy] = useState("");
  const [state, setState] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const query = useTraderQuery<SignalTrades>(["signals", "h4", "trades", strategy, state, limit], () =>
    traderApi.GET("/trader/v1/signals/trades", {
      params: { query: { strategy: strategy || undefined, state: state || undefined, limit, offset: 0 } },
    }),
  );
  return (
    <div className="space-y-6">
      <H4Summary />
      <Card>
        <div className="mb-4 flex flex-wrap items-end gap-3">
          <Field label={t("trader.signals.h4.filter.strategy")}>
            <select className={inputClass} value={strategy} onChange={(e) => setStrategy(e.target.value)}>
              <option value="">{t("trader.signals.h4.filter.any")}</option>
              {H4_STRATEGIES.map((x) => (
                <option key={x} value={x}>
                  {t(`trader.signals.f.h4.strategy.${x}` as MessageKey)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t("trader.signals.h4.filter.state")}>
            <select className={inputClass} value={state} onChange={(e) => setState(e.target.value)}>
              <option value="">{t("trader.signals.h4.filter.any")}</option>
              {["PENDING", "CLOSED", "SKIPPED"].map((x) => (
                <option key={x} value={x}>
                  {t(`trader.signals.h4.state.${x}` as MessageKey)}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <PanelBody query={query}>
          {(d) =>
            d.items.length === 0 ? (
              <Empty message={t("trader.signals.h4.none")} />
            ) : (
              <div className="space-y-3">
                <div className="-mx-4 overflow-x-auto px-4">
                  <table className="w-full min-w-[44rem] text-left text-sm">
                    <thead className="text-xs text-muted">
                      <tr>
                        {(["coin", "strategy", "side", "score", "entry", "stop", "state", "outcome", "net", "when"] as const).map((c) => (
                          <th key={c} className="pb-2 pr-3 font-medium">
                            {t(`trader.signals.h4.col.${c}` as MessageKey)}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {d.items.map((x) => (
                        <tr key={x.id}>
                          <td className="py-2 pr-3 font-mono">{x.symbol}</td>
                          <td className="py-2 pr-3 text-xs">{x.strategy}</td>
                          <td className="py-2 pr-3 text-xs">{x.side}</td>
                          <td className="py-2 pr-3 font-mono tnum">{x.score}</td>
                          <td className="py-2 pr-3 font-mono tnum">{x.entry}</td>
                          <td className="py-2 pr-3 font-mono tnum">{x.stop}</td>
                          <td className="py-2 pr-3 text-xs">{t(`trader.signals.h4.state.${x.state}` as MessageKey)}</td>
                          <td className="py-2 pr-3 font-mono text-xs text-muted">{x.outcome ? words(x.outcome) : "-"}</td>
                          <td className="py-2 pr-3 font-mono tnum">{x.net_r === null ? "-" : fixed(Number(x.net_r))}</td>
                          <td className="py-2 text-xs text-muted">{dateTime(x.issued_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {d.items.length < d.total && (
                  <Button variant="ghost" size="sm" onClick={() => setLimit((n) => n + PAGE)}>
                    {t("trader.signals.h4.more")}
                  </Button>
                )}
              </div>
            )
          }
        </PanelBody>
      </Card>
    </div>
  );
}

function OutcomeText({ outcome }: { outcome: string }) {
  const { t } = useI18n();
  return <>{t(`trader.signals.outcome.${outcome}` as MessageKey)}</>;
}

function CandidateRow({ c }: { c: SignalCandidate }) {
  const { t, dateTime } = useI18n();
  const [open, setOpen] = useState(false);
  const ai = c.ai as { score?: number; verdict?: string; reasons?: string[]; risks?: string[] } | null;
  const horizons = Object.keys(c.met);
  return (
    <>
      <tr className="align-top">
        <td className="py-2 pr-3 font-mono">
          <button type="button" className="underline-offset-2 hover:underline max-sm:min-h-11" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            {c.symbol}
          </button>
        </td>
        <td className="py-2 pr-3 font-mono text-xs text-muted">{c.day}</td>
        <td className="py-2 pr-3 text-right font-mono tnum">{pct(c.score_ratio)}</td>
        <td className="py-2 pr-3 text-xs">
          <span className={c.meets_threshold ? "text-rise" : "text-muted"}>
            {c.meets_threshold ? "✓ " : "✗ "}
            <OutcomeText outcome={c.outcome} />
          </span>
        </td>
        <td className="py-2 pr-3 text-right font-mono tnum">{ai?.score ?? "-"}</td>
        <td className="py-2 pr-3 text-xs text-muted">{c.mode}</td>
        <td className="py-2 text-xs text-muted">{dateTime(c.scored_at)}</td>
      </tr>
      {open && (
        <tr>
          <td colSpan={7} className="space-y-3 pb-4">
            {horizons.map((h) => (
              <div key={h} className="text-xs">
                <p className="font-mono text-ink">{h}</p>
                <p className="text-muted">
                  {t("trader.signals.detail.met")}: {(c.met[h] ?? []).map(words).join(", ") || t("trader.signals.detail.none")}
                </p>
                <p className="text-muted">
                  {t("trader.signals.detail.notMet")}: {(c.not_met[h] ?? []).map(words).join(", ") || t("trader.signals.detail.none")}
                </p>
              </div>
            ))}
            {ai && (
              <div className="text-xs text-muted">
                <p className="text-ink">
                  {t("trader.signals.detail.ai")}: {ai.verdict} ({ai.score})
                </p>
                <p>
                  {t("trader.signals.detail.reasons")}: {(ai.reasons ?? []).join("; ") || t("trader.signals.detail.none")}
                </p>
                <p>
                  {t("trader.signals.detail.risks")}: {(ai.risks ?? []).join("; ") || t("trader.signals.detail.none")}
                </p>
              </div>
            )}
            {c.levels && (
              <p className="font-mono text-xs text-muted tnum">
                {t("trader.signals.detail.levels")}: {t("trader.signals.detail.entry")} {c.levels.entry}, {t("trader.signals.detail.stop")}{" "}
                {c.levels.stop}, TP {c.levels.tp1} / {c.levels.tp2} / {c.levels.tp3}
              </p>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

const OUTCOMES = [
  "SIGNAL", "BELOW_THRESHOLD", "INELIGIBLE", "NO_LEVELS", "AI_SKIP", "AI_BELOW_MIN", "AI_UNAVAILABLE", "AI_BUDGET", "ALREADY_DECIDED",
];

function CandidateList({ meets }: { meets?: boolean }) {
  const { t } = useI18n();
  const [filter, setFilter] = useState<"all" | "yes" | "no">(meets ? "yes" : "all");
  const [symbol, setSymbol] = useState("");
  const [outcome, setOutcome] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const meetsParam = meets ? true : filter === "all" ? undefined : filter === "yes";
  const query = useTraderQuery<SignalCandidates>(
    ["signals", "candidates", String(meetsParam), symbol, outcome, limit],
    () =>
      traderApi.GET("/trader/v1/signals/candidates", {
        params: { query: { meets: meetsParam, symbol: symbol.trim() || undefined, outcome: outcome || undefined, limit, offset: 0 } },
      }),
  );
  return (
    <Card>
      {!meets && (
        <div className="mb-4 flex flex-wrap items-end gap-3">
          <Field label={t("trader.signals.filter.meets")}>
            <select className={inputClass} value={filter} onChange={(e) => setFilter(e.target.value as "all" | "yes" | "no")}>
              <option value="all">{t("trader.signals.filter.all")}</option>
              <option value="yes">{t("trader.signals.filter.yes")}</option>
              <option value="no">{t("trader.signals.filter.no")}</option>
            </select>
          </Field>
          <Field label={t("trader.signals.filter.symbol")}>
            <input className={`${inputClass} font-mono`} value={symbol} spellCheck={false} onChange={(e) => setSymbol(e.target.value)} />
          </Field>
          <Field label={t("trader.signals.filter.outcome")}>
            <select className={inputClass} value={outcome} onChange={(e) => setOutcome(e.target.value)}>
              <option value="">{t("trader.signals.filter.any")}</option>
              {OUTCOMES.map((o) => (
                <option key={o} value={o}>
                  {t(`trader.signals.outcome.${o}` as MessageKey)}
                </option>
              ))}
            </select>
          </Field>
        </div>
      )}
      <PanelBody query={query}>
        {(data) =>
          data.items.length === 0 ? (
            <Empty message={t(meets ? "trader.signals.empty.qualified" : "trader.signals.empty.history")} />
          ) : (
            <div className="space-y-3">
              <div className="-mx-4 overflow-x-auto px-4">
                <table className="w-full min-w-[40rem] text-left text-sm">
                  <thead className="text-xs text-muted">
                    <tr>
                      <th className="pb-2 pr-3 font-medium">{t("trader.signals.col.coin")}</th>
                      <th className="pb-2 pr-3 font-medium">{t("trader.signals.col.day")}</th>
                      <th className="pb-2 pr-3 text-right font-medium">{t("trader.signals.col.score")}</th>
                      <th className="pb-2 pr-3 font-medium">{t("trader.signals.col.outcome")}</th>
                      <th className="pb-2 pr-3 text-right font-medium">{t("trader.signals.col.ai")}</th>
                      <th className="pb-2 pr-3 font-medium">{t("trader.signals.col.mode")}</th>
                      <th className="pb-2 font-medium">{t("trader.signals.col.when")}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {data.items.map((c) => (
                      <CandidateRow key={c.id} c={c} />
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <p className="text-xs text-muted">{t("trader.signals.total", { shown: data.items.length, total: data.total })}</p>
                {data.items.length < data.total && (
                  <Button size="sm" variant="ghost" onClick={() => setLimit((l) => l + PAGE)}>
                    {t("trader.signals.more")}
                  </Button>
                )}
              </div>
            </div>
          )
        }
      </PanelBody>
    </Card>
  );
}

function ReceiverTab() {
  const { t, dateTime } = useI18n();
  const acks = useTraderQuery<SignalAck[]>(["signals", "acks"], () => traderApi.GET("/trader/v1/signals/acks"));
  return (
    <Card>
      <p className="mb-4 max-w-prose text-xs text-muted">{t("trader.signals.ack.note")}</p>
      <PanelBody query={acks}>
        {(rows) =>
          rows.length === 0 ? (
            <Empty message={t("trader.signals.ack.empty")} />
          ) : (
            <div className="-mx-4 overflow-x-auto px-4">
              <table className="w-full min-w-[36rem] text-left text-sm">
                <thead className="text-xs text-muted">
                  <tr>
                    <th className="pb-2 pr-3 font-medium">{t("trader.signals.col.signal")}</th>
                    <th className="pb-2 pr-3 font-medium">{t("trader.signals.col.stage")}</th>
                    <th className="pb-2 pr-3 font-medium">{t("trader.signals.col.env")}</th>
                    <th className="pb-2 pr-3 font-medium">{t("trader.signals.col.status")}</th>
                    <th className="pb-2 pr-3 font-medium">{t("trader.signals.col.reason")}</th>
                    <th className="pb-2 font-medium">{t("trader.signals.col.when")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {rows.map((a) => (
                    <tr key={a.id}>
                      <td className="py-2 pr-3 font-mono text-xs">{a.signal_id}</td>
                      <td className="py-2 pr-3 text-xs">{a.stage}</td>
                      <td className="py-2 pr-3 text-xs">{a.environment ?? "-"}</td>
                      <td className="py-2 pr-3 text-xs">{a.status ?? "-"}</td>
                      <td className="py-2 pr-3 text-xs text-muted">{a.reason ?? "-"}</td>
                      <td className="py-2 text-xs text-muted">{dateTime(a.received_at)}</td>
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
