import { Card, Empty } from "@/components/primitives";
import { useI18n } from "@/i18n/context";
import { traderApi } from "@/trader/client";
import { PanelBody } from "@/trader/components";
import { useTraderQuery } from "@/trader/hooks";

interface Review {
  id: string; strategy_id: string; strategy_version: string; pair: string;
  timeframe: string; candle_open: string; generated_at: string;
  outcome: string; reason: string; current: boolean;
  evidence: { kronos?: { projected_return_pct: string } | null; ai?: { score: number } | null };
}

export function BuilderReviews() {
  const { t, n } = useI18n();
  const query = useTraderQuery<Review[]>(["builder-reviews"],
    () => traderApi.GET("/trader/v1/signal-builder/reviews"));
  return <Card title={t("builder.reviews")}>
    <p className="mb-4 max-w-prose text-sm text-muted">{t("builder.reviewsNote")}</p>
    <PanelBody query={query}>{(reviews) => reviews.length === 0 ?
      <Empty message={t("builder.reviewsEmpty")} /> :
      <div className="overflow-x-auto"><table className="w-full min-w-[36rem] text-left text-sm">
        <thead><tr><th className="p-2">{t("builder.strategy")}</th><th className="p-2">{t("builder.candle")}</th>
          <th className="p-2">Kronos</th><th className="p-2">AI</th><th className="p-2">{t("builder.status")}</th></tr></thead>
        <tbody>{reviews.map((review) => <tr key={review.id} className="border-t border-line">
          <td className="p-2">{review.strategy_id}<br /><span className="text-xs text-muted">{review.pair} · {review.timeframe} · {review.strategy_version.slice(-12)}</span></td>
          <td className="p-2">{new Date(review.candle_open).toISOString().slice(0, 16).replace("T", " ")}</td>
          <td className="p-2">{review.evidence.kronos ? `${n(review.evidence.kronos.projected_return_pct, 3)}%` : "—"}</td>
          <td className="p-2">{review.evidence.ai ? `${review.evidence.ai.score}/100` : "—"}</td>
          <td className="p-2">{t(!review.current ? "builder.historical" : review.outcome === "PASS" ? "builder.passed" : "builder.blocked")}</td>
        </tr>)}</tbody>
      </table></div>}
    </PanelBody>
  </Card>;
}
