import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { useAuth } from "@/auth/context";
import { useI18n, type MessageKey } from "@/i18n/context";
import { Pager, type PageState } from "@/components/Pager";
import { useToast } from "@/components/toastContext";
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

type AdminUser = components["schemas"]["AdminUserResponse"];

/** What an in-flight or failed query renders as, so the table has one shape. */
const EMPTY_PAGE = { items: [] as AdminUser[], total: 0, limit: 50, offset: 0 };
type Role = components["schemas"]["UserRole"];

/** Preset lengths, because "three days" is what an admin actually decides. */
const SUSPEND_PRESETS = [1, 3, 7, 30] as const;

/**
 * Status to message key, spelled out rather than interpolated.
 *
 * `t()` is typed against the message table, so a computed key would compile to
 * `any` and a status the backend adds later would render as its own raw name.
 * The map turns that into a compile error the day the enum grows.
 */
const STATUS_LABELS: Record<string, MessageKey> = {
  active: "admin.users.status.active",
  suspended: "admin.users.status.suspended",
  banned: "admin.users.status.banned",
};
const fallback: MessageKey = "admin.users.status.active";

/** What is about to be applied, once its dialog is confirmed. */
type Action =
  | { kind: "suspend"; until: string | null; reason: string }
  | { kind: "ban"; reason: string }
  | { kind: "reinstate" }
  | { kind: "role"; role: Role }
  | { kind: "delete" };

type ActionKind = Action["kind"];

/** One account's result. Kept per user so a partial failure can name names. */
type Outcome = { email: string; ok: boolean; error?: string };

/**
 * Apply one action to one account.
 *
 * The single-user buttons and the batch bar both go through here, so a batch is
 * literally a list of the same calls the individual button makes - including
 * the server-side guards and the audit entry each one writes. There is no bulk
 * endpoint on purpose: it would have to re-implement "not yourself" and "not
 * the last admin", and decide what a half-applied batch means.
 */
async function applyTo(
  user: AdminUser,
  action: Action,
  fallbackMessage: string,
): Promise<void> {
  const path = { user_id: user.id };

  if (action.kind === "delete") {
    const { error } = await api.DELETE("/admin/users/{user_id}", { params: { path } });
    if (error) throw new Error(errorMessage(error, fallbackMessage));
    return;
  }
  if (action.kind === "reinstate") {
    const { error } = await api.POST("/admin/users/{user_id}/reinstate", {
      params: { path },
    });
    if (error) throw new Error(errorMessage(error, fallbackMessage));
    return;
  }
  if (action.kind === "role") {
    const { error } = await api.PATCH("/admin/users/{user_id}/role", {
      params: { path },
      body: { role: action.role },
    });
    if (error) throw new Error(errorMessage(error, fallbackMessage));
    return;
  }
  if (action.kind === "suspend") {
    const { error } = await api.POST("/admin/users/{user_id}/suspend", {
      params: { path },
      body: { until: action.until, reason: action.reason || null },
    });
    if (error) throw new Error(errorMessage(error, fallbackMessage));
    return;
  }
  const { error } = await api.POST("/admin/users/{user_id}/ban", {
    params: { path },
    body: { reason: action.reason || null },
  });
  if (error) throw new Error(errorMessage(error, fallbackMessage));
}

/**
 * Account administration.
 *
 * Every action here is one person acting on something another person depends
 * on, so each one names its consequence before it happens rather than after.
 * Delete in particular says what it takes with it: the backend cascades
 * watchlists, portfolios, and the journal, and there is no undo.
 */
export function UsersPanel() {
  const { t, dateTime } = useI18n();
  const { user: me } = useAuth();
  const queryClient = useQueryClient();

  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [asking, setAsking] = useState<{ kind: ActionKind; targets: AdminUser[] } | null>(
    null,
  );
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [outcomes, setOutcomes] = useState<{ kind: ActionKind; rows: Outcome[] } | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  // Reset to the first page whenever the filter changes: an offset kept
  // across a new search lands on rows the reader never asked about.
  const [page, setPage] = useState<PageState>({ limit: 50, offset: 0 });
  const [creating, setCreating] = useState(false);

  const users = useQuery({
    queryKey: ["admin-users", query, page],
    queryFn: async () => {
      const { data, error: failed } = await api.GET("/admin/users", {
        params: {
          query: {
            ...(query.trim() ? { q: query.trim() } : {}),
            limit: page.limit,
            offset: page.offset,
          },
        },
      });
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
      return data ?? EMPTY_PAGE;
    },
    placeholderData: (previous) => previous,
  });

  const rows = useMemo(() => users.data?.items ?? [], [users.data]);

  /**
   * Own account excluded from selection entirely.
   *
   * The server refuses it anyway, but a checkbox that can be ticked and then
   * always fails is a trap: it would make every batch report one failure the
   * admin did not cause and cannot fix.
   */
  const selectable = useMemo(
    () => rows.filter((row) => row.id !== me?.id),
    [rows, me?.id],
  );

  const chosen = useMemo(
    () => selectable.filter((row) => selected.has(row.id)),
    [selectable, selected],
  );

  const allChosen = selectable.length > 0 && chosen.length === selectable.length;

  const toggleOne = (id: string) =>
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const toggleAll = () =>
    setSelected(allChosen ? new Set() : new Set(selectable.map((row) => row.id)));

  /**
   * Run one action across the chosen accounts.
   *
   * Sequential, not parallel: the audit trail reads in the order an admin
   * chose, and a hundred concurrent writes to the same table buys nothing at
   * this scale. Every account is attempted even after one fails - stopping at
   * the first would leave a batch half-applied with no record of where it got
   * to.
   */
  const run = async (kind: ActionKind, targets: AdminUser[], action: Action) => {
    setAsking(null);
    setError(null);
    setProgress({ done: 0, total: targets.length });

    const results: Outcome[] = [];
    for (const [index, target] of targets.entries()) {
      try {
        await applyTo(target, action, t("common.error"));
        results.push({ email: target.email, ok: true });
      } catch (caught) {
        results.push({
          email: target.email,
          ok: false,
          error: caught instanceof Error ? caught.message : String(caught),
        });
      }
      setProgress({ done: index + 1, total: targets.length });
    }

    setProgress(null);
    setSelected(new Set());
    queryClient.invalidateQueries({ queryKey: ["admin-users"] });

    // Shown whenever more than one account was touched, and whenever anything
    // failed. A batch that quietly reports success for the ones that worked is
    // how an admin comes to believe forty accounts were suspended when
    // thirty-eight were.
    if (targets.length > 1 || results.some((r) => !r.ok)) {
      setOutcomes({ kind, rows: results });
    }
  };

  const ask = (kind: ActionKind, targets: AdminUser[]) => {
    if (targets.length) setAsking({ kind, targets });
  };

  return (
    <Card
      title={t("admin.users.title")}
      action={
        <Button size="sm" variant="ghost" onClick={() => setCreating(true)}>
          {t("admin.users.create")}
        </Button>
      }
    >
      <input
        className={inputClass}
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setPage((current) => ({ ...current, offset: 0 }));
        }}
        placeholder={t("admin.users.searchPlaceholder")}
        aria-label={t("common.search")}
        type="search"
      />

      {error && (
        <div className="mt-3">
          <ErrorNote message={error} onRetry={() => setError(null)} />
        </div>
      )}

      {chosen.length > 0 && (
        <SelectionBar
          count={chosen.length}
          disabled={progress !== null}
          onClear={() => setSelected(new Set())}
          onAction={(kind) => ask(kind, chosen)}
        />
      )}

      {progress && (
        <p className="mt-3 rounded-md border border-line bg-hover/30 px-3 py-2 text-xs text-muted">
          {t("admin.users.batchProgress", {
            done: progress.done,
            total: progress.total,
          })}
        </p>
      )}

      {users.isLoading ? (
        <Loading />
      ) : users.isError ? (
        <ErrorNote
          message={(users.error as Error).message}
          onRetry={() => users.refetch()}
        />
      ) : !rows.length ? (
        <Empty message={t("admin.users.empty")} />
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-208 text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs text-faint">
                <th className="w-8 py-2 pr-2">
                  <input
                    type="checkbox"
                    checked={allChosen}
                    // Some are ticked but not all: a plain unchecked box would
                    // claim nothing is selected while the bar above says four.
                    ref={(node) => {
                      if (node) {
                        node.indeterminate = chosen.length > 0 && !allChosen;
                      }
                    }}
                    onChange={toggleAll}
                    disabled={!selectable.length}
                    aria-label={t("admin.users.selectAll")}
                    className="h-3.5 w-3.5 rounded border-line"
                  />
                </th>
                <th className="py-2 pr-3 font-medium">{t("admin.users.account")}</th>
                <th className="py-2 pr-3 font-medium">{t("admin.users.role")}</th>
                <th className="py-2 pr-3 font-medium">{t("admin.users.status")}</th>
                <th className="py-2 pr-3 font-medium">{t("admin.users.since")}</th>
                <th className="py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const isSelf = row.id === me?.id;
                return (
                  <tr
                    key={row.id}
                    className={`border-b border-line/60 last:border-b-0 ${
                      selected.has(row.id) ? "bg-hover/30" : ""
                    }`}
                  >
                    <td className="py-2.5 pr-2 align-top">
                      <input
                        type="checkbox"
                        checked={selected.has(row.id)}
                        onChange={() => toggleOne(row.id)}
                        disabled={isSelf || progress !== null}
                        aria-label={t("admin.users.select", { email: row.email })}
                        className="mt-1 h-3.5 w-3.5 rounded border-line disabled:opacity-40"
                      />
                    </td>
                    <td className="py-2.5 pr-3">
                      <div className="text-ink">{row.email}</div>
                      {row.full_name && (
                        <div className="text-xs text-faint">{row.full_name}</div>
                      )}
                      {isSelf && (
                        <div className="text-xs text-muted">{t("admin.users.you")}</div>
                      )}
                    </td>
                    <td className="py-2.5 pr-3">
                      <RoleBadge role={row.role} />
                    </td>
                    <td className="py-2.5 pr-3">
                      <StatusCell row={row} />
                    </td>
                    <td className="py-2.5 pr-3 text-xs text-faint">
                      {dateTime(row.created_at)}
                    </td>
                    <td className="py-2.5">
                      <div className="flex flex-wrap justify-end gap-1.5">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => ask("role", [row])}
                        >
                          {t("admin.users.changeRole")}
                        </Button>
                        {row.effective_status === "active" ? (
                          <>
                            <Button
                              size="sm"
                              variant="ghost"
                              disabled={isSelf}
                              onClick={() => ask("suspend", [row])}
                            >
                              {t("admin.users.suspend")}
                            </Button>
                            <Button
                              size="sm"
                              variant="danger"
                              disabled={isSelf}
                              onClick={() => ask("ban", [row])}
                            >
                              {t("admin.users.ban")}
                            </Button>
                          </>
                        ) : (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => run("reinstate", [row], { kind: "reinstate" })}
                          >
                            {t("admin.users.reinstate")}
                          </Button>
                        )}
                        <Button
                          size="sm"
                          variant="danger"
                          disabled={isSelf}
                          onClick={() => ask("delete", [row])}
                        >
                          {t("admin.users.delete")}
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <Pager
            total={users.data?.total ?? 0}
            shown={rows.length}
            page={page}
            onChange={setPage}
          />
        </div>
      )}

      <Caveat>{t("admin.users.caveat")}</Caveat>

      {asking?.kind === "suspend" && (
        <SuspendDialog
          targets={asking.targets}
          onCancel={() => setAsking(null)}
          onConfirm={(until, reason) =>
            run("suspend", asking.targets, { kind: "suspend", until, reason })
          }
        />
      )}

      {asking?.kind === "ban" && (
        <ReasonDialog
          title={titleFor(t, "admin.users.banTitle", "admin.users.banTitleMany", asking.targets)}
          note={t("admin.users.banNote")}
          confirmLabel={t("admin.users.ban")}
          targets={asking.targets}
          onCancel={() => setAsking(null)}
          onConfirm={(reason) => run("ban", asking.targets, { kind: "ban", reason })}
        />
      )}

      {asking?.kind === "role" && (
        <RoleDialog
          targets={asking.targets}
          isSelf={asking.targets.some((target) => target.id === me?.id)}
          onCancel={() => setAsking(null)}
          onConfirm={(role) => run("role", asking.targets, { kind: "role", role })}
        />
      )}

      {asking?.kind === "delete" && (
        <DeleteDialog
          targets={asking.targets}
          onCancel={() => setAsking(null)}
          onConfirm={() => run("delete", asking.targets, { kind: "delete" })}
        />
      )}

      {outcomes && (
        <OutcomeDialog outcomes={outcomes.rows} onClose={() => setOutcomes(null)} />
      )}
      {creating && (
        <CreateUserDialog
          onClose={() => setCreating(false)}
          onCreated={() => {
            setCreating(false);
            queryClient.invalidateQueries({ queryKey: ["admin-users"] });
          }}
        />
      )}
    </Card>
  );
}

/**
 * An account created by an administrator rather than by its owner.
 *
 * Exists because registration can be closed, and an operator who closed it
 * still needs to onboard people - otherwise the only ways in are reopening the
 * door for everyone or editing the database.
 *
 * The password is typed rather than generated. A generated one has to reach
 * the person somehow, and every convenient channel for that is a worse place
 * for a credential than wherever the admin was going to type it anyway.
 */
function CreateUserDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const [form, setForm] = useState({
    email: "",
    password: "",
    full_name: "",
    role: "investor" as Role,
  });
  const [error, setError] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: async () => {
      const { error: failed } = await api.POST("/admin/users", {
        body: {
          email: form.email.trim(),
          password: form.password,
          full_name: form.full_name.trim() || null,
          role: form.role,
        },
      });
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
    },
    onSuccess: () => {
      toast.show({ title: t("admin.users.created"), tone: "success" });
      onCreated();
    },
    onError: (caught: Error) => setError(caught.message),
  });

  return (
    <Modal
      title={t("admin.users.createTitle")}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={create.isPending}>
            {t("common.cancel")}
          </Button>
          <Button
            busy={create.isPending}
            disabled={!form.email.trim() || form.password.length < 8}
            onClick={() => create.mutate()}
          >
            {t("common.save")}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {error && <ErrorNote message={error} />}
        <p className="text-xs text-faint">{t("admin.users.createHint")}</p>

        <Field label={t("auth.email")}>
          <input
            type="email"
            className={inputClass}
            value={form.email}
            onChange={(event) => setForm({ ...form, email: event.target.value })}
          />
        </Field>

        <Field label={t("auth.password")}>
          <input
            type="password"
            className={inputClass}
            value={form.password}
            onChange={(event) => setForm({ ...form, password: event.target.value })}
          />
        </Field>

        <Field label={t("auth.fullName")}>
          <input
            className={inputClass}
            value={form.full_name}
            onChange={(event) => setForm({ ...form, full_name: event.target.value })}
          />
        </Field>

        <Field label={t("admin.users.role")}>
          <select
            className={inputClass}
            value={form.role}
            onChange={(event) => setForm({ ...form, role: event.target.value as Role })}
          >
            {(["viewer", "investor", "admin"] as const).map((role) => (
              <option key={role} value={role}>
                {role}
              </option>
            ))}
          </select>
        </Field>
      </div>
    </Modal>
  );
}

/** Singular or plural title, chosen by how many are actually selected. */
function titleFor(
  t: (key: MessageKey, values?: Record<string, string | number>) => string,
  one: MessageKey,
  many: MessageKey,
  targets: AdminUser[],
): string {
  return targets.length === 1
    ? t(one, { email: targets[0].email })
    : t(many, { count: targets.length });
}

/**
 * What can be done to everything currently ticked.
 *
 * Sits above the table rather than at the bottom of the page: the selection is
 * in the table, and an action bar somewhere else means scrolling away from
 * what you selected to act on it.
 */
function SelectionBar({
  count,
  disabled,
  onClear,
  onAction,
}: {
  count: number;
  disabled: boolean;
  onClear: () => void;
  onAction: (kind: ActionKind) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 rounded-md border border-rise/30 bg-rise/5 px-3 py-2">
      <span className="text-sm text-ink">{t("admin.users.selected", { count })}</span>
      <div className="ml-auto flex flex-wrap gap-1.5">
        <Button size="sm" variant="ghost" disabled={disabled} onClick={() => onAction("role")}>
          {t("admin.users.changeRole")}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={disabled}
          onClick={() => onAction("reinstate")}
        >
          {t("admin.users.reinstate")}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={disabled}
          onClick={() => onAction("suspend")}
        >
          {t("admin.users.suspend")}
        </Button>
        <Button size="sm" variant="danger" disabled={disabled} onClick={() => onAction("ban")}>
          {t("admin.users.ban")}
        </Button>
        <Button
          size="sm"
          variant="danger"
          disabled={disabled}
          onClick={() => onAction("delete")}
        >
          {t("admin.users.delete")}
        </Button>
        <Button size="sm" variant="ghost" disabled={disabled} onClick={onClear}>
          {t("admin.users.clearSelection")}
        </Button>
      </div>
    </div>
  );
}

/** The accounts a dialog is about, listed rather than counted. */
function TargetList({ targets }: { targets: AdminUser[] }) {
  const { t } = useI18n();
  if (targets.length === 1) return null;
  return (
    <div className="mb-3 max-h-32 overflow-y-auto rounded-md border border-line px-3 py-2">
      <p className="mb-1 text-xs text-faint">{t("admin.users.appliesTo")}</p>
      <ul className="space-y-0.5 text-xs text-muted">
        {targets.map((target) => (
          <li key={target.id}>{target.email}</li>
        ))}
      </ul>
    </div>
  );
}

function RoleBadge({ role }: { role: string }) {
  const tone =
    role === "admin"
      ? "border-watch/40 text-watch"
      : role === "viewer"
        ? "border-line text-faint"
        : "border-line text-muted";
  return (
    <span className={`rounded border px-1.5 py-0.5 text-xs uppercase ${tone}`}>{role}</span>
  );
}

/**
 * The status, and what it is actually doing.
 *
 * `status` is what was recorded; `effective_status` is what the auth gate
 * enforces right now. They differ exactly when a suspension has run out, and
 * showing only the first would have an admin chasing a lock that has already
 * lifted itself.
 */
function StatusCell({ row }: { row: AdminUser }) {
  const { t, dateTime } = useI18n();
  const expired = row.status !== "active" && row.effective_status === "active";

  const tone =
    row.effective_status === "active"
      ? "border-line text-muted"
      : row.status === "banned"
        ? "border-fall/40 text-fall"
        : "border-watch/40 text-watch";

  return (
    <div className="space-y-1">
      <span className={`rounded border px-1.5 py-0.5 text-xs ${tone}`}>
        {expired ? t("admin.users.statusExpired") : t(STATUS_LABELS[row.status] ?? fallback)}
      </span>
      {row.suspended_until && !expired && (
        <div className="text-xs text-faint">
          {t("admin.users.until", { when: dateTime(row.suspended_until) })}
        </div>
      )}
      {row.status_reason && (
        <div className="max-w-64 truncate text-xs text-faint" title={row.status_reason}>
          {row.status_reason}
        </div>
      )}
    </div>
  );
}

function SuspendDialog({
  targets,
  onCancel,
  onConfirm,
}: {
  targets: AdminUser[];
  onCancel: () => void;
  onConfirm: (until: string | null, reason: string) => void;
}) {
  const { t } = useI18n();
  const [days, setDays] = useState<number | null>(7);
  const [reason, setReason] = useState("");

  const until =
    days === null ? null : new Date(Date.now() + days * 86_400_000).toISOString();

  return (
    <Modal
      title={titleFor(t, "admin.users.suspendTitle", "admin.users.suspendTitleMany", targets)}
      onClose={onCancel}
      footer={
        <>
          <Button variant="ghost" onClick={onCancel}>
            {t("common.cancel")}
          </Button>
          <Button onClick={() => onConfirm(until, reason)}>
            {t("admin.users.suspend")}
          </Button>
        </>
      }
    >
      <TargetList targets={targets} />

      <Field label={t("admin.users.duration")}>
        <div className="flex flex-wrap gap-1.5">
          {SUSPEND_PRESETS.map((preset) => (
            <button
              key={preset}
              onClick={() => setDays(preset)}
              aria-pressed={days === preset}
              className={`rounded-md border px-2.5 py-1 text-xs transition-colors ${
                days === preset
                  ? "border-rise/40 bg-rise/10 text-rise"
                  : "border-line text-muted hover:text-ink"
              }`}
            >
              {t("admin.users.days", { count: preset })}
            </button>
          ))}
          <button
            onClick={() => setDays(null)}
            aria-pressed={days === null}
            className={`rounded-md border px-2.5 py-1 text-xs transition-colors ${
              days === null
                ? "border-watch/40 bg-watch/10 text-watch"
                : "border-line text-muted hover:text-ink"
            }`}
          >
            {t("admin.users.indefinite")}
          </button>
        </div>
      </Field>

      <div className="mt-3">
        <Field label={t("admin.users.reason")}>
          <input
            className={inputClass}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder={t("admin.users.reasonPlaceholder")}
            autoFocus
          />
        </Field>
      </div>
      {/* The reason is shown to each account holder at sign-in. Saying so here
          is what stops an internal note ending up in front of them - and in a
          batch it goes to every one of them, identically. */}
      <p className="mt-2 text-xs text-faint">
        {targets.length > 1 ? t("admin.users.reasonNoteMany") : t("admin.users.reasonNote")}
      </p>
    </Modal>
  );
}

function ReasonDialog({
  title,
  note,
  confirmLabel,
  targets,
  onCancel,
  onConfirm,
}: {
  title: string;
  note: string;
  confirmLabel: string;
  targets: AdminUser[];
  onCancel: () => void;
  onConfirm: (reason: string) => void;
}) {
  const { t } = useI18n();
  const [reason, setReason] = useState("");

  return (
    <Modal
      title={title}
      onClose={onCancel}
      footer={
        <>
          <Button variant="ghost" onClick={onCancel}>
            {t("common.cancel")}
          </Button>
          <Button variant="danger" onClick={() => onConfirm(reason)}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <TargetList targets={targets} />
      <p className="mb-3 leading-relaxed">{note}</p>
      <Field label={t("admin.users.reason")}>
        <input
          className={inputClass}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder={t("admin.users.reasonPlaceholder")}
          autoFocus
        />
      </Field>
      <p className="mt-2 text-xs text-faint">
        {targets.length > 1 ? t("admin.users.reasonNoteMany") : t("admin.users.reasonNote")}
      </p>
    </Modal>
  );
}

function RoleDialog({
  targets,
  isSelf,
  onCancel,
  onConfirm,
}: {
  targets: AdminUser[];
  isSelf: boolean;
  onCancel: () => void;
  onConfirm: (role: Role) => void;
}) {
  const { t } = useI18n();
  // No sensible starting point when the selection already spans several roles,
  // so it opens on the one they share or on nothing in particular.
  const shared = targets.every((target) => target.role === targets[0].role)
    ? (targets[0].role as Role)
    : ("investor" as Role);
  const [role, setRole] = useState<Role>(shared);

  return (
    <Modal
      title={titleFor(t, "admin.users.roleTitle", "admin.users.roleTitleMany", targets)}
      onClose={onCancel}
      footer={
        <>
          <Button variant="ghost" onClick={onCancel}>
            {t("common.cancel")}
          </Button>
          <Button onClick={() => onConfirm(role)}>{t("common.save")}</Button>
        </>
      }
    >
      <TargetList targets={targets} />
      <Field label={t("admin.users.role")}>
        <select
          className={inputClass}
          value={role}
          onChange={(event) => setRole(event.target.value as Role)}
          autoFocus
        >
          <option value="viewer">{t("admin.users.role.viewer")}</option>
          <option value="investor">{t("admin.users.role.investor")}</option>
          <option value="admin">{t("admin.users.role.admin")}</option>
        </select>
      </Field>
      <p className="mt-2 text-xs text-faint">{t("admin.users.roleNote")}</p>
      {isSelf && role !== "admin" && (
        // Stepping down is allowed, and it is one-way from inside the product:
        // there is no endpoint that grants admin, deliberately.
        <p className="mt-2 text-xs text-watch">{t("admin.users.stepDownWarning")}</p>
      )}
    </Modal>
  );
}

/**
 * Delete, with the count typed out.
 *
 * A batch delete removes several people's entire history in one click, and
 * "are you sure" stops meaning anything after the third time. Typing the number
 * is a small deliberate act that a mis-click cannot perform.
 */
function DeleteDialog({
  targets,
  onCancel,
  onConfirm,
}: {
  targets: AdminUser[];
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const { t } = useI18n();
  const [typed, setTyped] = useState("");
  const many = targets.length > 1;
  const confirmed = !many || typed.trim() === String(targets.length);

  return (
    <Modal
      title={t("admin.users.deleteTitle")}
      onClose={onCancel}
      footer={
        <>
          <Button variant="ghost" onClick={onCancel}>
            {t("common.cancel")}
          </Button>
          <Button variant="danger" onClick={onConfirm} disabled={!confirmed}>
            {t("admin.users.delete")}
          </Button>
        </>
      }
    >
      <TargetList targets={targets} />
      <p className="leading-relaxed">
        {many
          ? t("admin.users.deleteWarningMany", { count: targets.length })
          : t("admin.users.deleteWarning", { email: targets[0].email })}
      </p>
      {many && (
        <div className="mt-3">
          <Field label={t("admin.users.typeCount", { count: targets.length })}>
            <input
              className={inputClass}
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              inputMode="numeric"
              autoFocus
            />
          </Field>
        </div>
      )}
    </Modal>
  );
}

/**
 * What actually happened, per account.
 *
 * The whole reason this exists: the server refuses some of these per account -
 * the last administrator, for one - so a batch of forty can come back as
 * thirty-nine. Reporting only the total would turn that into a silent
 * discrepancy nobody finds until the account is still there next week.
 */
function OutcomeDialog({
  outcomes,
  onClose,
}: {
  outcomes: Outcome[];
  onClose: () => void;
}) {
  const { t } = useI18n();
  const failed = outcomes.filter((row) => !row.ok);
  const succeeded = outcomes.length - failed.length;

  return (
    <Modal
      title={t("admin.users.batchResult")}
      onClose={onClose}
      footer={
        <Button variant="ghost" onClick={onClose}>
          {t("common.close")}
        </Button>
      }
    >
      <p className="text-ink">
        {t("admin.users.batchSummary", { done: succeeded, total: outcomes.length })}
      </p>

      {failed.length > 0 && (
        <div className="mt-3 space-y-2">
          <p className="text-xs font-medium text-fall">
            {t("admin.users.batchFailed", { count: failed.length })}
          </p>
          <ul className="max-h-48 space-y-2 overflow-y-auto text-xs">
            {failed.map((row) => (
              <li key={row.email} className="border-l-2 border-fall/40 pl-2">
                <div className="text-ink">{row.email}</div>
                <div className="text-faint">{row.error}</div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Modal>
  );
}
