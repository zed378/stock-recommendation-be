import { useI18n, type MessageKey } from "@/i18n/context";
import { Card, Caveat, Empty, Stat } from "@/components/primitives";

/**
 * The indicator snapshot, rendered by shape rather than assumed to be flat.
 *
 * It is not flat: `snapshot` holds `bars`, `as_of`, `last_close`, `structure`,
 * a nested `indicators` map, `levels`, and `breakout`. Several indicators carry
 * more than one component - MACD has three, Bollinger four, Ichimoku five - so
 * printing values naively yields `[object Object]`, which is exactly what the
 * first version of this screen did.
 *
 * The generated API types could not have caught it: `snapshot` is declared as
 * a bare `object` in the OpenAPI document, so there was nothing to check
 * against. Everything below therefore validates the shape as it reads it.
 */

interface IndicatorSnapshot {
  bars?: number;
  as_of?: string;
  last_close?: number;
  structure?: string;
  indicators?: Record<string, Record<string, number | null>>;
  levels?: { support?: number[]; resistance?: number[] };
  breakout?: { direction?: string; level?: number | null; lookback?: number };
}

/**
 * Which scale each value lives on, so it can be formatted honestly.
 *
 * This is presentation knowledge, not a duplicate of the indicator maths: the
 * engine computes the numbers and this decides how to read them. Printing an
 * RSI of 57.9 as "Rp 58" or a moving average of 2477.5 as a bare "2.477,50"
 * are both wrong, and in opposite directions.
 */
type Scale = "price" | "plain" | "fraction" | "count";

const PRICE_INDICATORS = /^(sma|ema|bollinger|atr|ichimoku|macd)/;
const FRACTION_FIELDS = /^(volatility|bandwidth)/;
const COUNT_INDICATORS = /^(obv)/;

function scaleFor(indicator: string, field: string): Scale {
  if (FRACTION_FIELDS.test(indicator) || FRACTION_FIELDS.test(field)) return "fraction";
  if (COUNT_INDICATORS.test(indicator)) return "count";
  if (PRICE_INDICATORS.test(indicator)) return "price";
  return "plain";
}

/**
 * `sma(period=20)` -> `SMA 20`, `macd(fast=12,signal=9,slow=26)` -> `MACD 12/9/26`.
 *
 * The raw keys are precise and unreadable in a grid. The parameters are kept
 * because an SMA(20) and an SMA(200) are different things and dropping them
 * would merge two rows into one meaningless label.
 */
function readableName(key: string): string {
  const match = /^([a-z_]+)(?:\((.*)\))?$/.exec(key);
  if (!match) return key.toUpperCase();

  const [, base, params] = match;
  const name = base.replace(/_/g, " ").toUpperCase();
  if (!params) return name;

  const values = params
    .split(",")
    .map((pair) => pair.split("=")[1])
    .filter(Boolean);
  return values.length ? `${name} ${values.join("/")}` : name;
}

export function IndicatorSnapshotView({
  snapshot,
  features,
}: {
  snapshot: unknown;
  features: unknown;
}) {
  const { t, n, money, date } = useI18n();

  const data = (snapshot ?? {}) as IndicatorSnapshot;
  const indicators = data.indicators ?? {};
  const entries = Object.entries(indicators);

  if (!entries.length) {
    return (
      <Card>
        <Empty message={t("indicators.empty")} hint={t("indicators.emptyHint")} />
      </Card>
    );
  }

  const format = (value: number | null, scale: Scale) => {
    if (value === null || value === undefined || !Number.isFinite(value)) return "—";
    switch (scale) {
      case "price":
        return money(value);
      case "fraction":
        return `${n(value * 100, 2)}%`;
      case "count":
        return n(value, 0);
      default:
        return n(value, 2);
    }
  };

  const structureKey = `indicators.structure.${data.structure}` as MessageKey;

  return (
    <div className="space-y-4">
      <Card>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
          <Stat label={t("indicators.bars")} value={n(data.bars ?? null, 0)} />
          <Stat label={t("indicators.asOf")} value={date(data.as_of)} mono={false} />
          <Stat label={t("indicators.lastClose")} value={money(data.last_close ?? null)} />
          <Stat
            label={t("indicators.structure")}
            // Falls back to the raw value rather than an empty cell: a new
            // structure the backend starts reporting should show up as an
            // unfamiliar word, not disappear.
            value={t(structureKey) === structureKey ? (data.structure ?? "—") : t(structureKey)}
            mono={false}
          />
        </dl>
      </Card>

      <Card title={t("indicators.title")}>
        <div className="grid gap-x-6 gap-y-5 sm:grid-cols-2 lg:grid-cols-3">
          {entries.map(([key, fields]) => {
            const parts = Object.entries(fields ?? {});
            // A lone `value` field is the common case and deserves the compact
            // treatment; anything else is a composite and gets its components
            // named, because "MACD: 38.68" hides the signal and histogram that
            // give it meaning.
            const single = parts.length === 1 && parts[0][0] === "value";

            return (
              <div key={key} className="min-w-0">
                <p className="font-mono text-xs text-faint">{readableName(key)}</p>
                {single ? (
                  <p className="mt-1 font-mono text-sm tnum text-ink">
                    {format(parts[0][1], scaleFor(key, "value"))}
                  </p>
                ) : (
                  <dl className="mt-1 space-y-0.5">
                    {parts.map(([field, value]) => (
                      <div key={field} className="flex items-baseline justify-between gap-3">
                        <dt className="text-xs text-muted">{field.replace(/_/g, " ")}</dt>
                        <dd
                          className={`font-mono text-xs tnum ${
                            value === null ? "text-faint" : "text-ink"
                          }`}
                        >
                          {format(value, scaleFor(key, field))}
                        </dd>
                      </div>
                    ))}
                  </dl>
                )}
              </div>
            );
          })}
        </div>
      </Card>

      {(data.levels?.support?.length || data.levels?.resistance?.length) && (
        <Card title={t("indicators.levels")}>
          <div className="grid gap-4 sm:grid-cols-2">
            <LevelList
              label={t("indicators.support")}
              levels={data.levels?.support}
              tone="rise"
            />
            <LevelList
              label={t("indicators.resistance")}
              levels={data.levels?.resistance}
              tone="fall"
            />
          </div>
          <Caveat>{t("indicators.levelsNote")}</Caveat>
        </Card>
      )}

      {data.breakout && (
        <Card title={t("indicators.breakout")}>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3">
            <Stat
              label={t("indicators.breakout.direction")}
              value={t(
                `indicators.breakout.${data.breakout.direction ?? "none"}` as MessageKey,
              )}
              tone={
                data.breakout.direction === "up"
                  ? "rise"
                  : data.breakout.direction === "down"
                    ? "fall"
                    : "neutral"
              }
              mono={false}
            />
            <Stat
              label={t("indicators.breakout.level")}
              value={data.breakout.level != null ? money(data.breakout.level) : "—"}
            />
            <Stat
              label={t("indicators.breakout.lookback")}
              value={n(data.breakout.lookback ?? null, 0)}
            />
          </dl>
          <Caveat>{t("indicators.breakoutNote")}</Caveat>
        </Card>
      )}

      <FeatureGrid features={features} />
    </div>
  );
}

function LevelList({
  label,
  levels,
  tone,
}: {
  label: string;
  levels: number[] | undefined;
  tone: "rise" | "fall";
}) {
  const { money } = useI18n();
  const colour = tone === "rise" ? "text-rise" : "text-fall";

  return (
    <div>
      <p className="mb-1.5 text-xs text-faint">{label}</p>
      {levels?.length ? (
        <ul className="space-y-1">
          {levels.map((level, index) => (
            <li key={index} className={`font-mono text-sm tnum ${colour}`}>
              {money(level)}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-faint">—</p>
      )}
    </div>
  );
}

/**
 * The engineered features, which are mostly fractions.
 *
 * A return of 0.0202 printed as "0,02" reads as two hundredths of a rupiah
 * rather than two per cent, so anything named as a return, a drawdown, a
 * volatility, a gap, or a position is shown as a percentage.
 */
function FeatureGrid({ features }: { features: unknown }) {
  const { t, n } = useI18n();
  const data = (features ?? {}) as Record<string, number | null>;
  const entries = Object.entries(data).filter(([key]) => key !== "bars");

  if (!entries.length) return null;

  const isFraction = (key: string) =>
    /^(return_|volatility_|drawdown_|range_position|gap_from_)/.test(key);

  return (
    <Card title={t("indicators.features")}>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3 lg:grid-cols-4">
        {entries.map(([key, value]) => (
          <Stat
            key={key}
            label={key.replace(/_/g, " ")}
            value={
              value === null || !Number.isFinite(value)
                ? "—"
                : isFraction(key)
                  ? `${n(value * 100, 2)}%`
                  : n(value, 0)
            }
            tone={isFraction(key) && value !== null && value < 0 ? "fall" : "neutral"}
          />
        ))}
      </dl>
    </Card>
  );
}
