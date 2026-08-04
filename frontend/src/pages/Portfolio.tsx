import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { useI18n } from "@/i18n/context";
import {
  Button,
  Card,
  Caveat,
  Empty,
  ErrorNote,
  Field,
  inputClass,
  Loading,
  Stat,
} from "@/components/primitives";

export function Portfolio() {
  const { t, n, money } = useI18n();
  const queryClient = useQueryClient();

  const [ticker, setTicker] = useState("");
  const [quantity, setQuantity] = useState("");
  const [price, setPrice] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const portfolio = useQuery({
    queryKey: ["portfolio"],
    queryFn: async () => {
      const { data, error } = await api.GET("/portfolio");
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data;
    },
  });

  const addHolding = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/portfolio/holdings", {
        body: {
          ticker: ticker.trim().toUpperCase(),
          exchange: "IDX",
          quantity,
          average_price: price,
          input_method: "manual",
        },
      });
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data;
    },
    onSuccess: () => {
      setTicker("");
      setQuantity("");
      setPrice("");
      setFormError(null);
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
    },
    onError: (caught: Error) => setFormError(caught.message),
  });

  const removeHolding = useMutation({
    mutationFn: async (id: string) => {
      const { error } = await api.DELETE("/portfolio/holdings/{holding_id}", {
        params: { path: { holding_id: id } },
      });
      if (error) throw new Error(errorMessage(error, t("common.error")));
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["portfolio"] }),
  });

  const analyse = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/portfolio/analysis");
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data;
    },
  });

  const holdings = portfolio.data?.holdings ?? [];
  const metrics = (analyse.data?.metrics ?? {}) as Record<string, unknown>;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-lg font-semibold text-ink">{t("portfolio.title")}</h1>
        {holdings.length > 0 && (
          <Button busy={analyse.isPending} onClick={() => analyse.mutate()}>
            {analyse.isPending ? t("portfolio.analysing") : t("portfolio.analyse")}
          </Button>
        )}
      </div>

      {/* Stated once, prominently, because it is a product constraint rather
          than a limitation: nothing here syncs from a broker, by design. */}
      <p className="rounded-md border border-line bg-raised px-3 py-2 text-xs text-muted">
        {t("portfolio.manualOnly")}
      </p>

      <Card title={t("portfolio.addHolding")}>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (ticker.trim() && quantity && price) addHolding.mutate();
          }}
          className="flex flex-wrap items-end gap-3"
        >
          <div className="w-36">
            <Field label={t("portfolio.ticker")}>
              <input
                className={`${inputClass} font-mono uppercase`}
                value={ticker}
                onChange={(e) => setTicker(e.target.value)}
                required
              />
            </Field>
          </div>
          <div className="w-36">
            <Field label={t("portfolio.quantity")}>
              <input
                className={`${inputClass} font-mono tnum`}
                type="number"
                step="any"
                min="0"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
                required
              />
            </Field>
          </div>
          <div className="w-40">
            <Field label={t("portfolio.avgPrice")}>
              <input
                className={`${inputClass} font-mono tnum`}
                type="number"
                step="any"
                min="0"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                required
              />
            </Field>
          </div>
          <Button type="submit" busy={addHolding.isPending}>
            {t("portfolio.addHolding")}
          </Button>
        </form>
        {formError && (
          <div className="mt-3">
            <ErrorNote message={formError} />
          </div>
        )}
      </Card>

      <Card>
        {portfolio.isLoading ? (
          <Loading />
        ) : portfolio.isError ? (
          <ErrorNote
            message={(portfolio.error as Error).message}
            onRetry={() => portfolio.refetch()}
          />
        ) : !holdings.length ? (
          <Empty message={t("portfolio.empty")} hint={t("portfolio.emptyHint")} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs text-faint">
                  <th className="pb-2 pr-4 font-medium">{t("portfolio.ticker")}</th>
                  <th className="pb-2 pr-4 text-right font-medium">
                    {t("portfolio.quantity")}
                  </th>
                  <th className="pb-2 pr-4 text-right font-medium">
                    {t("portfolio.avgPrice")}
                  </th>
                  <th className="pb-2 pr-4 text-right font-medium">{t("portfolio.value")}</th>
                  <th className="pb-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {holdings.map((holding) => (
                  <tr key={holding.id}>
                    <td className="py-2.5 pr-4">
                      <Link
                        to={`/assets/${holding.ticker}`}
                        className="font-mono text-ink hover:text-rise"
                      >
                        {holding.ticker}
                      </Link>
                    </td>
                    <td className="py-2.5 pr-4 text-right font-mono tnum text-ink/90">
                      {n(holding.quantity, 0)}
                    </td>
                    <td className="py-2.5 pr-4 text-right font-mono tnum text-ink/90">
                      {money(holding.average_price)}
                    </td>
                    <td className="py-2.5 pr-4 text-right font-mono tnum text-ink/90">
                      {money(Number(holding.quantity) * Number(holding.average_price))}
                    </td>
                    <td className="py-2.5 text-right">
                      <Button
                        variant="danger"
                        size="sm"
                        busy={
                          removeHolding.isPending && removeHolding.variables === holding.id
                        }
                        onClick={() => removeHolding.mutate(holding.id)}
                      >
                        {t("portfolio.remove")}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {analyse.isError && <ErrorNote message={(analyse.error as Error).message} />}

      {analyse.data && (
        <>
          <Card title={t("portfolio.concentration")}>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
              {Object.entries(metrics)
                .filter(([, value]) => typeof value === "number" || typeof value === "string")
                .map(([key, value]) => (
                  <Stat
                    key={key}
                    label={key.replace(/_/g, " ")}
                    value={typeof value === "number" ? n(value, 4) : String(value)}
                  />
                ))}
            </dl>
            {/* An unpriced holding is flagged rather than silently valued at
                zero, which would understate the portfolio without saying so. */}
            <Caveat>{t("portfolio.unpricedNote")}</Caveat>
          </Card>

          {Array.isArray(analyse.data.skipped) && analyse.data.skipped.length > 0 && (
            <Card title={t("analysis.skipped")}>
              <ul className="space-y-1 text-xs text-muted">
                {analyse.data.skipped.map((entry: unknown, index: number) => (
                  <li key={index}>
                    {typeof entry === "string" ? entry : JSON.stringify(entry)}
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
