import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { useI18n } from "@/i18n/context";
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
    if (settings.data) setCron(settings.data.news_sweep_cron);
  }, [settings.data]);

  const save = useMutation({
    mutationFn: async (patch: { registration_open?: boolean; news_sweep_cron?: string }) => {
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
