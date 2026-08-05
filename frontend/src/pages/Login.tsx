import { useState } from "react";
import { useAuth } from "@/auth/context";
import { useI18n, type MessageKey } from "@/i18n/context";
import { id as messages } from "@/i18n/messages";
import { Button, Field, inputClass } from "@/components/primitives";
import { Backdrop } from "@/components/Backdrop";

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
    <div className="relative min-h-full lg:grid lg:grid-cols-[1.1fr_1fr]">
      {/* The pitch, on the half of the screen that is otherwise empty space.
          Hidden below `lg` rather than stacked: on a phone it would push the
          form below the fold, and someone opening a sign-in page came to sign
          in. */}
      <aside className="relative hidden overflow-hidden border-r border-line lg:flex lg:flex-col lg:justify-between lg:p-12">
        <Backdrop />
        <div className="relative">
          <h1 className="text-xl font-semibold tracking-tight text-ink">
            {t("app.name")}
          </h1>
          <p className="mt-2 max-w-md text-sm leading-relaxed text-muted">
            {t("login.lede")}
          </p>
        </div>

        <ul className="relative space-y-4">
          {(
            [
              ["login.point1.title", "login.point1.body"],
              ["login.point2.title", "login.point2.body"],
              ["login.point3.title", "login.point3.body"],
            ] as const
          ).map(([title, body]) => (
            <li key={title} className="max-w-md">
              <p className="text-sm font-medium text-ink">{t(title)}</p>
              <p className="mt-0.5 text-xs leading-relaxed text-faint">{t(body)}</p>
            </li>
          ))}
        </ul>

        {/* The constraint that defines the product, stated on the way in
            rather than in a footnote after someone has formed an expectation. */}
        <div className="relative max-w-md rounded-lg border border-line bg-surface/70 p-4 backdrop-blur">
          <p className="text-sm font-medium text-ink">{t("disclaimer.title")}</p>
          <p className="mt-1 text-xs leading-relaxed text-faint">
            {t("login.constraint")}
          </p>
        </div>
      </aside>

      <div className="relative flex min-h-full items-center justify-center px-4 py-12">
        <div className="absolute right-4 top-4">
          {/* The only way to change language before signing in. Without it, a
              reader whose browser reports English meets an English login page
              for an Indonesian product and has nowhere to say otherwise. */}
          <LocaleSwitch />
        </div>

        <div className="w-full max-w-sm">
          <div className="mb-8 text-center lg:hidden">
            <h1 className="text-lg font-semibold text-ink">{t("app.name")}</h1>
            <p className="mt-1 text-xs text-faint">{t("app.tagline")}</p>
          </div>

          <div className="mb-6 hidden lg:block">
            <h2 className="text-lg font-semibold text-ink">
              {t(mode === "signIn" ? "login.welcomeBack" : "login.createAccount")}
            </h2>
            <p className="mt-1 text-xs text-faint">
              {t(mode === "signIn" ? "login.welcomeBackHint" : "login.createAccountHint")}
            </p>
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
    </div>
  );
}

/**
 * The language switch, before there is a session to attach a preference to.
 *
 * Same shape as the one in the application header, so it needs no explaining
 * the second time someone meets it.
 */
function LocaleSwitch() {
  const { locale, setLocale, t } = useI18n();
  return (
    <div
      role="group"
      aria-label={t("nav.language")}
      className="flex overflow-hidden rounded-md border border-line"
    >
      {(["id", "en"] as const).map((option) => (
        <button
          key={option}
          type="button"
          onClick={() => setLocale(option)}
          aria-pressed={locale === option}
          className={`px-2 py-1 text-xs uppercase transition-colors ${
            locale === option ? "bg-hover text-ink" : "text-faint hover:text-muted"
          }`}
        >
          {option}
        </button>
      ))}
    </div>
  );
}
