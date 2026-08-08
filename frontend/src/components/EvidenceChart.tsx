import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CandlestickSeries,
  createChart,
  LineStyle,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { api, errorMessage } from "@/api/client";
import { useI18n, type MessageKey } from "@/i18n/context";
import { Card, Caveat, Empty, Loading } from "@/components/primitives";

interface Bar {
  t: string;
  o: string;
  h: string;
  l: string;
  c: string;
  v: string;
}

interface Level {
  key: string;
  price: string;
  basis: string;
}

interface Mark {
  text: string;
  side: "supporting" | "conflicting";
}

const LEVEL_COLOR: Record<string, string> = {
  support_level: "#22c55e",
  resistance_level: "#ef4444",
  target_price: "#eab308",
  suggested_stop: "#f97316",
};

/**
 * The price series with every level the recommendation named drawn onto it.
 *
 * Explainability has been text-only: a stance, a paragraph, and two lists of
 * factors. That is checkable in principle and hard in practice - "price is
 * above its 50-bar average" asks the reader to hold two numbers in their head
 * and trust the comparison. Drawn, the same claim is one glance.
 *
 * Built on `lightweight-charts` because `PriceChart` already is: a second
 * charting approach in one product means two crosshairs, two time-axis
 * behaviours, and two sets of bugs.
 *
 * **Every mark is horizontal.** A target drawn as a line sloping into the
 * empty space right of the last bar is a forecast whatever the legend calls
 * it, so targets are price lines with their stated basis beside them - the
 * same rule the PDF export follows, for the same reason.
 */
export function EvidenceChart({ ticker }: { ticker: string }) {
  const { t, money, locale } = useI18n();
  const container = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);

  const query = useQuery({
    queryKey: ["evidence", ticker],
    queryFn: async () => {
      const { data, error } = await api.GET("/assets/{ticker}/evidence", {
        params: { path: { ticker }, query: { bars: 180 } },
      });
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data as unknown as {
        bars: Bar[];
        levels: Level[];
        marks: Mark[];
        caveat: string;
      };
    },
    // An issuer with no stored recommendation is the ordinary case, not a
    // fault. Retrying four times before saying so wastes the reader's time.
    retry: false,
  });

  const bars = query.data?.bars;
  const levels = query.data?.levels;

  useEffect(() => {
    if (!container.current || !bars?.length) return;

    const instance = createChart(container.current, {
      height: 320,
      layout: {
        background: { color: "transparent" },
        textColor: "#8b98a9",
        fontFamily: "JetBrains Mono, ui-monospace, monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(139, 152, 169, 0.08)" },
        horzLines: { color: "rgba(139, 152, 169, 0.08)" },
      },
      rightPriceScale: { borderColor: "rgba(139, 152, 169, 0.2)" },
      timeScale: { borderColor: "rgba(139, 152, 169, 0.2)" },
      localization: { locale },
    });
    chart.current = instance;

    const series = instance.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderVisible: false,
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });

    series.setData(
      bars.map((bar) => ({
        time: (Date.parse(bar.t) / 1000) as UTCTimestamp,
        open: Number(bar.o),
        high: Number(bar.h),
        low: Number(bar.l),
        close: Number(bar.c),
      })),
    );

    for (const level of levels ?? []) {
      series.createPriceLine({
        price: Number(level.price),
        color: LEVEL_COLOR[level.key] ?? "#8b98a9",
        lineWidth: 1,
        // Dashed on purpose. A solid line reads as something that happened; a
        // level is a number the analysis named, which is a different claim.
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: level.key.replace(/_/g, " "),
      });
    }

    instance.timeScale().fitContent();

    const resize = () =>
      container.current && instance.applyOptions({ width: container.current.clientWidth });
    resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      instance.remove();
      chart.current = null;
    };
  }, [bars, levels, locale]);

  if (query.isLoading) return <Loading />;
  if (query.isError)
    return (
      <Card title={t("evidence.title")}>
        <Empty message={t("evidence.none")} hint={t("evidence.noneHint")} />
      </Card>
    );
  if (!bars?.length)
    return (
      <Card title={t("evidence.title")}>
        <Empty message={t("evidence.noBars")} hint={t("evidence.noBarsHint")} />
      </Card>
    );

  const marks = query.data?.marks ?? [];

  return (
    <Card title={t("evidence.title")}>
      <p className="mb-3 text-sm text-muted">{t("evidence.intro")}</p>

      <div ref={container} className="w-full" />

      <ul className="mt-3 space-y-1">
        {(levels ?? []).map((level) => (
          <li key={level.key} className="flex flex-wrap items-baseline gap-2 text-xs">
            <span
              className="inline-block h-2 w-4 rounded-sm"
              style={{ background: LEVEL_COLOR[level.key] ?? "#8b98a9" }}
              aria-hidden
            />
            <span className="text-ink">{t(`evidence.level.${level.key}` as MessageKey)}</span>
            <span className="font-mono tnum text-muted">{money(level.price)}</span>
            {/* The basis on the same line as the number. A level with no
                stated basis gets treated as more certain than it is. */}
            <span className="text-faint">— {level.basis}</span>
          </li>
        ))}
      </ul>

      {marks.length > 0 && (
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {(["supporting", "conflicting"] as const).map((side) => {
            const rows = marks.filter((mark) => mark.side === side);
            if (rows.length === 0) return null;
            return (
              <div key={side}>
                <p className="mb-1.5 text-xs text-faint">
                  {t(side === "supporting" ? "evidence.supporting" : "evidence.conflicting")}
                </p>
                <ul className="space-y-1">
                  {rows.map((mark) => (
                    <li
                      key={mark.text}
                      className={`relative pl-4 text-sm leading-relaxed text-ink/85 before:absolute before:left-0 before:top-2 before:size-1.5 before:rounded-full ${
                        side === "supporting" ? "before:bg-rise/60" : "before:bg-fall/60"
                      }`}
                    >
                      {mark.text}
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      )}

      <Caveat>{query.data?.caveat}</Caveat>
    </Card>
  );
}
