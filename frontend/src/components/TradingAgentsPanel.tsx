import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { Button, Card, ErrorNote } from "@/components/primitives";
import type { components } from "@/api/schema";

type TradingDecision = components["schemas"]["TradingDecisionResponse"];

interface DebateTurn {
  round?: number;
  speaker?: string;
  stance?: string;
  thesis?: string;
  key_arguments?: string[];
  counter_points?: string[];
}

interface RiskTurn {
  round?: number;
  speaker?: string;
  risk_posture?: string;
  evaluation?: string;
  risk_arguments?: string[];
  recommended_adjustments?: string[];
}

interface TradingAgentsTrace {
  decision_log_id?: string | null;
  research_debate?: DebateTurn[];
  research_manager?: {
    consensus_bias?: string;
    investment_plan?: string;
    bull_case_summary?: string;
    bear_case_summary?: string;
    key_catalysts?: string[];
    key_risks?: string[];
  } | null;
  trader_proposal?: {
    proposed_stance?: string;
    horizon?: string;
    thesis?: string;
    position_sizing_note?: string;
    invalidation_conditions?: string[];
  } | null;
  risk_debate?: RiskTurn[];
  portfolio_manager?: {
    final_rating?: string;
    decision_summary?: string;
    risk_adjusted_rationale?: string;
    lessons_applied?: string[];
    key_conditions?: string[];
  } | null;
  past_lessons?: Array<{
    scope?: string;
    ticker?: string;
    trade_date?: string;
    final_rating?: string;
    realized_return_pct?: number | null;
    outcome_label?: string | null;
    lesson?: string;
  }>;
}

export function TradingAgentsPanel({
  ticker,
  trace,
}: {
  ticker: string;
  trace?: Record<string, unknown> | null;
}) {
  const queryClient = useQueryClient();
  const data = (trace ?? null) as TradingAgentsTrace | null;

  const decisions = useQuery({
    queryKey: ["trading-decisions", ticker],
    queryFn: async () => {
      const { data: rows, error } = await api.GET("/assets/{ticker}/decisions", {
        params: { path: { ticker } },
      });
      if (error) throw new Error(errorMessage(error, "Failed to load decisions"));
      return (rows ?? []) as TradingDecision[];
    },
  });

  const settle = useMutation({
    mutationFn: async () => {
      const { data: settled, error } = await api.POST("/assets/{ticker}/decisions/settle", {
        params: { path: { ticker } },
      });
      if (error) throw new Error(errorMessage(error, "Failed to settle decisions"));
      return settled;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trading-decisions", ticker] });
    },
  });

  if (!data && (!decisions.data || decisions.data.length === 0)) {
    return null;
  }

  return (
    <div className="space-y-4">
      {data && (
        <>
          {/* Research Debate + Research Manager */}
          <Card>
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-2 border-b border-line pb-2">
                <h3 className="text-sm font-medium text-ink">
                  Research Debate (Bull vs Bear)
                </h3>
                {data.research_manager?.consensus_bias && (
                  <span className="rounded border border-line px-2 py-0.5 text-xs font-medium uppercase text-ink">
                    {data.research_manager.consensus_bias}
                  </span>
                )}
              </div>

              {data.research_debate && data.research_debate.length > 0 && (
                <div className="grid gap-3 md:grid-cols-2">
                  {data.research_debate.map((turn, idx) => (
                    <div
                      key={`${turn.speaker ?? "turn"}-${idx}`}
                      className="rounded border border-line p-3 text-xs space-y-1.5"
                    >
                      <div className="flex items-center justify-between font-medium text-ink">
                        <span>
                          {turn.speaker} {turn.round ? `· R${turn.round}` : ""}
                        </span>
                        {turn.stance && (
                          <span className="uppercase text-faint">{turn.stance}</span>
                        )}
                      </div>
                      {turn.thesis && <p className="text-ink">{turn.thesis}</p>}
                      {turn.key_arguments && turn.key_arguments.length > 0 && (
                        <ul className="list-disc pl-4 text-faint space-y-0.5">
                          {turn.key_arguments.map((arg, i) => (
                            <li key={i}>{arg}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {data.research_manager?.investment_plan && (
                <div className="rounded border border-line p-3 text-xs space-y-1.5">
                  <div className="font-medium text-ink">Research Manager Plan</div>
                  <p className="text-ink">{data.research_manager.investment_plan}</p>
                  {data.research_manager.key_catalysts &&
                    data.research_manager.key_catalysts.length > 0 && (
                      <div className="text-faint">
                        <span className="font-medium text-ink">Catalysts: </span>
                        {data.research_manager.key_catalysts.join(" · ")}
                      </div>
                    )}
                  {data.research_manager.key_risks &&
                    data.research_manager.key_risks.length > 0 && (
                      <div className="text-faint">
                        <span className="font-medium text-ink">Risks: </span>
                        {data.research_manager.key_risks.join(" · ")}
                      </div>
                    )}
                </div>
              )}
            </div>
          </Card>

          {/* Trader Proposal + Risk Committee + Portfolio Manager */}
          <Card>
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-2 border-b border-line pb-2">
                <h3 className="text-sm font-medium text-ink">
                  Trader &amp; Risk Committee Decision
                </h3>
                {data.portfolio_manager?.final_rating && (
                  <span className="rounded border border-line px-2 py-0.5 text-xs font-medium uppercase text-ink">
                    PM: {data.portfolio_manager.final_rating.replace("_", " ")}
                  </span>
                )}
              </div>

              {data.trader_proposal && (
                <div className="rounded border border-line p-3 text-xs space-y-1">
                  <div className="flex items-center justify-between font-medium text-ink">
                    <span>Trader Proposal</span>
                    <span className="uppercase text-faint">
                      {data.trader_proposal.proposed_stance?.replace("_", " ")} ·{" "}
                      {data.trader_proposal.horizon}
                    </span>
                  </div>
                  <p className="text-ink">{data.trader_proposal.thesis}</p>
                  {data.trader_proposal.position_sizing_note && (
                    <p className="text-faint">{data.trader_proposal.position_sizing_note}</p>
                  )}
                </div>
              )}

              {data.risk_debate && data.risk_debate.length > 0 && (
                <div className="grid gap-3 md:grid-cols-3">
                  {data.risk_debate.map((turn, idx) => (
                    <div
                      key={`${turn.speaker ?? "risk"}-${idx}`}
                      className="rounded border border-line p-3 text-xs space-y-1.5"
                    >
                      <div className="font-medium text-ink">{turn.speaker}</div>
                      {turn.evaluation && <p className="text-ink">{turn.evaluation}</p>}
                      {turn.recommended_adjustments &&
                        turn.recommended_adjustments.length > 0 && (
                          <ul className="list-disc pl-4 text-faint space-y-0.5">
                            {turn.recommended_adjustments.map((adj, i) => (
                              <li key={i}>{adj}</li>
                            ))}
                          </ul>
                        )}
                    </div>
                  ))}
                </div>
              )}

              {data.portfolio_manager && (
                <div className="rounded border border-line p-3 text-xs space-y-1.5">
                  <div className="font-medium text-ink">Portfolio Manager Final Rationale</div>
                  <p className="text-ink">{data.portfolio_manager.decision_summary}</p>
                  <p className="text-faint">{data.portfolio_manager.risk_adjusted_rationale}</p>
                  {data.portfolio_manager.lessons_applied &&
                    data.portfolio_manager.lessons_applied.length > 0 && (
                      <div className="text-faint">
                        <span className="font-medium text-ink">Lessons applied: </span>
                        {data.portfolio_manager.lessons_applied.join(" · ")}
                      </div>
                    )}
                </div>
              )}
            </div>
          </Card>
        </>
      )}

      {/* Decision Memory & Settlement Log */}
      {decisions.data && decisions.data.length > 0 && (
        <Card>
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-2 border-b border-line pb-2">
              <h3 className="text-sm font-medium text-ink">
                Decision Memory &amp; Reflection Log
              </h3>
              <Button
                variant="ghost"
                busy={settle.isPending}
                onClick={() => settle.mutate()}
              >
                Settle Matured
              </Button>
            </div>
            {settle.isError && <ErrorNote message={(settle.error as Error).message} />}
            <div className="space-y-2">
              {decisions.data.slice(0, 5).map((d) => (
                <div
                  key={d.id}
                  className="rounded border border-line p-2.5 text-xs space-y-1"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium text-ink uppercase">
                      {d.final_rating.replace("_", " ")} ({Math.round(d.confidence)}%)
                    </span>
                    <span className="text-faint">
                      {new Date(d.trade_date).toLocaleDateString()}
                      {d.realized_return_pct !== null && d.realized_return_pct !== undefined
                        ? ` · ${d.realized_return_pct >= 0 ? "+" : ""}${d.realized_return_pct.toFixed(2)}% (${d.outcome_label ?? "settled"})`
                        : " · pending settlement"}
                    </span>
                  </div>
                  <p className="text-ink">{d.portfolio_decision}</p>
                  {d.reflection_lesson && (
                    <p className="text-faint">
                      <span className="font-medium text-ink">Lesson: </span>
                      {d.reflection_lesson}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
