import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { useI18n, type MessageKey } from "@/i18n/context";
import { useToast } from "@/components/toastContext";
import { Card, Caveat, ErrorNote, Field, Loading } from "@/components/primitives";
import type { components } from "@/api/schema";

const FIELDS = [
  { key: "investment_horizon", options: ["short", "medium", "long"] },
  { key: "risk_appetite", options: ["conservative", "moderate", "aggressive"] },
  { key: "experience_level", options: ["beginner", "intermediate", "advanced"] },
  { key: "explanation_depth", options: ["brief", "standard", "detailed"] },
  { key: "privacy_mode", options: ["standard", "high"] },
] as const;

type Update = NonNullable<
  components["schemas"]["PreferencesUpdate"]
>;
type FieldKey = (typeof FIELDS)[number]["key"];
type Draft = { [K in FieldKey]: NonNullable<Update[K]> };

/**
 * How this investor invests, and what the analysis should do with that.
 *
 * The Memory Manager has stored these since the AI layer landed, and the
 * prompt context has carried them - but nothing ever set them, so every
 * analysis was written for the defaults. This is the screen that makes the
 * preference real.
 */
export function Profile() {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [error, setError] = useState<string | null>(null);

  const preferences = useQuery({
    queryKey: ["preferences"],
    queryFn: async () => {
      const { data, error: failed } = await api.GET("/me/preferences");
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
      return data;
    },
  });

  useEffect(() => {
    if (!preferences.data) return;
    setDraft({
      investment_horizon: preferences.data.investment_horizon,
      risk_appetite: preferences.data.risk_appetite,
      experience_level: preferences.data.experience_level,
      explanation_depth: preferences.data.explanation_depth,
      privacy_mode: preferences.data.privacy_mode,
    });
  }, [preferences.data]);

  const save = useMutation({
    mutationFn: async (patch: Update) => {
      const { data, error: failed } = await api.PATCH("/me/preferences", { body: patch });
      if (failed) throw new Error(errorMessage(failed, t("common.error")));
      return data;
    },
    onSuccess: () => {
      setError(null);
      toast.show({ title: t("profile.saved"), tone: "success" });
      queryClient.invalidateQueries({ queryKey: ["preferences"] });
    },
    onError: (caught: Error) => setError(caught.message),
  });

  if (preferences.isLoading || !draft) return <Loading />;
  if (preferences.isError)
    return (
      <ErrorNote
        message={(preferences.error as Error).message}
        onRetry={() => preferences.refetch()}
      />
    );

  const stated = new Set(preferences.data?.stated ?? []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-ink">{t("profile.title")}</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">{t("profile.intro")}</p>
      </div>

      {error && <ErrorNote message={error} onRetry={() => setError(null)} />}

      <Card title={t("profile.howYouInvest")}>
        <div className="space-y-5">
          {FIELDS.map(({ key, options }) => (
            <Field
              key={key}
              label={t(`profile.${key}` as MessageKey)}
              hint={t(`profile.${key}.hint` as MessageKey)}
            >
              {/* Radio buttons rather than a select. There are three options
                  with real consequences, and a collapsed control hides two of
                  them behind a click on the screen whose whole purpose is to
                  make the reader consider all three. */}
              <div className="flex flex-wrap gap-2">
                {options.map((option) => {
                  const active = draft[key] === option;
                  return (
                    <button
                      key={option}
                      type="button"
                      onClick={() => {
                        setDraft({ ...draft, [key]: option } as Draft);
                        save.mutate({ [key]: option } as Update);
                      }}
                      className={`rounded-md border px-3 py-1.5 text-sm transition-colors ${
                        active
                          ? "border-rise/50 bg-rise/10 text-ink"
                          : "border-line text-muted hover:text-ink"
                      }`}
                    >
                      {t(`profile.${key}.${option}` as MessageKey)}
                    </button>
                  );
                })}
                {/* Says plainly whether this is an answer or a stand-in. An
                    inferred or defaulted preference reflected back as though
                    the reader chose it is how a product starts being confidently
                    wrong about people. */}
                {!stated.has(key) && (
                  <span className="self-center text-xs text-faint">
                    {t("profile.notStated")}
                  </span>
                )}
              </div>
            </Field>
          ))}
        </div>

        <Caveat>{t("profile.framingCaveat")}</Caveat>
      </Card>
    </div>
  );
}
