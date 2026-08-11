import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { useI18n, type MessageKey } from "@/i18n/context";
import { useToast } from "@/components/toastContext";
import {
  Button,
  Card,
  Caveat,
  Empty,
  ErrorNote,
  Field as FormField,
  inputClass,
  Loading,
} from "@/components/primitives";

interface FieldShape {
  key: string;
  type: "number" | "boolean" | "date" | "criteria";
  operators: string[];
}

interface Rule {
  field: string;
  operator: string;
  value: unknown;
}

interface RunResult {
  session_date: string | null;
  considered: number;
  matched: number;
  share: number;
  results: {
    ticker: string;
    close: string | null;
    matched: string[];
    matched_count: number;
  }[];
  caveat: string;
}

/**
 * A screen the reader writes themselves.
 *
 * The built-in horizons answer questions somebody else chose. This one asks
 * what the reader wants to know, and then tells them something the answer
 * alone cannot: how much of the exchange it kept. A filter matching most of
 * the market is not filtering, and the denominator is the only thing that
 * shows it - the platform learned that from two built-in criteria that matched
 * 44% and 36% before anybody measured them.
 */
export function ScreenBuilder() {
  const { t, money, n } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();

  const [rules, setRules] = useState<Rule[]>([]);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RunResult | null>(null);

  const vocabulary = useQuery({
    queryKey: ["screen-fields"],
    queryFn: async () => {
      const { data, error: failed } = await api.GET("/screens/fields");
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
      return data as unknown as {
        fields: FieldShape[];
        criteria: string[];
        caveat: string;
      };
    },
  });

  const preview = useMutation({
    mutationFn: async () => {
      const { data, error: failed } = await api.POST("/screens/preview", {
        body: { rules: rules as never, limit: 100 },
      });
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
      return data as unknown as RunResult;
    },
    onSuccess: (data) => {
      setError(null);
      setResult(data);
    },
    onError: (caught: Error) => setError(caught.message),
  });

  const save = useMutation({
    mutationFn: async () => {
      const { data, error: failed } = await api.POST("/screens", {
        body: { name: name.trim(), rules: rules as never },
      });
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
      return data;
    },
    onSuccess: () => {
      setError(null);
      toast.show({ title: t("screen.saved"), tone: "success" });
      queryClient.invalidateQueries({ queryKey: ["screens"] });
    },
    onError: (caught: Error) => setError(caught.message),
  });

  if (vocabulary.isLoading) return <Loading />;
  if (vocabulary.isError)
    return (
      <ErrorNote
        message={(vocabulary.error as Error).message}
        onRetry={() => vocabulary.refetch()}
      />
    );

  const fields = vocabulary.data?.fields ?? [];
  const byKey = new Map(fields.map((field) => [field.key, field]));

  const addRule = () => {
    const first = fields[0];
    if (!first) return;
    setRules((current) => [
      ...current,
      { field: first.key, operator: first.operators[0], value: defaultValue(first) },
    ]);
  };

  const patch = (index: number, next: Partial<Rule>) =>
    setRules((current) =>
      current.map((rule, at) => (at === index ? { ...rule, ...next } : rule)),
    );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-ink">{t("screen.title")}</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">{t("screen.intro")}</p>
      </div>

      {error && <ErrorNote message={error} onRetry={() => setError(null)} />}

      <Card title={t("screen.rules")}>
        {rules.length === 0 ? (
          <Empty message={t("screen.noRules")} hint={t("screen.noRulesHint")} />
        ) : (
          <ul className="space-y-2">
            {rules.map((rule, index) => {
              const field = byKey.get(rule.field);
              return (
                <li key={index} className="flex flex-wrap items-center gap-2">
                  {/* Every rule narrows: they are ANDed. Said in the interface
                      rather than left to be discovered, because the criteria
                      checkboxes elsewhere are ORed and the two would otherwise
                      look like the same control. */}
                  <span className="w-10 shrink-0 text-xs text-faint">
                    {index === 0 ? t("screen.where") : t("screen.and")}
                  </span>

                  <select
                    className={`${inputClass} w-auto min-w-44`}
                    value={rule.field}
                    onChange={(event) => {
                      const next = byKey.get(event.target.value);
                      if (!next) return;
                      patch(index, {
                        field: next.key,
                        // The operator and value come from the new field, not
                        // carried over: "includes_any" on a number is a rule
                        // the server would refuse, and offering it is offering
                        // a dead end.
                        operator: next.operators[0],
                        value: defaultValue(next),
                      });
                    }}
                  >
                    {fields.map((option) => (
                      <option key={option.key} value={option.key}>
                        {option.key.replace(/_/g, " ")}
                      </option>
                    ))}
                  </select>

                  <select
                    className={`${inputClass} w-auto min-w-36`}
                    value={rule.operator}
                    onChange={(event) => {
                      const operator = event.target.value;
                      patch(index, {
                        operator,
                        value:
                          operator === "between"
                            ? [0, 0]
                            : field?.type === "number" && Array.isArray(rule.value)
                              ? 0
                              : rule.value,
                      });
                    }}
                  >
                    {(field?.operators ?? []).map((operator) => (
                      <option key={operator} value={operator}>
                        {t(`screen.op.${operator}` as MessageKey)}
                      </option>
                    ))}
                  </select>

                  <ValueInput
                    field={field}
                    rule={rule}
                    criteria={vocabulary.data?.criteria ?? []}
                    onChange={(value) => patch(index, { value })}
                  />

                  <button
                    type="button"
                    onClick={() => setRules((c) => c.filter((_, at) => at !== index))}
                    className="rounded-md px-2 py-1 text-xs text-faint transition-colors hover:bg-hover hover:text-fall"
                  >
                    {t("common.remove")}
                  </button>
                </li>
              );
            })}
          </ul>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button variant="ghost" size="sm" onClick={addRule}>
            {t("screen.addRule")}
          </Button>
          <Button busy={preview.isPending} onClick={() => preview.mutate()}>
            {t("screen.run")}
          </Button>
        </div>
      </Card>

      {result && (
        <Card title={t("screen.results")}>
          {/* The denominator, first and in plain language. A screen that keeps
              most of the exchange has told its author nothing, and only the
              share makes that visible. */}
          <p className="mb-3 text-sm text-muted">
            {t("screen.matchedOf", {
              matched: result.matched,
              considered: result.considered,
            })}{" "}
            <span
              className={
                result.share > 0.5 ? "text-watch" : "text-faint"
              }
            >
              ({n(result.share * 100, 1)}%)
            </span>
          </p>
          {result.share > 0.5 && (
            <p className="mb-3 rounded-md border border-watch/25 bg-watch/5 px-3 py-2 text-xs text-watch">
              {t("screen.notSelective")}
            </p>
          )}

          {result.results.length === 0 ? (
            <Empty message={t("screen.empty")} hint={t("screen.emptyHint")} />
          ) : (
            <ul className="max-h-104 divide-y divide-line overflow-y-auto">
              {result.results.map((row) => (
                <li
                  key={row.ticker}
                  className="flex flex-wrap items-baseline gap-x-4 gap-y-1 py-2.5"
                >
                  <Link
                    to={`/assets/${row.ticker}`}
                    className="font-mono text-sm font-semibold text-ink hover:text-rise"
                  >
                    {row.ticker}
                  </Link>
                  <span className="font-mono text-sm tnum text-ink/90">
                    {money(row.close)}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-xs text-faint">
                    {row.matched.join(", ").replace(/_/g, " ")}
                  </span>
                </li>
              ))}
            </ul>
          )}

          <Caveat>{result.caveat}</Caveat>
        </Card>
      )}

      <Card title={t("screen.save")}>
        <div className="flex flex-wrap items-end gap-3">
          <FormField label={t("screen.name")}>
            <input
              className={`${inputClass} min-w-56`}
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t("screen.namePlaceholder")}
            />
          </FormField>
          <Button
            busy={save.isPending}
            disabled={!name.trim() || rules.length === 0}
            onClick={() => save.mutate()}
          >
            {t("common.save")}
          </Button>
        </div>

      </Card>

      <SavedScreens onLoad={(loaded) => setRules(loaded)} />
    </div>
  );
}

function defaultValue(field: FieldShape): unknown {
  if (field.type === "boolean") return true;
  if (field.type === "criteria") return [];
  if (field.type === "date") return new Date().toISOString().slice(0, 10);
  return 0;
}

function ValueInput({
  field,
  rule,
  criteria,
  onChange,
}: {
  field: FieldShape | undefined;
  rule: Rule;
  criteria: string[];
  onChange: (value: unknown) => void;
}) {
  const { t } = useI18n();
  if (!field) return null;

  if (rule.operator === "between") {
    const pair = Array.isArray(rule.value) ? (rule.value as number[]) : [0, 0];
    return (
      <div className="flex items-center gap-1.5">
        <input
          type="number"
          className={`${inputClass} w-28`}
          value={pair[0]}
          onChange={(event) => onChange([Number(event.target.value), pair[1]])}
        />
        <span className="text-xs text-faint">{t("screen.and")}</span>
        <input
          type="number"
          className={`${inputClass} w-28`}
          value={pair[1]}
          onChange={(event) => onChange([pair[0], Number(event.target.value)])}
        />
      </div>
    );
  }

  if (field.type === "boolean") {
    return (
      <select
        className={`${inputClass} w-auto`}
        value={String(rule.value)}
        onChange={(event) => onChange(event.target.value === "true")}
      >
        <option value="true">{t("common.yes")}</option>
        <option value="false">{t("common.no")}</option>
      </select>
    );
  }

  if (field.type === "date") {
    return (
      <input
        type="date"
        className={`${inputClass} w-auto`}
        value={String(rule.value ?? "")}
        onChange={(event) => onChange(event.target.value)}
      />
    );
  }

  if (field.type === "criteria") {
    const chosen = Array.isArray(rule.value) ? (rule.value as string[]) : [];
    return (
      <select
        multiple
        className={`${inputClass} h-24 w-auto min-w-52`}
        value={chosen}
        onChange={(event) =>
          onChange(Array.from(event.target.selectedOptions, (option) => option.value))
        }
      >
        {criteria.map((option) => (
          <option key={option} value={option}>
            {option.replace(/_/g, " ")}
          </option>
        ))}
      </select>
    );
  }

  return (
    <input
      type="number"
      className={`${inputClass} w-32`}
      value={Number(rule.value ?? 0)}
      onChange={(event) => onChange(Number(event.target.value))}
    />
  );
}


/**
 * Saved filters, each with a runner and a schedule of its own.
 *
 * Loading a filter into the builder to run it made the builder the only way to
 * use one - so a screen you had already decided on still cost a round trip
 * through the editor, and running it meant overwriting whatever you were
 * midway through composing.
 */
function SavedScreens({ onLoad }: { onLoad: (rules: Rule[]) => void }) {
  const { t, money, n, dateTime } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [ran, setRan] = useState<Record<string, RunResult>>({});
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  //: Which rows are open. A set rather than a single id: comparing two filters
  //: means having both on screen, and an accordion that closes one to open the
  //: next makes that impossible.
  const [open, setOpen] = useState<Set<string>>(new Set());

  const toggle = (id: string) =>
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const saved = useQuery({
    queryKey: ["screens"],
    queryFn: async () => {
      const { data, error: failed } = await api.GET("/screens");
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
      return data;
    },
  });

  const runOne = useMutation({
    mutationFn: async (id: string) => {
      const { data, error: failed } = await api.POST("/screens/{screen_id}/run", {
        params: { path: { screen_id: id } },
      });
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
      return { id, result: data as unknown as RunResult };
    },
    onSuccess: ({ id, result }) => {
      setError(null);
      setRan((current) => ({ ...current, [id]: result }));
      // Running a collapsed row would otherwise produce no visible change at
      // all - the results land inside a section nobody can see.
      setOpen((current) => new Set(current).add(id));
    },
    onError: (caught: Error) => setError(caught.message),
  });

  const schedule = useMutation({
    mutationFn: async ({ id, cron }: { id: string; cron: string }) => {
      const { data, error: failed } = await api.PATCH("/screens/{screen_id}/schedule", {
        params: { path: { screen_id: id } },
        body: { cron_expr: cron },
      });
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
      return data;
    },
    onSuccess: () => {
      setError(null);
      toast.show({ title: t("screen.scheduleSaved"), tone: "success" });
      queryClient.invalidateQueries({ queryKey: ["screens"] });
    },
    onError: (caught: Error) => setError(caught.message),
  });

  const remove = useMutation({
    mutationFn: async (id: string) => {
      const { error: failed } = await api.DELETE("/screens/{screen_id}", {
        params: { path: { screen_id: id } },
      });
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["screens"] }),
  });

  if (saved.isLoading) return <Loading />;
  const all = saved.data ?? [];
  if (all.length === 0) return null;

  const needle = search.trim().toLowerCase();
  // Matched on the name and on the fields the rules read. Somebody hunting for
  // "the one with the RSI condition" rarely remembers what they called it.
  const screens = needle
    ? all.filter(
        (screen) =>
          screen.name.toLowerCase().includes(needle) ||
          screen.rules.some((rule) =>
            String((rule as { field?: unknown }).field ?? "")
              .toLowerCase()
              .includes(needle),
          ),
      )
    : all;

  return (
    <Card title={t("screen.saved.title")}>
      {error && (
        <div className="mb-3">
          <ErrorNote message={error} onRetry={() => setError(null)} />
        </div>
      )}

      {/* Offered once the list is long enough to need it. A search box above
          three rows is furniture. */}
      {all.length > 3 && (
        <input
          className={`${inputClass} mb-3`}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={t("screen.searchPlaceholder")}
          aria-label={t("screen.searchPlaceholder")}
        />
      )}

      {screens.length === 0 ? (
        <Empty message={t("screen.noMatch")} hint={t("screen.noMatchHint")} />
      ) : (
        <ul className="divide-y divide-line">
          {screens.map((screen) => {
            const result = ran[screen.id];
            const expanded = open.has(screen.id);
            return (
              <li key={screen.id} className="py-3 first:pt-0">
                <div className="flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    onClick={() => toggle(screen.id)}
                    aria-expanded={expanded}
                    className="flex items-center gap-2 text-sm font-medium text-ink transition-colors hover:text-rise"
                  >
                    {/* Rotated rather than swapped for a second glyph: one shape
                        turning says the same row is opening, where two shapes
                        read as two different controls. */}
                    <svg
                      width="10"
                      height="10"
                      viewBox="0 0 10 10"
                      aria-hidden
                      className={`shrink-0 text-faint transition-transform ${
                        expanded ? "rotate-90" : ""
                      }`}
                    >
                      <path
                        d="M3 1.5 L7 5 L3 8.5"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                    {screen.name}
                  </button>
                  <span className="text-xs text-faint">
                    {t("screen.ruleCount", { count: screen.rules.length })}
                  </span>

                  {/* What the last scheduled run found, including when it found
                      nothing. A screen that only speaks up on a match is
                      indistinguishable from one that stopped running, and this
                      line is where that question gets answered without
                      interrupting anybody to say nothing happened. */}
                  {screen.last_run_at && (
                    <span className="text-xs text-faint">
                      {t("screen.lastRun", {
                        when: dateTime(screen.last_run_at),
                        count: screen.last_match_count ?? 0,
                      })}
                    </span>
                  )}

                  {/* Whether it is scheduled has to survive the collapse: it is
                      the difference between a filter that watches the market for
                      you and one that waits to be asked. */}
                  {screen.cron_expr && (
                    <span className="rounded border border-line px-1.5 py-0.5 font-mono text-[0.65rem] text-faint">
                      {screen.cron_expr}
                    </span>
                  )}

                  <div className="ml-auto flex gap-2">
                    <Button
                      size="sm"
                      busy={runOne.isPending && runOne.variables === screen.id}
                      onClick={() => runOne.mutate(screen.id)}
                    >
                      {t("screen.run")}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => onLoad(screen.rules as unknown as Rule[])}
                    >
                      {t("screen.edit")}
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => remove.mutate(screen.id)}>
                      {t("common.delete")}
                    </Button>
                  </div>
                </div>

                {screen.last_error && (
                  <p className="mt-2 rounded-md border border-fall/25 bg-fall/5 px-3 py-2 text-xs text-fall">
                    {screen.last_error}
                  </p>
                )}

                {expanded && (
                  <ScheduleRow
                    screen={screen}
                    busy={schedule.isPending}
                    onSave={(cron) => schedule.mutate({ id: screen.id, cron })}
                  />
                )}

                {expanded && result && (
                  <div className="mt-3 rounded-md border border-line bg-surface/60 p-3">
                    <p className="mb-2 text-xs text-muted">
                      {t("screen.matchedOf", {
                        matched: result.matched,
                        considered: result.considered,
                      })}{" "}
                      <span className={result.share > 0.5 ? "text-watch" : "text-faint"}>
                        ({n(result.share * 100, 1)}%)
                      </span>
                    </p>
                    {result.share > 0.5 && (
                      <p className="mb-2 rounded-md border border-watch/25 bg-watch/5 px-3 py-2 text-xs text-watch">
                        {t("screen.notSelective")}
                      </p>
                    )}
                    {result.results.length === 0 ? (
                      <p className="text-xs text-faint">{t("screen.empty")}</p>
                    ) : (
                      <ul className="max-h-64 divide-y divide-line overflow-y-auto">
                        {result.results.map((row) => (
                          <li key={row.ticker} className="flex items-baseline gap-3 py-1.5">
                            <Link
                              to={`/assets/${row.ticker}`}
                              className="font-mono text-sm text-ink hover:text-rise"
                            >
                              {row.ticker}
                            </Link>
                            <span className="font-mono text-xs tnum text-muted">
                              {money(row.close)}
                            </span>
                            <span className="min-w-0 flex-1 truncate text-xs text-faint">
                              {row.matched.join(", ").replace(/_/g, " ")}
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      <Caveat>{t("screen.scheduleCaveat")}</Caveat>
    </Card>
  );
}

const CRON_PRESETS = [
  { key: "off", cron: "" },
  { key: "afterClose", cron: "0 18 * * 1-5" },
  { key: "beforeOpen", cron: "0 8 * * 1-5" },
  { key: "weekly", cron: "0 8 * * 1" },
] as const;

function ScheduleRow({
  screen,
  busy,
  onSave,
}: {
  screen: { id: string; cron_expr: string; next_run_at: string | null };
  busy: boolean;
  onSave: (cron: string) => void;
}) {
  const { t, dateTime } = useI18n();
  const [cron, setCron] = useState(screen.cron_expr ?? "");

  return (
    <div className="mt-2 flex flex-wrap items-center gap-2">
      <span className="text-xs text-faint">{t("screen.schedule")}</span>

      {/* Presets first, expression second. A cron field alone asks a reader to
          know the syntax before they can have the feature at all, and the three
          they will actually want are the ones the exchange's day suggests. */}
      <select
        className={`${inputClass} w-auto text-xs`}
        value={CRON_PRESETS.some((p) => p.cron === cron) ? cron : "custom"}
        onChange={(event) => {
          if (event.target.value === "custom") return;
          setCron(event.target.value);
          onSave(event.target.value);
        }}
      >
        {CRON_PRESETS.map((preset) => (
          <option key={preset.key} value={preset.cron}>
            {t(`screen.cron.${preset.key}` as MessageKey)}
          </option>
        ))}
        <option value="custom">{t("screen.cron.custom")}</option>
      </select>

      <input
        className={`${inputClass} w-40 font-mono text-xs`}
        value={cron}
        onChange={(event) => setCron(event.target.value)}
        placeholder="0 18 * * 1-5"
      />
      <Button variant="ghost" size="sm" busy={busy} onClick={() => onSave(cron)}>
        {t("common.save")}
      </Button>

      {screen.next_run_at && (
        <span className="text-xs text-faint">
          {t("screen.nextRun", { when: dateTime(screen.next_run_at) })}
        </span>
      )}
    </div>
  );
}
