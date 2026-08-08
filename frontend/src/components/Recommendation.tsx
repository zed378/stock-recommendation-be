import type { components } from "@/api/schema";
import { useI18n, type MessageKey } from "@/i18n/context";
import { Caveat, Card, Stat } from "@/components/primitives";

type Rec = components["schemas"]["RecommendationResponse"];

/**
 * How a recommendation is presented is the product, not decoration.
 *
 * Three decisions carry most of the weight here, and each exists to stop a
 * particular misreading:
 *
 *  - **Conflicting factors get the same visual weight as supporting ones.**
 *    Section 14.4 requires counter-evidence to be shown; putting it in a
 *    collapsed section below the case *for* would satisfy the letter of that
 *    and defeat the point. They sit side by side.
 *  - **The stance is a label, not a position on a scale.** No green-to-red
 *    gradient, because `watchlist` is not a weak buy and a gradient invites
 *    reading it as one.
 *  - **Confidence says where it came from.** It is a calibrated figure derived
 *    from evidence coverage and agreement, and a percentage with no
 *    explanation reads as a probability of being right, which it is not.
 */
export function Recommendation({ rec }: { rec: Rec }) {
  const { t, n, money } = useI18n();

  const label = rec.label ?? "hold";
  const labelKey = `rec.label.${label}` as MessageKey;
  const tone =
    label.includes("buy") ? "buy" : label.includes("sell") ? "sell" : label === "watchlist" ? "watch" : "hold";

  const toneClasses: Record<string, string> = {
    buy: "border-buy/40 bg-buy/10 text-buy",
    sell: "border-sell/40 bg-sell/10 text-sell",
    watch: "border-watch/40 bg-watch/10 text-watch",
    hold: "border-hold/40 bg-hold/10 text-hold",
  };

  const neutral = label === "hold" || label === "watchlist";
  const basis = parseBasis(rec.confidence_basis);

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-start gap-6">
          <div>
            <p className="text-xs text-faint">{t("rec.title")}</p>
            <p
              className={`mt-1.5 inline-block rounded-md border px-3 py-1.5 text-base font-semibold ${toneClasses[tone]}`}
            >
              {t(labelKey)}
            </p>
          </div>

          <div className="min-w-64 flex-1">
            <p className="text-xs text-faint">{t("rec.confidence")}</p>
            <p className="mt-1.5 font-mono text-2xl tnum text-ink">
              {rec.confidence === null || rec.confidence === undefined
                ? "—"
                : `${n(rec.confidence, 1)}`}
            </p>
            <ConfidenceBar value={rec.confidence} />
            {/* The backend's own sentence, which says how the number was
                reached and why it is capped. It belongs beside the figure,
                not buried in a JSON dump at the bottom of the page. */}
            {basis?.explanation ? (
              <Caveat>{basis.explanation}</Caveat>
            ) : (
              <Caveat>{t("rec.confidenceExplain")}</Caveat>
            )}
          </div>

          {rec.horizon && (
            <Stat label={t("rec.horizon")} value={rec.horizon} mono={false} />
          )}
        </div>

        {/* The model's own number is shown *beside* the calibrated one rather
            than instead of it. Hiding it entirely would make the distinction
            invisible; showing it without the note would suggest it counted. */}
        {rec.model_self_reported_confidence !== null &&
          rec.model_self_reported_confidence !== undefined && (
            <div className="mt-4 border-t border-line pt-3">
              <div className="flex items-baseline gap-2">
                <span className="text-xs text-faint">{t("rec.modelSelfReported")}</span>
                <span className="font-mono text-sm tnum text-muted line-through decoration-faint/60">
                  {n(rec.model_self_reported_confidence, 1)}
                </span>
              </div>
              <Caveat>{t("rec.modelSelfReportedNote")}</Caveat>
            </div>
          )}
      </Card>

      {rec.reasoning && (
        <Card title={t("rec.reasoning")}>
          <p className="text-sm leading-relaxed text-ink/90">{rec.reasoning}</p>
        </Card>
      )}

      {/* Side by side, deliberately. */}
      <div className="grid gap-4 md:grid-cols-2">
        <FactorList title={t("rec.supporting")} items={rec.supporting_factors} tone="rise" />
        <FactorList title={t("rec.conflicting")} items={rec.conflicting_factors} tone="fall" />
      </div>

      {rec.risk_factors?.length ? (
        <FactorList title={t("rec.risks")} items={rec.risk_factors} tone="watch" />
      ) : null}

      <div className="grid gap-4 md:grid-cols-2">
        {rec.bullish_scenario && (
          <Card title={t("rec.bullish")}>
            <p className="text-sm leading-relaxed text-ink/85">{rec.bullish_scenario}</p>
          </Card>
        )}
        {rec.bearish_scenario && (
          <Card title={t("rec.bearish")}>
            <p className="text-sm leading-relaxed text-ink/85">{rec.bearish_scenario}</p>
          </Card>
        )}
      </div>

      <Card>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
          <Stat label={t("rec.support")} value={rec.support_level ? money(rec.support_level) : "—"} />
          <Stat
            label={t("rec.resistance")}
            value={rec.resistance_level ? money(rec.resistance_level) : "—"}
          />
          <Stat
            label={t("rec.target")}
            value={rec.target_price ? money(rec.target_price) : t("rec.noTarget")}
          />
          <Stat
            label={t("rec.stop")}
            value={rec.suggested_stop ? money(rec.suggested_stop) : t("rec.noTarget")}
          />
        </dl>

        {/* An absent target on a neutral stance is a decision, not a gap, and
            saying so stops it reading as missing data. */}
        {neutral && !rec.target_price && <Caveat>{t("rec.noTargetReason")}</Caveat>}

        {(rec.target_price_method || rec.suggested_stop_method) && (
          <div className="mt-3 space-y-1 border-t border-line pt-3 text-xs text-faint">
            {rec.target_price_method && (
              <p>
                {t("rec.target")} — {t("rec.method")}: {rec.target_price_method}
              </p>
            )}
            {rec.suggested_stop_method && (
              <p>
                {t("rec.stop")} — {t("rec.method")}: {rec.suggested_stop_method}
              </p>
            )}
          </div>
        )}
      </Card>

      {basis && <ConfidenceBasis basis={basis} />}

      {/* Provenance, because "which model said this, under which prompt?" is
          the first question asked of an output that looks wrong. */}
      <Card title={t("rec.provenance")}>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
          <Stat label={t("rec.model")} value={rec.model ?? "—"} mono={false} />
          <Stat label="Provider" value={rec.provider ?? "—"} mono={false} />
          <Stat label={t("rec.promptVersion")} value={rec.prompt_version ?? "—"} />
          <Stat label={t("rec.attempts")} value={rec.attempts ?? "—"} />
        </dl>
      </Card>
    </div>
  );
}

// --- the calibration, made legible ----------------------------------------

interface Basis {
  explanation?: string;
  components?: { coverage?: number; agreement?: number; balance?: number };
  signals?: { agent?: string; direction?: number; sufficiency?: string }[];
  confidence?: number;
  raw: unknown;
}

/** Read the basis defensively: it is typed as a bare object by the API. */
function parseBasis(value: unknown): Basis | null {
  if (!value) return null;
  if (typeof value === "string") return { explanation: value, raw: value };
  if (typeof value !== "object") return null;

  const node = value as Record<string, unknown>;
  return {
    explanation: typeof node.explanation === "string" ? node.explanation : undefined,
    components:
      node.components && typeof node.components === "object"
        ? (node.components as Basis["components"])
        : undefined,
    signals: Array.isArray(node.signals) ? (node.signals as Basis["signals"]) : undefined,
    confidence: typeof node.confidence === "number" ? node.confidence : undefined,
    raw: value,
  };
}

/**
 * The three inputs to the calibration, and what each agent contributed.
 *
 * This is the difference between a score a reader has to take on trust and one
 * they can check. Section 14.4's whole point is that confidence is derived from
 * evidence rather than asserted by the model, and a number alone cannot show
 * that - but "coverage 80%, agreement 100%, balance 100%" can, especially when
 * the agent that was missing is named right beneath it.
 */
function ConfidenceBasis({ basis }: { basis: Basis }) {
  const { t, n } = useI18n();
  const components = basis.components ?? {};

  const rows = (
    [
      {
        key: "rec.component.coverage",
        whatKey: "rec.component.coverageWhat",
        value: components.coverage,
      },
      {
        key: "rec.component.agreement",
        whatKey: "rec.component.agreementWhat",
        value: components.agreement,
      },
      {
        key: "rec.component.balance",
        whatKey: "rec.component.balanceWhat",
        value: components.balance,
      },
    ] satisfies { key: MessageKey; whatKey: MessageKey; value: number | undefined }[]
  ).filter((row) => typeof row.value === "number");

  const directionLabel = (direction: number | undefined) => {
    if (direction === undefined) return "—";
    if (direction > 0) return t("rec.direction.bullish");
    if (direction < 0) return t("rec.direction.bearish");
    return t("rec.direction.neutral");
  };

  const directionTone = (direction: number | undefined) =>
    direction === undefined || direction === 0
      ? "text-muted"
      : direction > 0
        ? "text-rise"
        : "text-fall";

  if (!rows.length && !basis.signals?.length) return null;

  return (
    <Card title={t("rec.components")}>
      {rows.length > 0 && (
        <dl className="space-y-3">
          {rows.map((row) => (
            <div key={row.key}>
              <div className="flex items-baseline justify-between gap-4">
                <dt className="text-sm text-ink/90">{t(row.key)}</dt>
                <dd className="font-mono text-sm tnum text-ink">
                  {n((row.value as number) * 100, 0)}%
                </dd>
              </div>
              <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-surface">
                <div
                  className="h-full rounded-full bg-muted"
                  style={{ width: `${Math.max(0, Math.min(1, row.value as number)) * 100}%` }}
                />
              </div>
              <p className="mt-1 text-xs text-faint">{t(row.whatKey)}</p>
            </div>
          ))}
        </dl>
      )}

      {basis.signals?.length ? (
        <div className={rows.length ? "mt-5 border-t border-line pt-4" : ""}>
          <p className="mb-2 text-xs text-faint">{t("rec.signals")}</p>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-faint">
                <th className="pb-1.5 pr-4 font-medium">{t("rec.signal.agent")}</th>
                <th className="pb-1.5 pr-4 font-medium">{t("rec.signal.direction")}</th>
                <th className="pb-1.5 font-medium">{t("rec.signal.sufficiency")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {basis.signals.map((signal, index) => (
                <tr key={index}>
                  <td className="py-1.5 pr-4 font-mono text-xs text-ink/90">
                    {(signal.agent ?? "").replace(/_/g, " ")}
                  </td>
                  <td className={`py-1.5 pr-4 text-xs ${directionTone(signal.direction)}`}>
                    {directionLabel(signal.direction)}
                  </td>
                  <td className="py-1.5 text-xs text-muted">{signal.sufficiency ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {/* Kept, but folded away: useful when something looks wrong, noise the
          rest of the time. */}
      <details className="mt-4 border-t border-line pt-3">
        <summary className="cursor-pointer text-xs text-faint hover:text-muted">
          {t("rec.rawBasis")}
        </summary>
        <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap wrap-break-word rounded bg-surface p-2.5 font-mono text-xs leading-relaxed text-muted">
          {JSON.stringify(basis.raw, null, 2)}
        </pre>
      </details>
    </Card>
  );
}

function ConfidenceBar({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return null;
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-surface">
      {/* One colour, not a gradient. A gradient would imply a red-to-green
          spectrum of correctness, and confidence measures how much evidence
          agreed - not how likely the call is to be right. */}
      <div className="h-full rounded-full bg-muted" style={{ width: `${pct}%` }} />
    </div>
  );
}

function FactorList({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[] | null | undefined;
  tone: "rise" | "fall" | "watch";
}) {
  const { t } = useI18n();
  const markers = {
    rise: "before:bg-rise/60",
    fall: "before:bg-fall/60",
    watch: "before:bg-watch/60",
  };

  return (
    <Card title={title} className="h-full">
      {items?.length ? (
        <ul className="space-y-2.5">
          {items.map((item, index) => (
            <li
              key={index}
              className={`relative pl-4 text-sm leading-relaxed text-ink/85 before:absolute before:left-0 before:top-2 before:size-1.5 before:rounded-full ${markers[tone]}`}
            >
              {item}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-faint">{t("common.none")}</p>
      )}
    </Card>
  );
}
