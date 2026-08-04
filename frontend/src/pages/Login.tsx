import { useState } from "react";
import { useAuth } from "@/auth/context";
import { useI18n, type MessageKey } from "@/i18n/context";
import { id as messages } from "@/i18n/messages";
import { Button, Field, inputClass } from "@/components/primitives";

export function Login() {
  const { t } = useI18n();
  const { signIn, signUp, expiredNotice, dismissExpiredNotice } = useAuth();

  const [mode, setMode] = useState<"signIn" | "signUp">("signIn");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    dismissExpiredNotice();
    try {
      if (mode === "signIn") await signIn(email, password);
      else await signUp(email, password, fullName);
    } catch (caught) {
      // The server's own message is shown when it has one: "password must
      // contain a digit" is worth reading, and replacing it with a generic
      // failure leaves someone guessing at a rule the server already stated.
      // What comes back may instead be one of our message keys, so both are
      // handled rather than one being assumed.
      const raw = caught instanceof Error ? caught.message : "";
      const isKey = raw in messages;
      setError(
        isKey
          ? t(raw as MessageKey)
          : raw || t(mode === "signIn" ? "auth.failed" : "auth.registerFailed"),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="text-lg font-semibold text-ink">{t("app.name")}</h1>
          <p className="mt-1 text-xs text-faint">{t("app.tagline")}</p>
        </div>

        {expiredNotice && (
          <p className="mb-4 rounded-md border border-watch/30 bg-watch/5 px-3 py-2 text-xs text-watch">
            {t("auth.sessionExpired")}
          </p>
        )}

        <form
          onSubmit={submit}
          className="space-y-4 rounded-lg border border-line bg-raised p-5"
        >
          {mode === "signUp" && (
            <Field label={`${t("auth.fullName")} (${t("common.optional")})`}>
              <input
                className={inputClass}
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                autoComplete="name"
              />
            </Field>
          )}

          <Field label={t("auth.email")}>
            <input
              className={inputClass}
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
            />
          </Field>

          <Field
            label={t("auth.password")}
            hint={mode === "signUp" ? t("auth.passwordHint") : undefined}
          >
            <input
              className={inputClass}
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === "signIn" ? "current-password" : "new-password"}
            />
          </Field>

          {error && (
            <p className="rounded-md border border-fall/25 bg-fall/5 px-3 py-2 text-xs text-fall/90">
              {error}
            </p>
          )}

          <Button type="submit" busy={busy} className="w-full">
            {busy
              ? t(mode === "signIn" ? "auth.signingIn" : "auth.signingUp")
              : t(mode === "signIn" ? "auth.signIn" : "auth.signUp")}
          </Button>

          <p className="text-center text-xs text-faint">
            {t(mode === "signIn" ? "auth.noAccount" : "auth.haveAccount")}{" "}
            <button
              type="button"
              onClick={() => {
                setMode(mode === "signIn" ? "signUp" : "signIn");
                setError(null);
              }}
              className="text-rise hover:underline"
            >
              {t(mode === "signIn" ? "auth.signUp" : "auth.signIn")}
            </button>
          </p>
        </form>

        <p className="mt-6 text-center text-xs leading-relaxed text-faint">
          {t("disclaimer.short")}
        </p>
      </div>
    </div>
  );
}
