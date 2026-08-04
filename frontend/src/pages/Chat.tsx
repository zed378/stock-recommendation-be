import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { useI18n } from "@/i18n/context";
import {
  Button,
  Card,
  Caveat,
  Empty,
  ErrorNote,
  inputClass,
  Loading,
} from "@/components/primitives";
import type { components } from "@/api/schema";

type ChatMode = components["schemas"]["ChatMode"];
type ChatResponse = components["schemas"]["ChatResponse"];

interface Turn {
  question: string;
  answer: ChatResponse | null;
}

const MODES: ChatMode[] = ["learn", "research", "knowledge"];

export function Chat() {
  const { t } = useI18n();
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<ChatMode>("learn");
  const [ticker, setTicker] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);

  const ask = useMutation({
    mutationFn: async (asked: string) => {
      const { data, error } = await api.POST("/chat", {
        body: { question: asked, mode, ticker: ticker.trim().toUpperCase() || null },
      });
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data!;
    },
    onSuccess: (data) => {
      setTurns((current) =>
        current.map((turn, index) =>
          index === current.length - 1 ? { ...turn, answer: data } : turn,
        ),
      );
    },
  });

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const asked = question.trim();
    if (!asked) return;
    setTurns((current) => [...current, { question: asked, answer: null }]);
    setQuestion("");
    ask.mutate(asked);
  }

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold text-ink">{t("chat.title")}</h1>

      <div className="space-y-4">
        {turns.length === 0 && (
          <Card>
            <Empty message={t("chat.empty")} hint={t("chat.emptyHint")} />
          </Card>
        )}

        {turns.map((turn, index) => (
          <div key={index} className="space-y-3">
            <div className="flex justify-end">
              <p className="max-w-2xl rounded-lg border border-line bg-raised px-3.5 py-2.5 text-sm text-ink/90">
                {turn.question}
              </p>
            </div>

            {turn.answer ? (
              <Answer answer={turn.answer} />
            ) : ask.isError && index === turns.length - 1 ? (
              <ErrorNote message={(ask.error as Error).message} />
            ) : (
              <Loading label={t("chat.sending")} />
            )}
          </div>
        ))}
      </div>

      <form onSubmit={submit} className="sticky bottom-4 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex overflow-hidden rounded-md border border-line">
            {MODES.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setMode(option)}
                className={`px-2.5 py-1 text-xs transition-colors ${
                  mode === option ? "bg-hover text-ink" : "text-faint hover:text-muted"
                }`}
              >
                {option}
              </button>
            ))}
          </div>
          <input
            className={`${inputClass} w-32 font-mono uppercase`}
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            placeholder={t("portfolio.ticker")}
          />
        </div>

        <div className="flex gap-2">
          <input
            className={inputClass}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder={t("chat.placeholder")}
          />
          <Button type="submit" busy={ask.isPending}>
            {ask.isPending ? t("chat.sending") : t("chat.send")}
          </Button>
        </div>
      </form>
    </div>
  );
}

function Answer({ answer }: { answer: ChatResponse }) {
  const { t } = useI18n();

  return (
    <Card>
      <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink/90">
        {answer.answer}
      </p>

      {answer.follow_up_questions?.length ? (
        <div className="mt-4 border-t border-line pt-3">
          <p className="mb-1.5 text-xs text-faint">Follow-up</p>
          <ul className="space-y-1">
            {answer.follow_up_questions.map((item, index) => (
              <li key={index} className="text-xs text-muted">
                {item}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line pt-3 text-xs text-faint">
        <span className="font-mono">{answer.agent}</span>
        {answer.model && <span className="font-mono">{answer.model}</span>}
        {answer.prompt_version && <span className="font-mono">{answer.prompt_version}</span>}
        {answer.sources_used?.length ? (
          <span>{answer.sources_used.length} sources</span>
        ) : null}
      </div>

      {/* The backend reports how much evidence it actually had. Surfacing it
          beside the answer is what stops a confident-sounding paragraph built
          on nothing from reading like one built on something. */}
      {answer.data_sufficiency && (
        <Caveat>
          {t("analysis.skippedNote").split(".")[0]} — {answer.data_sufficiency}
        </Caveat>
      )}
    </Card>
  );
}
