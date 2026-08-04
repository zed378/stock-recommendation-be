import { useEffect, useMemo, useState } from "react";
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
} from "@/components/primitives";
import type { components } from "@/api/schema";

type Item = components["schemas"]["WatchlistItemResponse"];

const STORAGE_KEY = "aidss.watchlist.collapsed";

/**
 * Remember which groups are shut, not which are open.
 *
 * The difference matters the first time a new category appears: storing the
 * open ones would collapse anything the user has never seen, and a group they
 * just created would arrive shut for no reason they could explain.
 */
function loadCollapsed(): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

export function Watchlist() {
  const { t, dateTime } = useI18n();
  const queryClient = useQueryClient();

  const [ticker, setTicker] = useState("");
  const [note, setNote] = useState("");
  const [category, setCategory] = useState("");
  const [addError, setAddError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(loadCollapsed);

  // Debounced so typing a ticker does not fire a request per keystroke. 250ms
  // is under the threshold where a search feels lagged and well above the
  // interval between keys.
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query.trim()), 250);
    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...collapsed]));
  }, [collapsed]);

  const searching = debounced.length > 0;

  const items = useQuery({
    queryKey: searching ? ["watchlist", "search", debounced] : ["watchlist"],
    queryFn: async () => {
      if (searching) {
        const { data, error } = await api.GET("/watchlist/search", {
          params: { query: { q: debounced } },
        });
        if (error) throw new Error(errorMessage(error, t("common.error")));
        return data ?? [];
      }
      const { data, error } = await api.GET("/watchlist");
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data ?? [];
    },
    // Keeps the previous rows on screen while a new search resolves, so the
    // list does not blink to empty between keystrokes.
    placeholderData: (previous) => previous,
  });

  const categories = useQuery({
    queryKey: ["watchlist-categories"],
    queryFn: async () => {
      const { data, error } = await api.GET("/watchlist/categories");
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data ?? [];
    },
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["watchlist"] });
    queryClient.invalidateQueries({ queryKey: ["watchlist-categories"] });
  };

  const add = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/watchlist", {
        body: {
          ticker: ticker.trim().toUpperCase(),
          exchange: "IDX",
          note: note.trim() || null,
          category: category.trim() || "Default",
        },
      });
      if (error) throw new Error(errorMessage(error, t("watchlist.addFailed")));
      return data;
    },
    onSuccess: () => {
      setTicker("");
      setNote("");
      setAddError(null);
      invalidate();
    },
    onError: (caught: Error) => setAddError(caught.message),
  });

  const remove = useMutation({
    mutationFn: async (id: string) => {
      const { error } = await api.DELETE("/watchlist/{item_id}", {
        params: { path: { item_id: id } },
      });
      if (error) throw new Error(errorMessage(error, t("common.error")));
    },
    onSuccess: invalidate,
  });

  const move = useMutation({
    mutationFn: async ({ id, to }: { id: string; to: string }) => {
      const { error } = await api.PATCH("/watchlist/{item_id}", {
        params: { path: { item_id: id } },
        body: { category: to },
      });
      if (error) throw new Error(errorMessage(error, t("common.error")));
    },
    onSuccess: invalidate,
  });

  /**
   * Group the rows client-side.
   *
   * The API returns them ordered by category already, and grouping here means
   * a search result set is grouped the same way the full list is - one code
   * path, so the two cannot drift into looking different.
   *
   * Empty categories come from the categories query, because a group with no
   * members produces no rows to group.
   */
  const groups = useMemo(() => {
    const byCategory = new Map<string, Item[]>();
    for (const row of categories.data ?? []) byCategory.set(row.name, []);
    for (const item of items.data ?? []) {
      const bucket = byCategory.get(item.category) ?? [];
      bucket.push(item);
      byCategory.set(item.category, bucket);
    }
    // While searching, an empty group is noise: it says nothing about the
    // query and pushes the matches off the screen.
    const entries = [...byCategory.entries()].filter(
      ([, rows]) => !searching || rows.length > 0,
    );
    return entries.sort(([a], [b]) => a.localeCompare(b));
  }, [items.data, categories.data, searching]);

  const total = items.data?.length ?? 0;
  const allCollapsed = groups.length > 0 && groups.every(([name]) => collapsed.has(name));

  const toggle = (name: string) =>
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-lg font-semibold text-ink">{t("watchlist.title")}</h1>
        {groups.length > 1 && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() =>
              setCollapsed(allCollapsed ? new Set() : new Set(groups.map(([name]) => name)))
            }
          >
            {allCollapsed ? t("watchlist.expandAll") : t("watchlist.collapseAll")}
          </Button>
        )}
      </div>

      <Card>
        <div className="relative">
          <input
            className={`${inputClass} pr-20`}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("watchlist.searchPlaceholder")}
            aria-label={t("watchlist.search")}
            type="search"
          />
          {query && (
            <button
              onClick={() => setQuery("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded px-2 py-1 text-xs text-faint hover:text-ink"
            >
              {t("watchlist.clearSearch")}
            </button>
          )}
        </div>
        <p className="mt-1.5 text-xs text-faint">{t("watchlist.searchHint")}</p>

        {searching && !items.isFetching && (
          <p className="mt-2 text-xs text-muted">
            {total > 0
              ? t("watchlist.searchResults", { count: total, query: debounced })
              : t("watchlist.searchNothing", { query: debounced })}
          </p>
        )}
      </Card>

      <Card title={t("watchlist.add")}>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (ticker.trim()) add.mutate();
          }}
          className="flex flex-wrap items-end gap-3"
        >
          <div className="w-36">
            <Field label={t("portfolio.ticker")}>
              <input
                className={`${inputClass} font-mono uppercase`}
                value={ticker}
                onChange={(e) => setTicker(e.target.value)}
                placeholder={t("watchlist.addPlaceholder")}
                required
              />
            </Field>
          </div>

          <div className="w-52">
            <Field label={t("watchlist.category")}>
              {/* A datalist rather than a select: existing categories are one
                  keystroke away, and a new one is just typed. A select would
                  need a separate "create category" flow for no benefit. */}
              <input
                className={inputClass}
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                placeholder={t("watchlist.categoryPlaceholder")}
                list="watchlist-categories"
              />
              <datalist id="watchlist-categories">
                {(categories.data ?? []).map((row) => (
                  <option key={row.name} value={row.name} />
                ))}
              </datalist>
            </Field>
          </div>

          <div className="min-w-56 flex-1">
            <Field label={`${t("watchlist.note")} (${t("common.optional")})`}>
              <input
                className={inputClass}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder={t("watchlist.notePlaceholder")}
              />
            </Field>
          </div>

          <Button type="submit" busy={add.isPending}>
            {add.isPending ? t("watchlist.adding") : t("watchlist.add")}
          </Button>
        </form>

        <Caveat>{t("watchlist.sameTickerNote")}</Caveat>
        {addError && (
          <div className="mt-3">
            <ErrorNote message={addError} />
          </div>
        )}
      </Card>

      {items.isLoading ? (
        <Loading />
      ) : items.isError ? (
        <ErrorNote message={(items.error as Error).message} onRetry={() => items.refetch()} />
      ) : groups.length === 0 ? (
        <Card>
          <Empty message={t("watchlist.empty")} hint={t("watchlist.emptyHint")} />
        </Card>
      ) : (
        <div className="space-y-3">
          {groups.map(([name, rows]) => (
            <CategoryGroup
              key={name}
              name={name}
              rows={rows}
              // A search collapses nothing: hiding matches behind a shut group
              // would make the search look as though it found less than it did.
              open={searching || !collapsed.has(name)}
              onToggle={() => toggle(name)}
              toggleable={!searching}
              onRemove={(item) => {
                if (
                  confirm(
                    t("watchlist.confirmRemove", { ticker: item.ticker, category: name }),
                  )
                ) {
                  remove.mutate(item.id);
                }
              }}
              onMove={(item) => {
                const to = prompt(t("watchlist.moveTo", { ticker: item.ticker }), name);
                if (to && to.trim() && to.trim() !== name) {
                  move.mutate({ id: item.id, to: to.trim() });
                }
              }}
              busyId={
                remove.isPending
                  ? (remove.variables as string)
                  : move.isPending
                    ? move.variables?.id
                    : undefined
              }
              formatDate={dateTime}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function CategoryGroup({
  name,
  rows,
  open,
  toggleable,
  onToggle,
  onRemove,
  onMove,
  busyId,
  formatDate,
}: {
  name: string;
  rows: Item[];
  open: boolean;
  toggleable: boolean;
  onToggle: () => void;
  onRemove: (item: Item) => void;
  onMove: (item: Item) => void;
  busyId: string | undefined;
  formatDate: (value: string) => string;
}) {
  const { t } = useI18n();

  return (
    <section className="overflow-hidden rounded-lg border border-line bg-raised">
      <button
        onClick={onToggle}
        disabled={!toggleable}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-hover/50 disabled:cursor-default disabled:hover:bg-transparent"
      >
        <span
          aria-hidden
          className={`text-faint transition-transform ${open ? "rotate-90" : ""}`}
        >
          ›
        </span>
        <span className="text-sm font-medium text-ink">{name}</span>
        <span className="rounded-full bg-surface px-2 py-0.5 font-mono text-xs tnum text-faint">
          {rows.length}
        </span>
      </button>

      {open && (
        <div className="border-t border-line px-4 py-3">
          {rows.length === 0 ? (
            <p className="py-2 text-center text-xs text-faint">{t("watchlist.categoryEmpty")}</p>
          ) : (
            <ul className="divide-y divide-line">
              {rows.map((item) => (
                <li
                  key={item.id}
                  className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2.5 first:pt-0 last:pb-0"
                >
                  <Link
                    to={`/assets/${item.ticker}`}
                    className="font-mono text-sm font-medium text-ink hover:text-rise"
                  >
                    {item.ticker}
                  </Link>

                  {/* Null until an ingest fills it in, so the name is shown
                      when there is one rather than reserving an empty column
                      for it. */}
                  {item.name && (
                    <span className="min-w-0 truncate text-sm text-muted">{item.name}</span>
                  )}
                  {item.sector && (
                    <span className="shrink-0 rounded border border-line px-1.5 py-0.5 text-xs text-faint">
                      {item.sector}
                    </span>
                  )}

                  {item.note && (
                    <span className="min-w-0 flex-1 truncate text-xs text-muted">
                      {item.note}
                    </span>
                  )}

                  <span className="ml-auto shrink-0 text-xs text-faint">
                    {formatDate(item.added_at)}
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    busy={busyId === item.id}
                    onClick={() => onMove(item)}
                  >
                    {t("watchlist.move")}
                  </Button>
                  <Button
                    variant="danger"
                    size="sm"
                    busy={busyId === item.id}
                    onClick={() => onRemove(item)}
                  >
                    {t("watchlist.remove")}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
