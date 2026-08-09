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

  const saved = useQuery({
    queryKey: ["screens"],
    queryFn: async () => {
      const { data, error: failed } = await api.GET("/screens");
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
      return data;
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

  const remove = useMutation({
    mutationFn: async (id: string) => {
      const { error: failed } = await api.DELETE("/screens/{screen_id}", {
        params: { path: { screen_id: id } },
      });
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["screens"] }),
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

        {(saved.data ?? []).length > 0 && (
          <ul className="mt-4 divide-y divide-line">
            {(saved.data ?? []).map((screen) => (
              <li key={screen.id} className="flex flex-wrap items-center gap-3 py-2.5">
                <span className="text-sm font-medium text-ink">{screen.name}</span>
                <span className="text-xs text-faint">
                  {t("screen.ruleCount", { count: screen.rules.length })}
                </span>
                <div className="ml-auto flex gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setRules(screen.rules as unknown as Rule[])}
                  >
                    {t("screen.load")}
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => remove.mutate(screen.id)}>
                    {t("common.delete")}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
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
