import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { useI18n } from "@/i18n/context";
import {
  Button,
  Card,
  Caveat,
  ErrorNote,
  inputClass,
  Loading,
} from "@/components/primitives";

interface Turn {
  question: string;
  answer?: string;
  sufficiency?: string;
  followUps?: string[];
}

/**
 * Open questions about trading, with no ticker required.
 *
 * A screen of its own rather than a fourth tab on Ask AI, and the reason is
 * what the ticker field does to the question. On that screen the box is there,
 * empty, above every mode - so a question about the market reads as a question
 * missing its subject, and two of the three modes refuse outright without one.
 * Here there is no field to leave empty.
 *
 * The scope is trading and this exchange. That is enforced in the prompt
 * rather than by a classifier: a classifier is a component that can be wrong
 * and needs its own evaluation, while an instruction to decline is one the
 * model follows or visibly does not.
 */
export function MarketChat() {
  const { t } = useI18n();
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [error, setError] = useState<string | null>(null);

  const ask = useMutation({
    mutationFn: async (asked: string) => {
      const { data, error: failed } = await api.POST("/chat", {
        body: { question: asked, mode: "market" },
      });
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
      return data;
    },
    onSuccess: (data, asked) => {
      setError(null);
      setTurns((current) => [
        ...current,
        {
          question: asked,
          answer: data?.answer ?? "",
          sufficiency: data?.data_sufficiency ?? undefined,
          followUps: data?.follow_up_questions ?? [],
        },
      ]);
    },
    onError: (caught: Error) => setError(caught.message),
  });

  const send = () => {
    const asked = question.trim();
    if (!asked) return;
    setQuestion("");
    ask.mutate(asked);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-ink">{t("marketChat.title")}</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">{t("marketChat.intro")}</p>
      </div>

      {error && <ErrorNote message={error} onRetry={() => setError(null)} />}

      {turns.length === 0 && !ask.isPending && (
        <Card title={t("marketChat.examplesTitle")}>
          {/* Examples rather than an empty box. The mode's boundary is easier
              to show than to describe, and every one of these is a question
              the digest can actually answer. */}
          <ul className="space-y-2">
            {["budget", "moving", "oversold", "concept"].map((key) => (
              <li key={key}>
                <button
                  type="button"
                  onClick={() => setQuestion(t(`marketChat.example.${key}` as never))}
                  className="text-left text-sm text-muted transition-colors hover:text-ink"
                >
                  &ldquo;{t(`marketChat.example.${key}` as never)}&rdquo;
                </button>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {turns.map((turn, index) => (
        <div key={index} className="space-y-3">
          <div className="ml-auto max-w-2xl rounded-lg border border-line bg-raised px-4 py-3">
            <p className="text-sm text-ink">{turn.question}</p>
          </div>

          <Card>
            {/* Said before the answer, not after. "The platform has not
                scanned yet" changes how every sentence below should be read,
                and a reader who learns it at the end has already believed the
                middle. */}
            {turn.sufficiency && turn.sufficiency !== "sufficient" && (
              <p className="mb-3 rounded-md border border-watch/25 bg-watch/5 px-3 py-2 text-xs text-watch">
                {t("marketChat.thinData")}
              </p>
            )}
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink/90">
              {turn.answer}
            </p>

            {(turn.followUps ?? []).length > 0 && (
              <div className="mt-4 border-t border-line pt-3">
                <p className="mb-1.5 text-xs text-faint">{t("marketChat.followUps")}</p>
                <ul className="space-y-1">
                  {turn.followUps?.map((followUp) => (
                    <li key={followUp}>
                      <button
                        type="button"
                        onClick={() => setQuestion(followUp)}
                        className="text-left text-sm text-muted transition-colors hover:text-ink"
                      >
                        {followUp}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Card>
        </div>
      ))}

      {ask.isPending && <Loading label={t("marketChat.thinking")} />}

      <div className="flex flex-wrap gap-2">
        <input
          className={`${inputClass} min-w-64 flex-1`}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              send();
            }
          }}
          placeholder={t("marketChat.placeholder")}
          aria-label={t("marketChat.placeholder")}
        />
        <Button busy={ask.isPending} disabled={!question.trim()} onClick={send}>
          {t("chat.send")}
        </Button>
      </div>

      <Caveat>{t("marketChat.caveat")}</Caveat>
    </div>
  );
}
