import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  createChart,
  HistogramSeries,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";
import type { components } from "@/api/schema";
import { useI18n } from "@/i18n/context";

type Candle = components["schemas"]["CandleResponse"];

/**
 * Candlesticks with a volume histogram beneath.
 *
 * `lightweight-charts` rather than a general charting library: it is built for
 * this exact shape, handles the crosshair, time scale, and log axis without
 * configuration, and is a fraction of the size of the alternatives.
 *
 * The API sends decimals as strings so no precision is lost in JSON. They are
 * parsed here, at the boundary, rather than left as strings for the chart to
 * coerce silently - a string that fails to parse becomes NaN and draws a gap,
 * which is nearly invisible and completely wrong.
 */
export function PriceChart({ candles, height = 420 }: { candles: Candle[]; height?: number }) {
  const container = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const { locale } = useI18n();

  useEffect(() => {
    if (!container.current) return;

    const instance = createChart(container.current, {
      height,
      layout: {
        background: { color: "transparent" },
        textColor: "#8b98a9",
        fontFamily: "JetBrains Mono, ui-monospace, monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "#1e2733" },
        horzLines: { color: "#1e2733" },
      },
      rightPriceScale: { borderColor: "#1e2733", scaleMargins: { top: 0.08, bottom: 0.26 } },
      timeScale: { borderColor: "#1e2733", timeVisible: false },
      crosshair: { mode: 1 },
      localization: { locale: locale === "id" ? "id-ID" : "en-US" },
    });
    chart.current = instance;

    const priceSeries = instance.addSeries(CandlestickSeries, {
      upColor: "#26a69a",
      downColor: "#ef5350",
      borderUpColor: "#26a69a",
      borderDownColor: "#ef5350",
      wickUpColor: "#26a69a",
      wickDownColor: "#ef5350",
    });

    const volumeSeries = instance.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    instance
      .priceScale("volume")
      .applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });

    const parsed = candles
      .map((candle) => {
        const time = Math.floor(Date.parse(candle.timestamp) / 1000) as UTCTimestamp;
        const open = Number(candle.open);
        const high = Number(candle.high);
        const low = Number(candle.low);
        const close = Number(candle.close);
        const volume = Number(candle.volume);
        if (![time, open, high, low, close].every(Number.isFinite)) return null;
        return { time, open, high, low, close, volume: Number.isFinite(volume) ? volume : 0 };
      })
      .filter((bar): bar is NonNullable<typeof bar> => bar !== null)
      // The API returns ascending order, but the chart *requires* it and fails
      // loudly rather than sorting for us, so this is not a redundant sort.
      .sort((a, b) => a.time - b.time);

    priceSeries.setData(parsed);
    volumeSeries.setData(
      parsed.map((bar) => ({
        time: bar.time,
        value: bar.volume,
        color: bar.close >= bar.open ? "#26a69a33" : "#ef535033",
      })),
    );
    instance.timeScale().fitContent();

    const observer = new ResizeObserver(([entry]) => {
      instance.applyOptions({ width: entry.contentRect.width });
    });
    observer.observe(container.current);

    return () => {
      observer.disconnect();
      instance.remove();
      chart.current = null;
    };
  }, [candles, height, locale]);

  return <div ref={container} className="w-full" />;
}
