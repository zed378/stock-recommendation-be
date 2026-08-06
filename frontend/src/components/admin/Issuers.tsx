import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { useI18n } from "@/i18n/context";
import { useToast } from "@/components/toastContext";
import { Pager, type PageState } from "@/components/Pager";
import { MultiSelect } from "@/components/MultiSelect";
import {
  Button,
  Card,
  Caveat,
  Empty,
  ErrorNote,
  Field,
  inputClass,
  Loading,
  Modal,
} from "@/components/primitives";
import type { components } from "@/api/schema";

type IssuerRow = components["schemas"]["IssuerResponse"];

/**
 * Both alias lists have defaults in the schema, so `openapi-typescript` types
 * them optional. They are always present in practice; narrowing here keeps the
 * uncertainty in one place rather than at every use.
 */
type Issuer = IssuerRow & { aliases: string[]; effective_aliases: string[] };

function normalised(row: IssuerRow): Issuer {
  return { ...row, aliases: row.aliases ?? [], effective_aliases: row.effective_aliases ?? [] };
}

/**
 * The listed-company directory that news tagging matches against.
 *
 * Its completeness is what tagging's recall rests on, and its aliases are what
 * its precision rests on - so both need to be visible. A tag nobody can
 * inspect is a tag nobody can correct.
 *
 * Two alias lists, and the distinction matters. `effective_aliases` is what
 * actually matches: the curated index, the names derived from the registered
 * one, and anything typed here. `aliases` is only the last of those. Showing
 * just the editable one would render an empty list for BBCA while "BCA" is
 * matching perfectly well, which reads as the feature being broken.
 */
export function IssuersPanel() {
  const { t, dateTime } = useI18n();
  const queryClient = useQueryClient();
  const toast = useToast();

  const [search, setSearch] = useState("");
  const [listedOnly, setListedOnly] = useState(true);
  const [editing, setEditing] = useState<Issuer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState<PageState>({ limit: 50, offset: 0 });
  const [subSectors, setSubSectors] = useState<string[]>([]);

  const issuers = useQuery({
    queryKey: ["issuers", search, listedOnly, subSectors, page],
    queryFn: async () => {
      const { data, error: failed } = await api.GET("/admin/issuers", {
        params: { query: { search: search.trim() || undefined, listed_only: listedOnly, limit: 200 } },
      });
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
      return {
        items: (data?.items ?? []).map(normalised),
        total: data?.total ?? 0,
      };
    },
  });

  const options = useQuery({
    queryKey: ["issuer-sub-sectors", listedOnly],
    queryFn: async () => {
      const { data, error: failed } = await api.GET("/admin/issuers/sub-sectors", {
        params: { query: { listed_only: listedOnly } },
      });
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
      return data ?? [];
    },
  });

  const sync = useMutation({
    mutationFn: async () => {
      const { data, error: failed } = await api.POST("/admin/issuers/sync", {});
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
      return data;
    },
    onSuccess: (job) => {
      toast.show({ title: t("admin.issuers.syncQueued"), body: job?.note ?? undefined, tone: "success" });
    },
    onError: (caught: Error) => setError(caught.message),
  });

  const save = useMutation({
    mutationFn: async (input: { id: string; aliases: string[] }) => {
      const { error: failed } = await api.PATCH("/admin/issuers/{issuer_id}", {
        params: { path: { issuer_id: input.id } },
        body: { aliases: input.aliases },
      });
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
    },
    onSuccess: () => {
      setEditing(null);
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["issuers"] });
      toast.show({ title: t("admin.issuers.saved"), tone: "success" });
    },
    // Shown in the dialog rather than as a toast: an alias refused for being
    // too general is a correction to make, not news to acknowledge.
    onError: (caught: Error) => setError(caught.message),
  });

  return (
    <Card
      title={t("admin.issuers.title")}
      action={
        <Button size="sm" variant="ghost" disabled={sync.isPending} onClick={() => sync.mutate()}>
          {t("admin.issuers.sync")}
        </Button>
      }
    >
      {error && !editing && (
        <div className="mb-3">
          <ErrorNote message={error} onRetry={() => setError(null)} />
        </div>
      )}

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input
          className={`${inputClass} min-w-48 flex-1`}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setPage((current) => ({ ...current, offset: 0 }));
          }}
          placeholder={t("admin.issuers.searchPlaceholder")}
          aria-label={t("common.search")}
        />
        <MultiSelect
          label={t("admin.issuers.subSectorFilter")}
          placeholder={t("admin.issuers.subSectorFilter")}
          options={options.data ?? []}
          selected={subSectors}
          onChange={(next) => {
            setSubSectors(next);
            setPage((current) => ({ ...current, offset: 0 }));
          }}
        />
        <label className="flex items-center gap-1.5 text-xs text-muted">
          <input
            type="checkbox"
            checked={listedOnly}
            onChange={(event) => setListedOnly(event.target.checked)}
            className="accent-rise"
          />
          {t("admin.issuers.listedOnly")}
        </label>
      </div>

      {issuers.isLoading ? (
        <Loading />
      ) : issuers.isError ? (
        <ErrorNote
          message={(issuers.error as Error).message}
          onRetry={() => issuers.refetch()}
        />
      ) : !issuers.data?.items.length ? (
        <Empty
          message={t("admin.issuers.empty")}
          hint={t("admin.issuers.emptyHint")}
          action={
            <Button disabled={sync.isPending} onClick={() => sync.mutate()}>
              {t("admin.issuers.sync")}
            </Button>
          }
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs text-faint">
                <th className="pb-2 pr-4 font-medium">{t("portfolio.ticker")}</th>
                <th className="pb-2 pr-4 font-medium">{t("admin.issuers.name")}</th>
                <th className="pb-2 pr-4 font-medium">{t("admin.issuers.sector")}</th>
                <th className="pb-2 pr-4 font-medium">{t("admin.issuers.aliases")}</th>
                <th className="pb-2 font-medium" />
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {issuers.data.items.map((issuer) => (
                <tr key={issuer.id}>
                  <td className="py-2.5 pr-4 font-mono text-xs text-ink">{issuer.ticker}</td>
                  <td className="py-2.5 pr-4 text-ink/85">
                    {issuer.name}
                    {!issuer.is_listed && (
                      <span className="ml-2 rounded border border-line px-1 py-0.5 text-[0.65rem] text-faint">
                        {t("admin.issuers.delisted")}
                      </span>
                    )}
                  </td>
                  <td className="py-2.5 pr-4 text-xs text-muted">{issuer.sub_sector ?? issuer.sector ?? "—"}</td>
                  <td className="py-2.5 pr-4">
                    <div className="flex flex-wrap gap-1">
                      {issuer.effective_aliases.slice(0, 4).map((alias) => (
                        <span
                          key={alias}
                          // The ones typed here are marked, because the
                          // difference between "we derived this" and "somebody
                          // decided this" is the difference between a bug and
                          // a decision.
                          className={`rounded border px-1.5 py-0.5 text-[0.7rem] ${
                            issuer.aliases.includes(alias)
                              ? "border-rise/30 text-rise"
                              : "border-line text-faint"
                          }`}
                        >
                          {alias}
                        </span>
                      ))}
                      {issuer.effective_aliases.length > 4 && (
                        <span className="text-[0.7rem] text-faint">
                          +{issuer.effective_aliases.length - 4}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="py-2.5 text-right">
                    <Button size="sm" variant="ghost" onClick={() => setEditing(issuer)}>
                      {t("admin.issuers.edit")}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pager
            total={issuers.data?.total ?? 0}
            shown={issuers.data?.items.length ?? 0}
            page={page}
            onChange={setPage}
          />
        </div>
      )}

      <Caveat>{t("admin.issuers.caveat")}</Caveat>

      {editing && (
        <AliasEditor
          issuer={editing}
          error={error}
          busy={save.isPending}
          syncedAt={dateTime(editing.synced_at)}
          onCancel={() => {
            setEditing(null);
            setError(null);
          }}
          onSave={(aliases) => save.mutate({ id: editing.id, aliases })}
        />
      )}
    </Card>
  );
}

function AliasEditor({
  issuer,
  error,
  busy,
  syncedAt,
  onCancel,
  onSave,
}: {
  issuer: Issuer;
  error: string | null;
  busy: boolean;
  syncedAt: string;
  onCancel: () => void;
  onSave: (aliases: string[]) => void;
}) {
  const { t } = useI18n();
  const [text, setText] = useState(issuer.aliases.join("\n"));

  // Only the extras are editable. Everything else on the row comes from the
  // exchange and would be overwritten by the next synchronisation, so offering
  // it as a field would be offering an edit that silently expires.
  const derived = issuer.effective_aliases.filter((a) => !issuer.aliases.includes(a));

  return (
    <Modal
      title={`${issuer.ticker} — ${issuer.name}`}
      onClose={onCancel}
      footer={
        <>
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            {t("common.cancel")}
          </Button>
          <Button
            busy={busy}
            onClick={() =>
              onSave(
                text
                  .split("\n")
                  .map((line) => line.trim())
                  .filter(Boolean),
              )
            }
          >
            {t("common.save")}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {error && <ErrorNote message={error} />}

        <div>
          <p className="text-xs text-faint">{t("admin.issuers.automatic")}</p>
          <div className="mt-1 flex flex-wrap gap-1">
            {derived.length ? (
              derived.map((alias) => (
                <span
                  key={alias}
                  className="rounded border border-line px-1.5 py-0.5 text-[0.7rem] text-faint"
                >
                  {alias}
                </span>
              ))
            ) : (
              <span className="text-xs text-faint">—</span>
            )}
          </div>
        </div>

        <Field label={t("admin.issuers.extraAliases")} hint={t("admin.issuers.extraHint")}>
          <textarea
            className={`${inputClass} min-h-28 font-mono text-xs`}
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder={"bri\nbank bri"}
          />
        </Field>

        <p className="text-xs text-faint">
          {t("admin.issuers.syncedAt", { when: syncedAt })}
        </p>
      </div>
    </Modal>
  );
}
