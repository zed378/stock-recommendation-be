import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { Button, Card, ErrorNote, inlineControlClass } from "@/components/primitives";
import type { components } from "@/api/schema";

type Timeframe = components["schemas"]["Timeframe"];
type KronosForecast = components["schemas"]["KronosForecastResponse"];

export function KronosForecastPanel({
  ticker,
  timeframe,
}: {
  ticker: string;
  timeframe: Timeframe;
}) {
  const [predLen, setPredLen] = useState<number>(5);
  const [forecast, setForecast] = useState<KronosForecast | null>(null);

  const runForecast = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/assets/{ticker}/forecast", {
        params: { path: { ticker } },
        body: {
          timeframe,
          exchange: "IDX",
          pred_len: predLen,
          temperature: 1.0,
          top_p: 0.9,
          sample_count: 1,
        },
      });
      if (error) throw new Error(errorMessage(error, "Kronos forecast failed"));
      return data as KronosForecast;
    },
    onSuccess: (data) => {
      setForecast(data);
    },
  });

  return (
    <Card>
      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line pb-2">
          <div>
            <h3 className="text-sm font-medium text-ink">
              Kronos-base OHLCV Forecast
            </h3>
            <p className="text-xs text-faint">
              NeoQuasar/Kronos-base candlestick sequence projection
            </p>
          </div>
          <div className="flex items-center gap-2">
            <select
              className={`${inlineControlClass} text-xs`}
              value={predLen}
              disabled={runForecast.isPending}
              onChange={(e) => setPredLen(Number(e.target.value))}
              aria-label="Forecast horizon bars"
            >
              <option value={5}>5 bars</option>
              <option value={10}>10 bars</option>
              <option value={20}>20 bars</option>
            </select>
            <Button
              variant="ghost"
              busy={runForecast.isPending}
              onClick={() => runForecast.mutate()}
            >
              {runForecast.isPending ? "Forecasting..." : "Run Kronos Forecast"}
            </Button>
          </div>
        </div>

        {runForecast.isError && (
          <ErrorNote message={(runForecast.error as Error).message} />
        )}

        {forecast && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
              <span className="text-faint">
                Last close:{" "}
                <span className="font-medium text-ink">{forecast.last_close.toFixed(2)}</span>
                {" → "}Projected close:{" "}
                <span className="font-medium text-ink">{forecast.projected_close.toFixed(2)}</span>
              </span>
              <span className="rounded border border-line px-2 py-0.5 font-medium uppercase text-ink">
                {forecast.direction_bias} (
                {forecast.projected_return_pct >= 0 ? "+" : ""}
                {forecast.projected_return_pct.toFixed(2)}%)
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-line text-faint">
                    <th className="py-1.5 pr-3 font-medium">Date</th>
                    <th className="py-1.5 pr-3 font-medium">Open</th>
                    <th className="py-1.5 pr-3 font-medium">High</th>
                    <th className="py-1.5 pr-3 font-medium">Low</th>
                    <th className="py-1.5 pr-3 font-medium">Close</th>
                    <th className="py-1.5 font-medium">Volume</th>
                  </tr>
                </thead>
                <tbody>
                  {forecast.bars.map((bar, idx) => (
                    <tr key={idx} className="border-b border-line/60 text-ink">
                      <td className="py-1.5 pr-3 text-faint">
                        {new Date(bar.timestamp).toLocaleDateString()}
                      </td>
                      <td className="py-1.5 pr-3">{bar.open.toFixed(2)}</td>
                      <td className="py-1.5 pr-3">{bar.high.toFixed(2)}</td>
                      <td className="py-1.5 pr-3">{bar.low.toFixed(2)}</td>
                      <td className="py-1.5 pr-3 font-medium">{bar.close.toFixed(2)}</td>
                      <td className="py-1.5 text-faint">{Math.round(bar.volume).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}
