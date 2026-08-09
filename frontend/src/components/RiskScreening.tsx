import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { useI18n, type MessageKey } from "@/i18n/context";
import { useToast } from "@/components/toastContext";
import { Button, Card, Caveat, ErrorNote, Loading } from "@/components/primitives";

interface QuestionShape {
  key: string;
  dimension: string;
  options: string[];
}

/**
 * The risk questionnaire, and the result it derives.
 *
 * Asking "are you conservative, moderate or aggressive?" is the cheapest
 * possible instrument and the least reliable: the question invites an answer
 * about self-image rather than behaviour. These ask about situations instead,
 * and the label is derived.
 *
 * The two scores are shown alongside the label, because "you answered boldly
 * but have no buffer" is the useful sentence and a bare word cannot say it.
 */
export function RiskScreening() {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const instrument = useQuery({
    queryKey: ["risk-questions"],
    queryFn: async () => {
      const { data, error: failed } = await api.GET("/me/risk-profile/questions");
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
      return data as unknown as { questions: QuestionShape[]; caveat: string };
    },
  });

  const stored = useQuery({
    queryKey: ["risk-profile"],
    queryFn: async () => {
      const { data, error: failed } = await api.GET("/me/risk-profile");
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
      return data;
    },
  });

  const submit = useMutation({
    mutationFn: async () => {
      const { data, error: failed } = await api.POST("/me/risk-profile", {
        body: { answers },
      });
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
      return data;
    },
    onSuccess: () => {
      setError(null);
      setOpen(false);
      toast.show({ title: t("risk.saved"), tone: "success" });
      // The derived appetite and horizon land in the preferences too, so that
      // card has to reload or it keeps showing what the reader had before.
      queryClient.invalidateQueries({ queryKey: ["risk-profile"] });
      queryClient.invalidateQueries({ queryKey: ["preferences"] });
    },
    onError: (caught: Error) => setError(caught.message),
  });

  if (instrument.isLoading || stored.isLoading) return <Loading />;

  const questions = instrument.data?.questions ?? [];
  const result = stored.data;
  const answered = questions.filter((question) => answers[question.key]).length;
  const complete = answered === questions.length && questions.length > 0;

  return (
    <Card title={t("risk.title")}>
      <p className="mb-4 text-sm text-muted">{t("risk.intro")}</p>

      {error && (
        <div className="mb-3">
          <ErrorNote message={error} onRetry={() => setError(null)} />
        </div>
      )}

      {result && !open && (
        <div className="mb-4 rounded-lg border border-line bg-surface/40 px-4 py-3">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-sm text-faint">{t("risk.yourProfile")}</span>
            <span className="text-base font-semibold text-ink">
              {t(`profile.risk_appetite.${result.risk_appetite}` as MessageKey)}
            </span>
            <span className="text-sm text-muted">
              · {t(`profile.investment_horizon.${result.investment_horizon}` as MessageKey)}
            </span>
          </div>

          {/* Both scores, always. The label alone cannot distinguish someone
              cautious by temperament from someone with no room to be
              otherwise, and those two readers need different things said. */}
          <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted">
            <span>
              {t("risk.tolerance")}{" "}
              <span className="font-mono tnum text-ink">{result.tolerance_score}/9</span>
            </span>
            <span>
              {t("risk.capacity")}{" "}
              <span className="font-mono tnum text-ink">{result.capacity_score}/9</span>
            </span>
          </div>
          <p className="mt-2 text-xs leading-relaxed text-faint">
            {t(`risk.limitedBy.${result.limited_by}` as MessageKey)}
          </p>
        </div>
      )}

      {!open ? (
        <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>
          {result ? t("risk.retake") : t("risk.take")}
        </Button>
      ) : (
        <div className="space-y-5">
          {questions.map((question, index) => (
            <div key={question.key}>
              <p className="mb-1 text-sm font-medium text-ink">
                <span className="mr-2 font-mono text-xs text-faint">{index + 1}</span>
                {t(`risk.q.${question.key}` as MessageKey)}
              </p>
              <div className="flex flex-col gap-1.5">
                {question.options.map((option) => {
                  const active = answers[question.key] === option;
                  return (
                    <button
                      key={option}
                      type="button"
                      onClick={() =>
                        setAnswers((current) => ({ ...current, [question.key]: option }))
                      }
                      className={`rounded-md border px-3 py-2 text-left text-sm transition-colors ${
                        active
                          ? "border-rise/50 bg-rise/10 text-ink"
                          : "border-line text-muted hover:text-ink"
                      }`}
                    >
                      {t(`risk.a.${question.key}.${option}` as MessageKey)}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}

          <div className="flex flex-wrap items-center gap-3">
            <Button
              busy={submit.isPending}
              // Disabled rather than scoring what is there. A skipped question
              // is not a cautious answer, and treating it as one would quietly
              // mark somebody conservative for finding a question unclear.
              disabled={!complete}
              onClick={() => submit.mutate()}
            >
              {t("risk.submit")}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
              {t("common.cancel")}
            </Button>
            <span className="text-xs text-faint">
              {answered}/{questions.length}
            </span>
          </div>
        </div>
      )}

      <Caveat>{instrument.data?.caveat}</Caveat>
    </Card>
  );
}
