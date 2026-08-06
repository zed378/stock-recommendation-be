import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { useI18n } from "@/i18n/context";
import { useToast } from "@/components/toastContext";
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

type Provider = components["schemas"]["AIProviderResponse"];
type TestResult = components["schemas"]["AIProviderTestResponse"];

/**
 * Which models the platform may use, and in what order it falls back.
 *
 * Configured here rather than in the environment because the choice is a
 * budget decision that changes: a cheaper model for routine work, a stronger
 * one for the analyzers, a self-hosted one for anything touching personal
 * financial data. Each of those is a different endpoint and a different key,
 * which is why a row now carries its own - rows that all read the environment
 * were one provider listed several times, and a fallback chain with one
 * destination cannot fall back.
 */

/** Which task complexities a provider may serve. */
const ROLES = ["general", "light", "standard", "reasoning"] as const;

export function AIProvidersPanel() {
  const { t, dateTime } = useI18n();
  const queryClient = useQueryClient();
  const toast = useToast();

  const [editing, setEditing] = useState<Provider | "new" | null>(null);
  const [deleting, setDeleting] = useState<Provider | null>(null);
  const [tested, setTested] = useState<{ provider: Provider; result: TestResult } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const providers = useQuery({
    queryKey: ["ai-providers"],
    queryFn: async () => {
      const { data, error: failed } = await api.GET("/admin/ai-providers");
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
      return data ?? [];
    },
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["ai-providers"] });

  const save = useMutation({
    mutationFn: async (input: { body: Record<string, unknown>; id?: string }) => {
      const { error: failed } = input.id
        ? await api.PATCH("/admin/ai-providers/{provider_id}", {
            params: { path: { provider_id: input.id } },
            body: input.body as never,
          })
        : await api.POST("/admin/ai-providers", { body: input.body as never });
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
    },
    onSuccess: () => {
      setEditing(null);
      setError(null);
      invalidate();
    },
    onError: (caught: Error) => setError(caught.message),
  });

  const remove = useMutation({
    mutationFn: async (id: string) => {
      const { error: failed } = await api.DELETE("/admin/ai-providers/{provider_id}", {
        params: { path: { provider_id: id } },
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
    mutationFn: async (provider: Provider) => {
      const { data, error: failed } = await api.POST("/admin/ai-providers/{provider_id}/test", {
        params: { path: { provider_id: provider.id } },
      });
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
      return { provider, result: data as TestResult };
    },
    onSuccess: (value) => {
      setTested(value);
      invalidate();
      if (value.result.ok) {
        toast.show({
          title: t("admin.providers.testOk", { ms: String(value.result.latency_ms ?? 0) }),
          tone: "success",
        });
      }
    },
    onError: (caught: Error) => setError(caught.message),
  });

  return (
    <Card
      title={t("admin.providers.title")}
      action={
        <Button size="sm" variant="ghost" onClick={() => setEditing("new")}>
          {t("admin.providers.add")}
        </Button>
      }
    >
      {error && (
        <div className="mb-3">
          <ErrorNote message={error} onRetry={() => setError(null)} />
        </div>
      )}

      {providers.isLoading ? (
        <Loading />
      ) : providers.isError ? (
        <ErrorNote
          message={(providers.error as Error).message}
          onRetry={() => providers.refetch()}
        />
      ) : !providers.data?.length ? (
        <Empty
          message={t("admin.providers.empty")}
          hint={t("admin.providers.emptyHint")}
          action={<Button onClick={() => setEditing("new")}>{t("admin.providers.add")}</Button>}
        />
      ) : (
        <ul className="divide-y divide-line">
          {providers.data.map((provider) => (
            <li key={provider.id} className="py-3 first:pt-0 last:pb-0">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className="text-sm font-medium text-ink">{provider.name}</span>
                <span className="font-mono text-xs text-faint">
                  {provider.default_model ?? "—"}
                </span>
                <span className="rounded border border-line px-1.5 py-0.5 text-[0.65rem] text-faint">
                  {provider.role}
                </span>
                {provider.self_hosted && (
                  <span className="rounded border border-rise/30 px-1.5 py-0.5 text-[0.65rem] text-rise">
                    {t("admin.providers.selfHosted")}
                  </span>
                )}
                {!provider.is_active && (
                  <span className="rounded border border-line px-1.5 py-0.5 text-[0.65rem] text-faint">
                    {t("admin.news.off")}
                  </span>
                )}
                {/* The last check, because a provider that stopped answering
                    is otherwise indistinguishable from one nobody has tried. */}
                {provider.last_status && (
                  <span
                    className={`text-xs ${
                      provider.last_status === "ok" ? "text-rise" : "text-fall"
                    }`}
                    title={provider.last_error ?? undefined}
                  >
                    {provider.last_status}
                    {provider.last_checked_at ? ` · ${dateTime(provider.last_checked_at)}` : ""}
                  </span>
                )}

                <div className="ml-auto flex gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    busy={probe.isPending && probe.variables?.id === provider.id}
                    onClick={() => probe.mutate(provider)}
                  >
                    {t("admin.providers.test")}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setEditing(provider)}>
                    {t("admin.news.edit")}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setDeleting(provider)}>
                    {t("admin.news.remove")}
                  </Button>
                </div>
              </div>

              <p className="mt-1 font-mono text-xs text-faint">
                {provider.base_url ?? "—"}
                {provider.api_key_hint
                  ? ` · ${t("admin.providers.apiKeyStored", { hint: provider.api_key_hint })}`
                  : ""}
              </p>
              <p className="mt-0.5 text-xs text-faint">
                {t("admin.providers.priority")} {provider.priority}
                {provider.timeout_seconds ? ` · ${provider.timeout_seconds}s` : ""}
              </p>
            </li>
          ))}
        </ul>
      )}

      <Caveat>{t("admin.providers.caveat")}</Caveat>

      {editing && (
        <ProviderEditor
          provider={editing === "new" ? null : editing}
          busy={save.isPending}
          error={error}
          onCancel={() => {
            setEditing(null);
            setError(null);
          }}
          onSave={(body) =>
            save.mutate({ body, id: editing === "new" ? undefined : editing.id })
          }
        />
      )}

      {deleting && (
        <ConfirmDialog
          destructive
          busy={remove.isPending}
          title={t("admin.news.removeTitle")}
          message={deleting.name}
          confirmLabel={t("common.delete")}
          onCancel={() => setDeleting(null)}
          onConfirm={() => remove.mutate(deleting.id)}
        />
      )}

      {tested && (
        <Modal title={tested.provider.name} onClose={() => setTested(null)}>
          {tested.result.ok ? (
            <div className="space-y-2 text-sm">
              <p className="text-rise">
                {t("admin.providers.testOk", { ms: String(tested.result.latency_ms ?? 0) })}
              </p>
              <p className="font-mono text-xs text-faint">{tested.result.model}</p>
              <p className="text-xs text-muted">{tested.result.reply}</p>
            </div>
          ) : (
            <ErrorNote message={tested.result.error ?? t("common.error")} />
          )}
        </Modal>
      )}
    </Card>
  );
}

function ProviderEditor({
  provider,
  busy,
  error,
  onCancel,
  onSave,
}: {
  provider: Provider | null;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onSave: (body: Record<string, unknown>) => void;
}) {
  const { t } = useI18n();
  const [form, setForm] = useState({
    name: provider?.name ?? "",
    base_url: provider?.base_url ?? "",
    default_model: provider?.default_model ?? "",
    role: provider?.role ?? "general",
    priority: String(provider?.priority ?? 100),
    timeout_seconds: provider?.timeout_seconds ? String(provider.timeout_seconds) : "",
    input_cost_per_1k: provider?.input_cost_per_1k ? String(provider.input_cost_per_1k) : "",
    output_cost_per_1k: provider?.output_cost_per_1k ? String(provider.output_cost_per_1k) : "",
    is_active: provider?.is_active ?? true,
    self_hosted: provider?.self_hosted ?? false,
  });
  // Kept apart from the rest of the form, because absent and empty mean
  // different things here: absent keeps the stored key, empty clears it.
  const [apiKey, setApiKey] = useState<string | null>(provider ? null : "");

  const set = (patch: Partial<typeof form>) => setForm((current) => ({ ...current, ...patch }));

  return (
    <Modal
      title={provider ? provider.name : t("admin.providers.add")}
      onClose={onCancel}
      footer={
        <>
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            {t("common.cancel")}
          </Button>
          <Button
            busy={busy}
            disabled={!form.name.trim()}
            onClick={() =>
              onSave({
                name: form.name.trim(),
                base_url: form.base_url.trim() || null,
                default_model: form.default_model.trim() || null,
                role: form.role,
                priority: Number(form.priority) || 100,
                is_active: form.is_active,
                self_hosted: form.self_hosted,
                timeout_seconds: form.timeout_seconds ? Number(form.timeout_seconds) : null,
                input_cost_per_1k: form.input_cost_per_1k || null,
                output_cost_per_1k: form.output_cost_per_1k || null,
                ...(apiKey === null ? {} : { api_key: apiKey }),
              })
            }
          >
            {t("common.save")}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {error && <ErrorNote message={error} />}

        <Field label={t("admin.providers.name")}>
          <input
            className={inputClass}
            value={form.name}
            onChange={(event) => set({ name: event.target.value })}
            placeholder="primary"
          />
        </Field>

        <Field label={t("admin.providers.baseUrl")}>
          <input
            className={`${inputClass} font-mono text-xs`}
            value={form.base_url}
            onChange={(event) => set({ base_url: event.target.value })}
            placeholder="https://api.example.com/v1"
          />
        </Field>

        <Field label={t("admin.providers.model")}>
          <input
            className={`${inputClass} font-mono text-xs`}
            value={form.default_model}
            onChange={(event) => set({ default_model: event.target.value })}
          />
        </Field>

        <Field
          label={t("admin.providers.apiKey")}
          hint={
            provider?.api_key_hint
              ? `${t("admin.providers.apiKeyStored", { hint: provider.api_key_hint })} — ${t("admin.providers.apiKeyKeep")}`
              : t("admin.providers.apiKeyKeep")
          }
        >
          <input
            type="password"
            className={`${inputClass} font-mono text-xs`}
            value={apiKey ?? ""}
            // Typing at all switches this from "leave it alone" to "set it to
            // what is in the box" - which is what clearing the box then means.
            onChange={(event) => setApiKey(event.target.value)}
            placeholder={provider ? "••••••••" : ""}
          />
        </Field>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("admin.providers.role")}>
            <select
              className={inputClass}
              value={form.role}
              onChange={(event) => set({ role: event.target.value })}
            >
              {ROLES.map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </select>
          </Field>

          <Field label={t("admin.providers.priority")} hint={t("admin.providers.priorityHint")}>
            <input
              type="number"
              className={inputClass}
              value={form.priority}
              onChange={(event) => set({ priority: event.target.value })}
            />
          </Field>

          <Field label={t("admin.providers.timeout")}>
            <input
              type="number"
              className={inputClass}
              value={form.timeout_seconds}
              onChange={(event) => set({ timeout_seconds: event.target.value })}
              placeholder="300"
            />
          </Field>

          <Field label={t("admin.providers.costIn")}>
            <input
              className={inputClass}
              value={form.input_cost_per_1k}
              onChange={(event) => set({ input_cost_per_1k: event.target.value })}
              placeholder="0"
            />
          </Field>

          <Field label={t("admin.providers.costOut")}>
            <input
              className={inputClass}
              value={form.output_cost_per_1k}
              onChange={(event) => set({ output_cost_per_1k: event.target.value })}
              placeholder="0"
            />
          </Field>
        </div>

        <label className="flex items-center gap-2 text-sm text-ink">
          <input
            type="checkbox"
            className="accent-rise"
            checked={form.is_active}
            onChange={(event) => set({ is_active: event.target.checked })}
          />
          {t("admin.providers.active")}
        </label>

        <div>
          <label className="flex items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              className="accent-rise"
              checked={form.self_hosted}
              onChange={(event) => set({ self_hosted: event.target.checked })}
            />
            {t("admin.providers.selfHosted")}
          </label>
          <p className="mt-1 text-xs text-faint">{t("admin.providers.selfHostedHint")}</p>
        </div>
      </div>
    </Modal>
  );
}
