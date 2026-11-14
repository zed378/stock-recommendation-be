import { useState } from "react";
import { useI18n } from "@/i18n/context";
import { Button, Card, Empty, Field, inputClass } from "@/components/primitives";
import { OriginBadge, PanelBody } from "@/trader/components";
import { traderApi } from "@/trader/client";
import { useTraderQuery } from "@/trader/hooks";
import { groupDigits, multiplyDecimals } from "@/trader/format";
import { useDecide, type ApproveResult } from "@/trader/mutations";
import type { Intent } from "@/trader/types";

/**
 * Intents waiting for a decision.
 *
 * The card shows exactly what will be sent, and the approve call echoes the hash
 * of exactly that, so an approval on a card for an older price is refused by the
 * server rather than sent (docs/05-MODULE-SPECIFICATIONS/07). The expiry shown
 * is the real one; there is no countdown pressure (UX principle 7).
 */
export function TraderApprovals() {
  const { t } = useI18n();
  const query = useTraderQuery<Intent[]>(["intents"], () => traderApi.GET("/trader/v1/intents"));
  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold text-ink">{t("trader.approvals.title")}</h1>
      <PanelBody query={query}>
        {(intents, meta) => {
          const waiting = intents.filter((i) => i.approval?.state === "AWAITING");
          const decided = intents.filter((i) => i.approval && i.approval.state !== "AWAITING");
          return (
            <div className="space-y-6">
              {waiting.length === 0 ? (
                <Card>
                  <Empty message={t("trader.approvals.empty")} hint={t("trader.approvals.emptyHint")} />
                </Card>
              ) : (
                <ul className="space-y-4">
                  {waiting.map((intent) => (
                    <li key={intent.identity}>
                      <ApprovalCard intent={intent} origin={meta.origin} />
                    </li>
                  ))}
                </ul>
              )}
              {decided.length > 0 && (
                <section aria-labelledby="decided">
                  <h2 id="decided" className="mb-2 text-sm font-medium text-muted">
                    {t("trader.approvals.history")}
                  </h2>
                  <ul className="divide-y divide-line rounded-lg border border-line">
                    {decided.slice(0, 20).map((i) => (
                      <li key={i.identity} className="flex flex-wrap items-center gap-x-3 px-4 py-2.5 text-sm">
                        <span className="font-mono">{i.pair}</span>
                        <span>{i.side}</span>
                        <span className="text-muted">{t(`trader.approval.${i.approval!.state}`)}</span>
                        {i.approval?.reason && <span className="text-xs text-faint">{i.approval.reason}</span>}
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </div>
          );
        }}
      </PanelBody>
    </div>
  );
}

function ApprovalCard({ intent, origin }: { intent: Intent; origin: "LIVE" | "PAPER" | "BACKTEST" }) {
  const { t, locale, dateTime } = useI18n();
  const decide = useDecide();
  const [reason, setReason] = useState("");
  const [outcome, setOutcome] = useState<string | null>(null);
  const value = multiplyDecimals(intent.entry_price, intent.quantity);
  const num = (v: string) => groupDigits(v, locale);

  const report = (r: ApproveResult) =>
    setOutcome(
      r.already_decided
        ? t("trader.approve.already", { state: r.state })
        : r.sent
          ? t("trader.approve.sent", { state: r.detail })
          : r.state === "DENIED"
            ? t("trader.deny.done")
            : t("trader.approve.notSent", { detail: r.detail }),
    );

  return (
    <Card
      title={
        <h2 className="flex flex-wrap items-center gap-2 text-sm font-medium text-ink">
          <span className="font-mono">{intent.pair}</span>
          <span>{intent.side}</span>
          <OriginBadge origin={origin} />
        </h2>
      }
      action={
        intent.approval && (
          <span className="text-xs text-muted">
            {t("trader.card.expires", { when: dateTime(intent.approval.expires_at) })}
          </span>
        )
      }
    >
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
        <Item label={t("trader.card.price")} value={num(intent.entry_price)} />
        <Item label={t("trader.card.quantity")} value={intent.quantity} />
        <Item label={t("trader.card.value")} value={`IDR ${num(value)}`} />
        <Item label={t("trader.card.stop")} value={intent.stop_price ? num(intent.stop_price) : "-"} />
        {intent.risk_amount_idr && <Item label={t("trader.card.risk")} value={num(intent.risk_amount_idr)} />}
      </dl>

      <p className="mt-4 border-l-2 border-watch/40 pl-2.5 text-xs leading-relaxed text-faint">
        {t("trader.card.exact")}
      </p>
      <p className="mt-2 text-xs text-faint">{t("trader.card.missing")}</p>

      <div className="mt-4 space-y-3">
        <Field label={t("trader.card.reason")}>
          <input className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
        <div className="flex flex-wrap gap-2">
          <Button
            busy={decide.isPending && decide.variables?.decision === "approve"}
            disabled={decide.isPending}
            onClick={() =>
              decide.mutate(
                { identity: intent.identity, intentHash: intent.intent_hash, decision: "approve" },
                { onSuccess: report },
              )
            }
          >
            {t("trader.card.approve")}
          </Button>
          <Button
            variant="ghost"
            busy={decide.isPending && decide.variables?.decision === "deny"}
            disabled={decide.isPending}
            onClick={() =>
              decide.mutate(
                { identity: intent.identity, intentHash: intent.intent_hash, decision: "deny", reason },
                { onSuccess: report },
              )
            }
          >
            {t("trader.card.deny")}
          </Button>
        </div>
        {/* Text and role, so a screen reader announces the result of the decision. */}
        <div role="status" aria-live="polite">
          {outcome && <p className="text-sm text-ink">{outcome}</p>}
          {decide.error && <p className="text-sm text-fall">{decide.error.message}</p>}
        </div>
      </div>
    </Card>
  );
}

function Item({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-faint">{label}</dt>
      <dd className="mt-0.5 font-mono text-sm tnum text-ink">{value}</dd>
    </div>
  );
}
