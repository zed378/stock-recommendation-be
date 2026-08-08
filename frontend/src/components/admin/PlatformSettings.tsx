import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { useI18n, type MessageKey } from "@/i18n/context";
import { useToast } from "@/components/toastContext";
import {
  Button,
  Card,
  Caveat,
  ErrorNote,
  Field,
  inputClass,
  Loading,
} from "@/components/primitives";

/**
 * Operator choices that apply without a redeploy.
 *
 * These used to be environment variables, which put them in the hands of
 * whoever deploys and made them take effect at boot. That is right for a
 * database URL and wrong for "is registration open right now" - a decision
 * someone makes at 11pm because an invitation link leaked.
 */
export function PlatformSettingsPanel() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const toast = useToast();

  const [cron, setCron] = useState("");
  const [marketCron, setMarketCron] = useState("");
  const [jitter, setJitter] = useState("");
  const [error, setError] = useState<string | null>(null);

  const settings = useQuery({
    queryKey: ["platform-settings"],
    queryFn: async () => {
      const { data, error: failed } = await api.GET("/admin/settings");
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
      return data;
    },
  });

  // Seeded from the server once it arrives, rather than held as the only copy:
  // an input whose value is the query result cannot be typed in, and one that
  // never syncs shows a stale schedule after somebody else changes it.
  useEffect(() => {
    if (!settings.data) return;
    setCron(settings.data.news_sweep_cron);
    setMarketCron(settings.data.market_scan_cron);
    setJitter(String(settings.data.market_scan_jitter_seconds));
  }, [settings.data]);

  /**
   * The three manual triggers.
   *
   * Separate buttons rather than one, because they fail for different reasons
   * and are worth retrying apart: the backfill and the fetch talk to the
   * exchange, the scan needs no network at all and is what you press after a
   * rule changes.
   */
  const trigger = useMutation({
    mutationFn: async (what: "fetch" | "scan" | "backfill") => {
      const path = `/admin/market/${what}` as
        | "/admin/market/fetch"
        | "/admin/market/scan"
        | "/admin/market/backfill";
      const { data, error: failed } = await api.POST(path, {});
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
      return data;
    },
    onSuccess: (job) => {
      toast.show({ title: t("admin.market.queued"), body: job?.note ?? undefined, tone: "success" });
    },
    onError: (caught: Error) => setError(caught.message),
  });

  const save = useMutation({
    mutationFn: async (patch: {
      registration_open?: boolean;
      news_sweep_cron?: string;
      market_scan_cron?: string;
      market_scan_jitter_seconds?: number;
    }) => {
      const { data, error: failed } = await api.PATCH("/admin/settings", { body: patch });
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
      return data;
    },
    onSuccess: () => {
      setError(null);
      toast.show({ title: t("admin.settings.saved"), tone: "success" });
      queryClient.invalidateQueries({ queryKey: ["platform-settings"] });
    },
    onError: (caught: Error) => setError(caught.message),
  });

  if (settings.isLoading) return <Loading />;
  if (settings.isError)
    return (
      <ErrorNote
        message={(settings.error as Error).message}
        onRetry={() => settings.refetch()}
      />
    );

  const open = settings.data?.registration_open ?? true;

  return (
    <Card title={t("admin.settings.title")}>
      {error && (
        <div className="mb-3">
          <ErrorNote message={error} onRetry={() => setError(null)} />
        </div>
      )}

      <div className="space-y-5">
        <div>
          <label className="flex items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              className="accent-rise"
              checked={open}
              disabled={save.isPending}
              // Saved on toggle rather than behind a Save button. There is one
              // field and its effect is immediate; a switch that needs
              // confirming is a switch someone leaves half-flipped.
              onChange={(event) => save.mutate({ registration_open: event.target.checked })}
            />
            {t("admin.settings.registration")}
          </label>
          <p className="mt-1 text-xs text-faint">{t("admin.settings.registrationHint")}</p>
        </div>

        <div className="space-y-2 border-t border-line pt-4">
          <p className="text-sm font-medium text-ink">{t("admin.market.title")}</p>
          <p className="text-xs text-faint">{t("admin.market.hint")}</p>
          <div className="flex flex-wrap gap-2">
            {(["fetch", "scan", "backfill"] as const).map((what) => (
              <Button
                key={what}
                variant="ghost"
                size="sm"
                disabled={trigger.isPending}
                onClick={() => trigger.mutate(what)}
              >
                {t(`admin.market.${what}` as MessageKey)}
              </Button>
            ))}
          </div>
        </div>

        <Field
          label={t("admin.settings.marketCron")}
          hint={t("admin.settings.marketCronHint")}
        >
          <div className="flex flex-wrap gap-2">
            <input
              className={`${inputClass} min-w-48 flex-1 font-mono text-xs`}
              value={marketCron}
              onChange={(event) => setMarketCron(event.target.value)}
              placeholder="0 18 * * 1-5"
            />
            <input
              type="number"
              className={`${inputClass} w-28 text-xs`}
              value={jitter}
              onChange={(event) => setJitter(event.target.value)}
              aria-label={t("admin.settings.jitter")}
            />
            <Button
              busy={save.isPending}
              onClick={() =>
                save.mutate({
                  market_scan_cron: marketCron,
                  market_scan_jitter_seconds: Number(jitter) || 0,
                })
              }
            >
              {t("common.save")}
            </Button>
          </div>
        </Field>
        <p className="-mt-3 text-xs text-faint">{t("admin.settings.jitterHint")}</p>

        <Field
          label={t("admin.settings.newsCron")}
          hint={t("admin.settings.newsCronHint")}
        >
          <div className="flex flex-wrap gap-2">
            <input
              className={`${inputClass} min-w-48 flex-1 font-mono text-xs`}
              value={cron}
              onChange={(event) => setCron(event.target.value)}
              placeholder="0 */2 * * *"
            />
            <Button
              busy={save.isPending}
              onClick={() => save.mutate({ news_sweep_cron: cron })}
            >
              {t("common.save")}
            </Button>
          </div>
        </Field>
      </div>

      <Caveat>{t("admin.settings.caveat")}</Caveat>
    </Card>
  );
}
