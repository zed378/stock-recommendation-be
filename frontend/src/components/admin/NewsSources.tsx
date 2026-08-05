import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { useI18n } from "@/i18n/context";
import {
  Button,
  Card,
  Caveat,
  ConfirmDialog,
  Empty,
  ErrorNote,
  Field,
  inputClass,
  Loading,
  Modal,
} from "@/components/primitives";
import type { components } from "@/api/schema";

type Source = components["schemas"]["NewsSourceResponse"];
type TestResult = components["schemas"]["NewsSourceTestResponse"];

/**
 * Starting points, offered rather than inserted.
 *
 * A fresh install has no sources, so news ingestion has nowhere to look - but
 * choosing which publications a platform reads is not a decision to make on
 * someone's behalf by seeding rows into their database. These fill the form;
 * the admin still presses the button.
 */
const SUGGESTIONS: { name: string; url: string; note: string }[] = [
  {
    name: "Google News — per ticker",
    url: "https://news.google.com/rss/search?q={ticker}+saham&hl=id&gl=ID&ceid=ID:id",
    note: "templated",
  },
  {
    name: "Google News — IDX",
    url: "https://news.google.com/rss/search?q=bursa+efek+indonesia&hl=id&gl=ID&ceid=ID:id",
    note: "general",
  },
];

/**
 * The feeds the platform reads news from.
 *
 * This panel exists because the subsystem it configures did not work at all:
 * the only news adapter in the tree was a fixture that manufactured plausible
 * headlines, and it was also the configured default - so ingestion ran, said
 * it succeeded, and stored nothing anybody wrote.
 *
 * Every row therefore carries what happened the last time it was read. A feed
 * that started answering 404 is otherwise indistinguishable from a feed with
 * no news, which is how that went unnoticed.
 */
export function NewsSourcesPanel() {
  const { t, dateTime } = useI18n();
  const queryClient = useQueryClient();

  // `null` is not editing; a Source is editing that one; `"new"` is adding.
  // One value rather than two booleans, because "adding and editing at once"
  // has no meaning and would otherwise have to be prevented by hand.
  const [editing, setEditing] = useState<Source | "new" | null>(null);
  const [deleting, setDeleting] = useState<Source | null>(null);
  const [tested, setTested] = useState<{ source: Source; result: TestResult } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const sources = useQuery({
    queryKey: ["news-sources"],
    queryFn: async () => {
      const { data, error: failed } = await api.GET("/admin/news-sources");
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
      return data ?? [];
    },
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["news-sources"] });

  type Draft = { name: string; feed_url: string; ticker: string | null };

  const save = useMutation({
    mutationFn: async (input: { draft: Draft; id?: string }) => {
      if (input.id) {
        const { error: failed } = await api.PATCH("/admin/news-sources/{source_id}", {
          params: { path: { source_id: input.id } },
          // `ticker` sent explicitly even when null: the route reads the
          // presence of the key to tell "unbind this" from "leave it alone".
          body: input.draft,
        });
        if (failed) throw new Error(errorMessage(failed, t("common.error")));
        return;
      }
      const { error: failed } = await api.POST("/admin/news-sources", {
        body: { ...input.draft, is_active: true },
      });
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
    },
    onSuccess: () => {
      setEditing(null);
      setError(null);
      invalidate();
    },
    onError: (caught: Error) => setError(caught.message),
  });

  const toggle = useMutation({
    mutationFn: async (input: { id: string; is_active: boolean }) => {
      const { error: failed } = await api.PATCH("/admin/news-sources/{source_id}", {
        params: { path: { source_id: input.id } },
        body: { is_active: input.is_active },
      });
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
    },
    onSuccess: invalidate,
    onError: (caught: Error) => setError(caught.message),
  });

  const remove = useMutation({
    mutationFn: async (id: string) => {
      const { error: failed } = await api.DELETE("/admin/news-sources/{source_id}", {
        params: { path: { source_id: id } },
      });
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
    },
    onSuccess: () => {
      setDeleting(null);
      invalidate();
    },
    onError: (caught: Error) => setError(caught.message),
  });

  const probe = useMutation({
    mutationFn: async (source: Source) => {
      const { data, error: failed } = await api.POST("/admin/news-sources/{source_id}/test", {
        params: {
          path: { source_id: source.id },
          // A templated URL needs something to substitute. BBCA is only a
          // probe subject; nothing is stored against it.
          query: source.is_templated ? { ticker: "BBCA" } : {},
        },
      });
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
      return { source, result: data as TestResult };
    },
    onSuccess: (value) => {
      setTested(value);
      invalidate();
    },
    onError: (caught: Error) => setError(caught.message),
  });

  return (
    <Card
      title={t("admin.news.title")}
      action={
        <Button size="sm" variant="ghost" onClick={() => setEditing("new")}>
          {t("admin.news.add")}
        </Button>
      }
    >
      {error && (
        <div className="mb-3">
          <ErrorNote message={error} onRetry={() => setError(null)} />
        </div>
      )}

      {sources.isLoading ? (
        <Loading />
      ) : sources.isError ? (
        <ErrorNote
          message={(sources.error as Error).message}
          onRetry={() => sources.refetch()}
        />
      ) : !sources.data?.length ? (
        <Empty
          message={t("admin.news.empty")}
          hint={t("admin.news.emptyHint")}
          action={
            <Button size="sm" onClick={() => setEditing("new")}>
              {t("admin.news.add")}
            </Button>
          }
        />
      ) : (
        <div className="space-y-2">
          {sources.data.map((source) => (
            <div
              key={source.id}
              className="rounded-md border border-line p-3 text-sm"
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-ink">{source.name}</span>
                    {source.is_templated && (
                      <span className="rounded border border-line px-1.5 py-0.5 text-xs text-muted">
                        {t("admin.news.templated")}
                      </span>
                    )}
                    {source.ticker && (
                      <span className="rounded border border-line px-1.5 py-0.5 font-mono text-xs text-muted">
                        {source.ticker}
                      </span>
                    )}
                    {!source.is_active && (
                      <span className="rounded border border-watch/40 px-1.5 py-0.5 text-xs text-watch">
                        {t("admin.news.off")}
                      </span>
                    )}
                  </div>
                  <div className="mt-1 truncate font-mono text-xs text-faint" title={source.feed_url}>
                    {source.feed_url}
                  </div>
                </div>

                <div className="flex shrink-0 gap-1.5">
                  <Button
                    size="sm"
                    variant="ghost"
                    busy={probe.isPending && probe.variables?.id === source.id}
                    onClick={() => probe.mutate(source)}
                  >
                    {t("admin.news.test")}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setEditing(source)}>
                    {t("admin.news.edit")}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      toggle.mutate({ id: source.id, is_active: !source.is_active })
                    }
                  >
                    {source.is_active ? t("admin.news.disable") : t("admin.news.enable")}
                  </Button>
                  <Button size="sm" variant="danger" onClick={() => setDeleting(source)}>
                    {t("admin.news.remove")}
                  </Button>
                </div>
              </div>

              <LastRun source={source} formatDate={dateTime} />
            </div>
          ))}
        </div>
      )}

      <Caveat>{t("admin.news.caveat")}</Caveat>

      {editing && (
        <SourceDialog
          source={editing === "new" ? null : editing}
          busy={save.isPending}
          onCancel={() => setEditing(null)}
          onConfirm={(draft) =>
            save.mutate({ draft, id: editing === "new" ? undefined : editing.id })
          }
        />
      )}

      {deleting && (
        <ConfirmDialog
          title={t("admin.news.removeTitle")}
          message={t("admin.news.removeWarning", { name: deleting.name })}
          confirmLabel={t("admin.news.remove")}
          destructive
          busy={remove.isPending}
          onCancel={() => setDeleting(null)}
          onConfirm={() => remove.mutate(deleting.id)}
        />
      )}

      {tested && <TestDialog {...tested} onClose={() => setTested(null)} />}
    </Card>
  );
}

/** What happened the last time this feed was read. */
function LastRun({
  source,
  formatDate,
}: {
  source: Source;
  formatDate: (value: string) => string;
}) {
  const { t } = useI18n();

  if (!source.last_fetched_at) {
    return <p className="mt-2 text-xs text-faint">{t("admin.news.neverRead")}</p>;
  }

  const failed = source.last_status === "failed";
  return (
    <div className="mt-2 text-xs">
      <span className={failed ? "text-fall" : "text-muted"}>
        {failed
          ? t("admin.news.lastFailed", { when: formatDate(source.last_fetched_at) })
          : t("admin.news.lastOk", {
              count: source.last_entry_count,
              when: formatDate(source.last_fetched_at),
            })}
      </span>
      {failed && source.last_error && (
        <div className="mt-1 font-mono text-xs text-faint">{source.last_error}</div>
      )}
      {source.consecutive_failures > 1 && (
        <div className="mt-1 text-watch">
          {t("admin.news.failureStreak", { count: source.consecutive_failures })}
        </div>
      )}
    </div>
  );
}

/**
 * Add a source, or change one.
 *
 * One component for both. They are the same act - name it, point it at a feed,
 * optionally bind it to an issuer - and `source` being null is the only
 * difference. Editing used to be impossible: a typo in a URL meant deleting the
 * row and losing its fetch history to recreate it one character different.
 */
function SourceDialog({
  source,
  busy,
  onCancel,
  onConfirm,
}: {
  source: Source | null;
  busy: boolean;
  onCancel: () => void;
  onConfirm: (draft: { name: string; feed_url: string; ticker: string | null }) => void;
}) {
  const { t } = useI18n();
  const [name, setName] = useState(source?.name ?? "");
  const [url, setUrl] = useState(source?.feed_url ?? "");
  const [ticker, setTicker] = useState(source?.ticker ?? "");

  const trimmedUrl = url.trim();
  const valid =
    name.trim().length > 0 && /^https?:\/\//i.test(trimmedUrl) && trimmedUrl.length > 8;
  const templated = trimmedUrl.includes("{ticker}");

  const submit = () =>
    onConfirm({
      name: name.trim(),
      feed_url: trimmedUrl,
      // A templated URL is already per-asset, so any binding it carried is
      // dropped rather than left to contradict the URL.
      ticker: templated ? null : ticker.trim() || null,
    });

  return (
    <Modal
      title={source ? t("admin.news.editTitle", { name: source.name }) : t("admin.news.addTitle")}
      onClose={onCancel}
      footer={
        <>
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            {t("common.cancel")}
          </Button>
          <Button onClick={submit} disabled={!valid} busy={busy}>
            {source ? t("common.save") : t("admin.news.add")}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label={t("admin.news.name")}>
          <input
            className={inputClass}
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={t("admin.news.namePlaceholder")}
            autoFocus
          />
        </Field>

        <Field label={t("admin.news.url")} hint={t("admin.news.urlHint")}>
          <input
            className={inputClass}
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://…/rss"
          />
        </Field>

        {/* Hidden once the URL is templated: binding a per-ticker search feed
            to one asset would be two ways of saying the same thing, and they
            could disagree. */}
        {!templated && (
          <Field label={`${t("admin.news.ticker")} (${t("common.optional")})`} hint={t("admin.news.tickerHint")}>
            <input
              className={`${inputClass} font-mono uppercase`}
              value={ticker}
              onChange={(event) => setTicker(event.target.value.toUpperCase())}
              placeholder="BBCA"
            />
          </Field>
        )}

        {templated && (
          <p className="rounded-md border border-line bg-hover/30 px-3 py-2 text-xs text-muted">
            {t("admin.news.templatedNote")}
          </p>
        )}

        <div>
          <p className="mb-1.5 text-xs font-medium text-muted">
            {t("admin.news.suggestions")}
          </p>
          <div className="space-y-1">
            {SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion.url}
                onClick={() => {
                  setName(suggestion.name);
                  setUrl(suggestion.url);
                }}
                className="block w-full rounded-md border border-line px-2.5 py-1.5 text-left text-xs text-muted transition-colors hover:bg-hover hover:text-ink"
              >
                {suggestion.name}
              </button>
            ))}
          </div>
        </div>
      </div>
    </Modal>
  );
}

/**
 * What the feed actually returned, just now.
 *
 * The sample headlines are the point. A count answers "did something parse";
 * only the headlines answer "is this the feed you meant".
 */
function TestDialog({
  source,
  result,
  onClose,
}: {
  source: Source;
  result: TestResult;
  onClose: () => void;
}) {
  const { t, dateTime } = useI18n();

  return (
    <Modal
      title={t("admin.news.testTitle", { name: source.name })}
      onClose={onClose}
      footer={
        <Button variant="ghost" onClick={onClose}>
          {t("common.close")}
        </Button>
      }
    >
      {result.ok ? (
        <div className="space-y-3">
          <p className="text-ink">{t("admin.news.testOk", { count: result.entries })}</p>
          {result.newest_published_at && (
            <p className="text-xs text-faint">
              {t("admin.news.testNewest", {
                when: dateTime(result.newest_published_at),
              })}
            </p>
          )}
          {(result.sample?.length ?? 0) > 0 && (
            <ul className="space-y-1 text-xs text-muted">
              {(result.sample ?? []).map((headline) => (
                <li key={headline} className="border-l-2 border-line pl-2 leading-relaxed">
                  {headline}
                </li>
              ))}
            </ul>
          )}
          {result.entries === 0 && (
            <p className="text-xs text-watch">{t("admin.news.testEmpty")}</p>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-fall">{t("admin.news.testFailed")}</p>
          <p className="font-mono text-xs text-faint">{result.error}</p>
        </div>
      )}
    </Modal>
  );
}
