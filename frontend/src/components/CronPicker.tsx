import { useMemo, useState } from "react";
import cronstrue from "cronstrue/i18n";
import { useI18n } from "@/i18n/context";
import { Button, inputClass } from "@/components/primitives";

/**
 * A schedule chosen from dropdowns, and read back in the reader's own language.
 *
 * Cron is a fine storage format and a poor input. `0 18 * * 1-5` is five fields
 * of positional syntax that has to be memorised before the feature can be used
 * at all, and the failure it produces is silent: a wrong expression saves
 * cleanly and the schedule simply never fires when the reader expected it to.
 *
 * So the dropdowns compose the expression and `cronstrue` says what it means -
 * "Pada 18:00, Senin sampai Jumat" - in whichever language is selected. The
 * readback is the point: it is the only thing that catches a schedule that
 * parses and means something other than intended.
 *
 * `cronstrue` rather than a cron *editor* package. Every dropdown-based editor
 * on npm carries a UI framework with it - `react-js-cron` wants antd 6 - and
 * importing a second design system into a Tailwind codebase costs far more
 * than the four selects below. cronstrue does the one thing that is genuinely
 * hard, has zero dependencies, and ships the Indonesian locale this product
 * needs.
 */

type Frequency = "off" | "daily" | "weekdays" | "weekly" | "hourly";

const HOURS = Array.from({ length: 24 }, (_, hour) => hour);
const MINUTES = [0, 15, 30, 45];
const WEEKDAYS = [1, 2, 3, 4, 5, 6, 0];
const EVERY_N_HOURS = [1, 2, 3, 4, 6, 8, 12];

/** Read an expression back into the controls, so editing an existing one works. */
function parse(expression: string): {
  frequency: Frequency;
  hour: number;
  minute: number;
  weekday: number;
  everyHours: number;
} {
  const fallback = {
    frequency: "off" as Frequency,
    hour: 18,
    minute: 0,
    weekday: 1,
    everyHours: 2,
  };
  const parts = expression.trim().split(/\s+/);
  if (parts.length !== 5) return fallback;

  const [minute, hour, , , weekday] = parts;
  const minuteValue = Number(minute);
  if (!Number.isInteger(minuteValue)) return fallback;

  if (hour.startsWith("*/")) {
    return { ...fallback, frequency: "hourly", minute: minuteValue, everyHours: Number(hour.slice(2)) || 1 };
  }

  const hourValue = Number(hour);
  if (!Number.isInteger(hourValue)) return fallback;

  if (weekday === "1-5")
    return { ...fallback, frequency: "weekdays", hour: hourValue, minute: minuteValue };
  if (weekday === "*")
    return { ...fallback, frequency: "daily", hour: hourValue, minute: minuteValue };
  if (/^\d$/.test(weekday))
    return {
      ...fallback,
      frequency: "weekly",
      hour: hourValue,
      minute: minuteValue,
      weekday: Number(weekday),
    };

  // An expression the dropdowns cannot represent - somebody wrote it by hand,
  // or an older build stored it. Reported as unrepresentable rather than
  // quietly rewritten to something the controls can show, which would change a
  // working schedule the moment its owner opened the screen.
  return fallback;
}

function compose(state: ReturnType<typeof parse>): string {
  const { frequency, hour, minute, weekday, everyHours } = state;
  switch (frequency) {
    case "off":
      return "";
    case "hourly":
      return `${minute} */${everyHours} * * *`;
    case "daily":
      return `${minute} ${hour} * * *`;
    case "weekdays":
      return `${minute} ${hour} * * 1-5`;
    case "weekly":
      return `${minute} ${hour} * * ${weekday}`;
  }
}

export function CronPicker({
  value,
  onSave,
  busy = false,
  nextRunAt,
}: {
  value: string;
  onSave: (expression: string) => void;
  busy?: boolean;
  nextRunAt?: string | null;
}) {
  const { t, locale, dateTime } = useI18n();
  const [state, setState] = useState(() => parse(value));

  const expression = compose(state);

  // Whether the stored expression is one these controls can represent. A hand
  // written cron must not be silently replaced by whatever the dropdowns
  // happen to be showing.
  const representable = useMemo(
    () => !value || compose(parse(value)) === value.trim(),
    [value],
  );

  const described = useMemo(() => {
    if (!expression) return null;
    try {
      return cronstrue.toString(expression, { locale, use24HourTimeFormat: true });
    } catch {
      // cronstrue refusing is itself the answer: the expression is not one a
      // scheduler will accept either.
      return null;
    }
  }, [expression, locale]);

  const set = (patch: Partial<typeof state>) => setState((current) => ({ ...current, ...patch }));

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <select
          className={`${inputClass} w-auto text-xs`}
          value={state.frequency}
          onChange={(event) => set({ frequency: event.target.value as Frequency })}
          aria-label={t("cron.frequency")}
        >
          {(["off", "weekdays", "daily", "weekly", "hourly"] as const).map((option) => (
            <option key={option} value={option}>
              {t(`cron.frequency.${option}` as never)}
            </option>
          ))}
        </select>

        {state.frequency === "weekly" && (
          <select
            className={`${inputClass} w-auto text-xs`}
            value={state.weekday}
            onChange={(event) => set({ weekday: Number(event.target.value) })}
            aria-label={t("cron.weekday")}
          >
            {WEEKDAYS.map((day) => (
              <option key={day} value={day}>
                {t(`cron.day.${day}` as never)}
              </option>
            ))}
          </select>
        )}

        {state.frequency === "hourly" && (
          <select
            className={`${inputClass} w-auto text-xs`}
            value={state.everyHours}
            onChange={(event) => set({ everyHours: Number(event.target.value) })}
            aria-label={t("cron.everyHours")}
          >
            {EVERY_N_HOURS.map((hours) => (
              <option key={hours} value={hours}>
                {t("cron.everyNHours", { hours })}
              </option>
            ))}
          </select>
        )}

        {state.frequency !== "off" && state.frequency !== "hourly" && (
          <select
            className={`${inputClass} w-auto text-xs tnum`}
            value={state.hour}
            onChange={(event) => set({ hour: Number(event.target.value) })}
            aria-label={t("cron.hour")}
          >
            {HOURS.map((hour) => (
              <option key={hour} value={hour}>
                {String(hour).padStart(2, "0")}
              </option>
            ))}
          </select>
        )}

        {state.frequency !== "off" && (
          <select
            className={`${inputClass} w-auto text-xs tnum`}
            value={state.minute}
            onChange={(event) => set({ minute: Number(event.target.value) })}
            aria-label={t("cron.minute")}
          >
            {MINUTES.map((minute) => (
              <option key={minute} value={minute}>
                :{String(minute).padStart(2, "0")}
              </option>
            ))}
          </select>
        )}

        <Button size="sm" busy={busy} onClick={() => onSave(expression)}>
          {t("common.save")}
        </Button>
      </div>

      <div className="flex flex-wrap items-baseline gap-2 text-xs">
        {described ? (
          <>
            {/* The readback, and the timezone with it. Every cron on this
                platform is read in exchange time, and cronstrue has no way to
                know that - so a description reading "at 18:00" would be taken
                for the reader's own clock. */}
            <span className="text-ink/80">{described}</span>
            <span className="text-faint">{t("cron.exchangeTime")}</span>
            <code className="rounded border border-line px-1.5 py-0.5 font-mono text-[0.65rem] text-faint">
              {expression}
            </code>
          </>
        ) : (
          <span className="text-faint">{t("cron.frequency.off.hint")}</span>
        )}
      </div>

      {!representable && (
        // Shown rather than silently overwritten: the dropdowns cannot express
        // every cron, and opening this screen must not rewrite a schedule
        // somebody set deliberately.
        <p className="rounded-md border border-watch/25 bg-watch/5 px-3 py-2 text-xs text-watch">
          {t("cron.handWritten", { expression: value })}
        </p>
      )}

      {nextRunAt && (
        <p className="text-xs text-faint">{t("cron.nextRun", { when: dateTime(nextRunAt) })}</p>
      )}
    </div>
  );
}
