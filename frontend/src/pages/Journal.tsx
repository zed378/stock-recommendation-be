import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { useI18n } from "@/i18n/context";
import {
  Button,
  Card,
  Empty,
  ErrorNote,
  Field,
  inputClass,
  Loading,
  Stat,
} from "@/components/primitives";
import { TranslateToggle } from "@/components/TranslateToggle";

export function Journal() {
  const { t, dateTime, date } = useI18n();
  const queryClient = useQueryClient();

  const [decision, setDecision] = useState("");
  const [note, setNote] = useState("");
  const [ticker, setTicker] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const entries = useQuery({
    queryKey: ["journal"],
    queryFn: async () => {
      const { data, error } = await api.GET("/journal");
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data ?? [];
    },
  });

  const summary = useQuery({
    queryKey: ["journal-summary"],
    queryFn: async () => {
      const { data, error } = await api.GET("/journal/summary");
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data;
    },
  });

  const add = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/journal", {
        body: {
          decision: decision.trim(),
          note: note.trim() || null,
          ticker: ticker.trim().toUpperCase() || null,
          exchange: "IDX",
          recommendation_ref: null,
        },
      });
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data;
    },
    onSuccess: () => {
      setDecision("");
      setNote("");
      setTicker("");
      setFormError(null);
      queryClient.invalidateQueries({ queryKey: ["journal"] });
      queryClient.invalidateQueries({ queryKey: ["journal-summary"] });
    },
    onError: (caught: Error) => setFormError(caught.message),
  });

  const remove = useMutation({
    mutationFn: async (id: string) => {
      const { error } = await api.DELETE("/journal/{entry_id}", {
        params: { path: { entry_id: id } },
      });
      if (error) throw new Error(errorMessage(error, t("common.error")));
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["journal"] });
      queryClient.invalidateQueries({ queryKey: ["journal-summary"] });
    },
  });

  const reflect = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/journal/reflection");
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data as Record<string, unknown>;
    },
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-lg font-semibold text-ink">{t("journal.title")}</h1>
        {entries.data?.length ? (
          <Button variant="ghost" busy={reflect.isPending} onClick={() => reflect.mutate()}>
            {reflect.isPending ? t("journal.reflecting") : t("journal.reflection")}
          </Button>
        ) : null}
      </div>

      {summary.data && summary.data.entries > 0 && (
        <Card title={t("journal.summary")}>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
            <Stat label={t("journal.title")} value={summary.data.entries} />
            <Stat
              label="Linked to a recommendation"
              value={summary.data.linked_to_recommendation}
            />
            <Stat label="First entry" value={date(summary.data.first_entry_at)} />
          </dl>
        </Card>
      )}

      <Card title={t("journal.add")}>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (decision.trim()) add.mutate();
          }}
          className="space-y-3"
        >
          <div className="flex flex-wrap gap-3">
            <div className="w-36">
              <Field label={`${t("portfolio.ticker")} (${t("common.optional")})`}>
                <input
                  className={`${inputClass} font-mono uppercase`}
                  value={ticker}
                  onChange={(e) => setTicker(e.target.value)}
                />
              </Field>
            </div>
            <div className="min-w-56 flex-1">
              <Field label={t("journal.content")}>
                <input
                  className={inputClass}
                  value={decision}
                  onChange={(e) => setDecision(e.target.value)}
                  placeholder={t("journal.contentPlaceholder")}
                  required
                />
              </Field>
            </div>
          </div>
          <Field label={`${t("journal.note")} (${t("common.optional")})`}>
            <textarea
              className={`${inputClass} min-h-20 resize-y`}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={4000}
            />
          </Field>
          <Button type="submit" busy={add.isPending}>
            {add.isPending ? t("common.saving") : t("journal.add")}
          </Button>
        </form>
        {formError && (
          <div className="mt-3">
            <ErrorNote message={formError} />
          </div>
        )}
      </Card>

      {reflect.isError && <ErrorNote message={(reflect.error as Error).message} />}
      {reflect.data && (
        <Card title={t("journal.reflection")}>
          {/* `isPersonal` routes the translation through the sensitive path:
              a journal entry must not reach a provider the analysis itself
              would have been refused to. */}
          <TranslateToggle fields={reflect.data} isPersonal>
            {(rendered) => (
              <div className="space-y-3">
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink/90">
                  {String(rendered.summary ?? rendered.answer ?? "")}
                </p>

                {Array.isArray(rendered.patterns) && rendered.patterns.length > 0 && (
                  <ul className="space-y-1.5">
                    {(rendered.patterns as string[]).map((line, index) => (
                      <li
                        key={index}
                        className="relative pl-4 text-sm leading-relaxed text-ink/85 before:absolute before:left-0 before:top-2 before:size-1.5 before:rounded-full before:bg-muted/60"
                      >
                        {line}
                      </li>
                    ))}
                  </ul>
                )}

                {/* What the reflection could *not* conclude, shown as
                    prominently as what it could. An agent that says "no
                    outcomes are recorded, so I cannot assess discipline" is
                    doing the most useful thing it does. */}
                {Array.isArray(rendered.insufficient_evidence_for) &&
                  rendered.insufficient_evidence_for.length > 0 && (
                    <div className="border-t border-line pt-3">
                      <p className="mb-1.5 text-xs text-faint">
                        {t("analysis.skipped")}
                      </p>
                      <ul className="space-y-1">
                        {(rendered.insufficient_evidence_for as string[]).map(
                          (line, index) => (
                            <li key={index} className="text-xs leading-relaxed text-watch">
                              {line}
                            </li>
                          ),
                        )}
                      </ul>
                    </div>
                  )}
              </div>
            )}
          </TranslateToggle>
        </Card>
      )}

      <Card>
        {entries.isLoading ? (
          <Loading />
        ) : entries.isError ? (
          <ErrorNote
            message={(entries.error as Error).message}
            onRetry={() => entries.refetch()}
          />
        ) : !entries.data?.length ? (
          <Empty message={t("journal.empty")} hint={t("journal.emptyHint")} />
        ) : (
          <ul className="divide-y divide-line">
            {entries.data.map((entry) => (
              <li key={entry.id} className="py-3 first:pt-0 last:pb-0">
                <div className="flex items-baseline gap-3">
                  {entry.ticker && (
                    <span className="font-mono text-sm text-rise">{entry.ticker}</span>
                  )}
                  <p className="flex-1 text-sm text-ink/90">{entry.decision}</p>
                  <span className="shrink-0 text-xs text-faint">
                    {dateTime(entry.created_at)}
                  </span>
                  <Button
                    variant="danger"
                    size="sm"
                    busy={remove.isPending && remove.variables === entry.id}
                    onClick={() => remove.mutate(entry.id)}
                  >
                    {t("journal.delete")}
                  </Button>
                </div>
                {entry.note && (
                  <p className="mt-1.5 whitespace-pre-wrap text-xs leading-relaxed text-muted">
                    {entry.note}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
