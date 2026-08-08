import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { useI18n } from "@/i18n/context";
import { useToast } from "@/components/toastContext";
import {
  Button,
  Card,
  Caveat,
  Empty,
  ErrorNote,
  Field,
  Loading,
  inputClass,
  inlineControlClass,
} from "@/components/primitives";

/**
 * What this account shows other people, and what they show it.
 *
 * There is no "copy link" button here and there will not be one. A URL
 * carrying investment analysis about a named company forwards itself, cannot
 * be withdrawn once it is in a group chat, and makes the audience unknowable -
 * and the audience has to stay knowable for the redistribution question to
 * have an answer at all.
 */
export function Shared() {
  const { t, date } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const incoming = useQuery({
    queryKey: ["shares", "incoming"],
    queryFn: async () => {
      const { data, error: failed } = await api.GET("/shares/incoming");
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
      return data;
    },
  });

  const outgoing = useQuery({
    queryKey: ["shares", "outgoing"],
    queryFn: async () => {
      const { data, error: failed } = await api.GET("/shares/outgoing");
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
      return data;
    },
  });

  const revoke = useMutation({
    mutationFn: async (id: string) => {
      const { error: failed } = await api.DELETE("/shares/{share_id}", {
        params: { path: { share_id: id } },
      });
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
    },
    onSuccess: () => {
      toast.show({ title: t("shared.revoked"), tone: "success" });
      queryClient.invalidateQueries({ queryKey: ["shares"] });
    },
    onError: (caught: Error) => setError(caught.message),
  });

  if (incoming.isLoading || outgoing.isLoading) return <Loading />;

  const received = incoming.data ?? [];
  const sent = outgoing.data ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-ink">{t("shared.title")}</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">{t("shared.intro")}</p>
      </div>

      {error && <ErrorNote message={error} onRetry={() => setError(null)} />}

      <Card title={t("shared.incoming")}>
        {received.length === 0 ? (
          <Empty message={t("shared.noIncoming")} hint={t("shared.noIncomingHint")} />
        ) : (
          <ul className="divide-y divide-line">
            {received.map((item) => (
              <li key={item.id} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 py-3">
                <span className="rounded border border-line px-1.5 py-0.5 text-xs text-faint">
                  {t(item.kind === "watchlist" ? "shared.kindWatchlist" : "shared.kindAnalysis")}
                </span>
                <span className="text-sm font-medium text-ink">{item.label}</span>
                <span className="text-xs text-muted">{item.counterpart_email}</span>
                {item.note && (
                  <span className="min-w-0 flex-1 truncate text-sm text-ink/70">
                    &ldquo;{item.note}&rdquo;
                  </span>
                )}
                <span className="ml-auto font-mono text-xs tnum text-faint">
                  {date(item.created_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
        <Caveat>{t("shared.recipientCaveat")}</Caveat>
      </Card>

      <ShareForm onError={setError} />

      <Card title={t("shared.outgoing")}>
        {sent.length === 0 ? (
          <Empty message={t("shared.noOutgoing")} />
        ) : (
          <ul className="divide-y divide-line">
            {sent.map((item) => (
              <li key={item.id} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 py-3">
                <span className="rounded border border-line px-1.5 py-0.5 text-xs text-faint">
                  {t(item.kind === "watchlist" ? "shared.kindWatchlist" : "shared.kindAnalysis")}
                </span>
                <span className="text-sm font-medium text-ink">{item.label}</span>
                <span className="text-xs text-muted">{item.counterpart_email}</span>
                {/* Withdrawn shares stay listed rather than disappearing.
                    "This was shared and then taken back" is the question the
                    list exists to answer, and a row that vanishes cannot. */}
                {item.revoked_at ? (
                  <span className="ml-auto text-xs text-faint">
                    {t("shared.revokedOn")} {date(item.revoked_at)}
                  </span>
                ) : (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="ml-auto"
                    busy={revoke.isPending}
                    onClick={() => revoke.mutate(item.id)}
                  >
                    {t("shared.revoke")}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function ShareForm({ onError }: { onError: (message: string | null) => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [kind, setKind] = useState<"watchlist" | "analysis">("watchlist");
  const [subject, setSubject] = useState("");
  const [note, setNote] = useState("");

  const watchlists = useQuery({
    queryKey: ["watchlist", "categories"],
    queryFn: async () => {
      const { data, error } = await api.GET("/watchlist/categories");
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data;
    },
  });

  const create = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/shares", {
        body: {
          recipient_email: email.trim(),
          kind,
          subject_id: subject,
          note: note.trim() || null,
        },
      });
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data;
    },
    onSuccess: () => {
      onError(null);
      setEmail("");
      setNote("");
      toast.show({ title: t("shared.sent"), tone: "success" });
      queryClient.invalidateQueries({ queryKey: ["shares"] });
    },
    onError: (caught: Error) => onError(caught.message),
  });

  return (
    <Card title={t("shared.share")}>
      <div className="space-y-4">
        <Field label={t("shared.recipient")} hint={t("shared.recipientHint")}>
          <input
            className={inputClass}
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="name@example.com"
            type="email"
          />
        </Field>

        <Field label={t("shared.what")}>
          <div className="flex flex-wrap gap-2">
            {(["watchlist", "analysis"] as const).map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => {
                  setKind(option);
                  setSubject("");
                }}
                className={`rounded-md border px-3 py-1.5 text-sm transition-colors ${
                  kind === option
                    ? "border-rise/50 bg-rise/10 text-ink"
                    : "border-line text-muted hover:text-ink"
                }`}
              >
                {t(option === "watchlist" ? "shared.kindWatchlist" : "shared.kindAnalysis")}
              </button>
            ))}
          </div>
        </Field>

        {kind === "watchlist" ? (
          <Field label={t("shared.pickWatchlist")}>
            <select
              className={inputClass}
              value={subject}
              onChange={(event) => setSubject(event.target.value)}
            >
              <option value="">{t("shared.choose")}</option>
              {(watchlists.data ?? []).map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name} ({row.count})
                </option>
              ))}
            </select>
          </Field>
        ) : (
          <Field label={t("shared.analysisId")} hint={t("shared.analysisIdHint")}>
            <input
              className={`${inputClass} font-mono text-xs`}
              value={subject}
              onChange={(event) => setSubject(event.target.value)}
              placeholder="00000000-0000-0000-0000-000000000000"
            />
          </Field>
        )}

        <Field label={t("shared.note")}>
          <input
            className={inputClass}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            maxLength={500}
          />
        </Field>

        <Button
          className={inlineControlClass}
          busy={create.isPending}
          disabled={!email.trim() || !subject}
          onClick={() => create.mutate()}
        >
          {t("shared.send")}
        </Button>
      </div>

      <Caveat>{t("shared.ownerCaveat")}</Caveat>
    </Card>
  );
}
