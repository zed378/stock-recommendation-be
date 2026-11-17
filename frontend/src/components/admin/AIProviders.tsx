import { useCallback, useEffect, useRef, useState } from "react";
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

  // Read from the registry rather than listed here: a hardcoded copy goes
  // stale the day somebody adds a fourth adapter, and the failure is a
  // provider you cannot select.
  const inventory = useQuery({
    queryKey: ["provider-inventory"],
    queryFn: async () => {
      const { data, error: failed } = await api.GET("/providers");
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
      return data;
    },
  });
  const adapters = inventory.data?.registered?.ai ?? ["openai_compatible"];

  const [form, setForm] = useState({
    name: provider?.name ?? "",
    adapter_name: provider?.adapter_name ?? "openai_compatible",
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

  // The model list is asked of the endpoint itself, with the key being typed, so the choice is a
  // dropdown of what that key can actually use rather than a name copied from documentation.
  const [models, setModels] = useState<string[] | null>(null);
  const [modelsStatus, setModelsStatus] = useState<"idle" | "loading" | "ok" | "failed">("idle");
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [typeModel, setTypeModel] = useState(false);
  // Only the newest request may write its answer: a slow reply for a key since replaced would
  // otherwise overwrite the list for the key now in the box.
  const latest = useRef(0);

  const fetchModels = useCallback(async () => {
    const ticket = ++latest.current;
    setModelsStatus("loading");
    setModelsError(null);
    try {
      const { data, error: failed } = await api.POST("/admin/ai-providers/models", {
        body: {
          adapter_name: form.adapter_name,
          base_url: form.base_url.trim() || null,
          // Typed key wins; an untouched edit form lets the server use the stored one.
          ...(apiKey === null ? { provider_id: provider?.id } : { api_key: apiKey }),
        },
      });
      if (ticket !== latest.current) return;
      if (failed || !data) throw new Error(errorMessage(failed, t("common.error")));
      if (!data.ok) {
        setModels(null);
        setModelsStatus("failed");
        setModelsError(data.error ?? t("common.error"));
        return;
      }
      const listed = data.models ?? [];
      setModels(listed);
      setModelsStatus(listed.length ? "ok" : "failed");
      setModelsError(listed.length ? null : t("admin.providers.modelsNone"));
    } catch (caught) {
      if (ticket !== latest.current) return;
      setModels(null);
      setModelsStatus("failed");
      setModelsError((caught as Error).message);
    }
  }, [apiKey, form.adapter_name, form.base_url, provider, t]);

  // Fetch by itself once there is a key to ask with: one being typed, or a stored one on an edit
  // that has not touched it. A keyless local server has nothing to wait for, so it uses the button.
  const canAsk = apiKey === null ? Boolean(provider?.api_key_hint) : apiKey.trim().length > 0;
  useEffect(() => {
    latest.current += 1; // whatever was in flight belongs to the previous inputs
    setModels(null);
    setModelsStatus("idle");
    setModelsError(null);
    if (!canAsk) return;
    const timer = window.setTimeout(() => void fetchModels(), 700);
    return () => window.clearTimeout(timer);
    // `fetchModels` changes with exactly these inputs; listing them here would reschedule twice.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.adapter_name, form.base_url, apiKey, canAsk]);

  const MANUAL = "__manual__";
  const choosing = models !== null && models.length > 0 && !typeModel;
  const modelOptions =
    models && form.default_model && !models.includes(form.default_model)
      ? [form.default_model, ...models]
      : (models ?? []);

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
                adapter_name: form.adapter_name,
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

        <Field label={t("admin.providers.adapter")} hint={t("admin.providers.adapterHint")}>
          <select
            className={inputClass}
            value={form.adapter_name}
            onChange={(event) => set({ adapter_name: event.target.value })}
          >
            {adapters.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </Field>

        <Field
          label={t("admin.providers.baseUrl")}
          // Above the field rather than beside it: for a first-party adapter
          // this box is an override nobody normally needs, and for the
          // OpenAI-compatible one it is the whole point of the row.
          hint={
            form.adapter_name === "openai_compatible"
              ? t("admin.providers.baseUrlRequired")
              : t("admin.providers.baseUrlOptional")
          }
        >
          <input
            className={`${inputClass} font-mono text-xs`}
            value={form.base_url}
            onChange={(event) => set({ base_url: event.target.value })}
            placeholder={
              form.adapter_name === "anthropic"
                ? "https://api.anthropic.com/v1"
                : form.adapter_name === "gemini"
                  ? "https://generativelanguage.googleapis.com/v1beta"
                  : "https://api.example.com/v1"
            }
          />
        </Field>

        <div>
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <label htmlFor="provider-model" className="text-xs font-medium text-muted">
              {t("admin.providers.model")}
            </label>
            <Button
              size="sm"
              variant="ghost"
              type="button"
              busy={modelsStatus === "loading"}
              onClick={() => {
                setTypeModel(false);
                void fetchModels();
              }}
            >
              {t("admin.providers.fetchModels")}
            </Button>
          </div>
          {choosing ? (
            <select
              id="provider-model"
              className={`${inputClass} font-mono text-xs`}
              value={form.default_model}
              onChange={(event) => {
                if (event.target.value === MANUAL) setTypeModel(true);
                else set({ default_model: event.target.value });
              }}
            >
              {!form.default_model && <option value="">{t("admin.providers.modelPick")}</option>}
              {modelOptions.map((name) => (
                <option key={name} value={name}>
                  {models?.includes(name) ? name : t("admin.providers.modelCurrent", { name })}
                </option>
              ))}
              <option value={MANUAL}>{t("admin.providers.modelManual")}</option>
            </select>
          ) : (
            <input
              id="provider-model"
              className={`${inputClass} font-mono text-xs`}
              value={form.default_model}
              onChange={(event) => set({ default_model: event.target.value })}
            />
          )}
          <p className="mt-1 text-xs text-faint" aria-live="polite">
            {modelsStatus === "loading"
              ? t("admin.providers.fetchingModels")
              : modelsStatus === "ok"
                ? t("admin.providers.modelsFound", { count: String(models?.length ?? 0) })
                : modelsStatus === "failed"
                  ? t("admin.providers.modelsFailed", { reason: modelsError ?? "" })
                  : t("admin.providers.modelsHint")}
          </p>
        </div>

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
