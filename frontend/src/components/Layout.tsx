import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "@/auth/context";
import { useI18n } from "@/i18n/context";
import type { Locale } from "@/i18n/context";

/**
 * The application shell.
 *
 * The disclaimer sits in the footer of every page rather than behind a dialog
 * that gets dismissed once and never seen again. Section 13 requires it to be
 * present on output, and a modal accepted six months ago is not present.
 */
export function Layout() {
  const { t, locale, setLocale } = useI18n();
  const { user, signOut } = useAuth();

  const links = [
    { to: "/watchlist", label: t("nav.watchlist") },
    { to: "/portfolio", label: t("nav.portfolio") },
    { to: "/journal", label: t("nav.journal") },
    { to: "/chat", label: t("nav.chat") },
    // Shown only to admins. Not a security measure - the route and the API
    // both stand on their own - just an absence of a link to somewhere the
    // reader cannot use.
    ...(user?.role === "admin" ? [{ to: "/admin", label: t("nav.admin") }] : []),
  ];

  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-20 border-b border-line bg-surface/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-6 px-4 py-3">
          <NavLink to="/watchlist" className="flex items-baseline gap-2">
            <span className="text-sm font-semibold tracking-tight text-ink">
              {t("app.shortName")}
            </span>
            <span className="hidden text-xs text-faint sm:inline">{t("app.tagline")}</span>
          </NavLink>

          <nav className="flex items-center gap-1">
            {links.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                className={({ isActive }) =>
                  `rounded-md px-3 py-1.5 text-sm transition-colors ${
                    isActive
                      ? "bg-hover text-ink"
                      : "text-muted hover:bg-hover/60 hover:text-ink"
                  }`
                }
              >
                {link.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-3">
            <LocaleSwitch locale={locale} onChange={setLocale} label={t("nav.language")} />
            {user && (
              <>
                <span className="hidden text-xs text-faint md:inline">{user.email}</span>
                <button
                  onClick={signOut}
                  className="rounded-md px-2.5 py-1 text-xs text-muted transition-colors hover:bg-hover hover:text-ink"
                >
                  {t("nav.signOut")}
                </button>
              </>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">
        <Outlet />
      </main>

      <footer className="border-t border-line px-4 py-4">
        <p className="mx-auto max-w-7xl text-xs leading-relaxed text-faint">
          <span className="font-medium text-muted">{t("disclaimer.title")}. </span>
          {t("disclaimer.long")}
        </p>
      </footer>
    </div>
  );
}

function LocaleSwitch({
  locale,
  onChange,
  label,
}: {
  locale: Locale;
  onChange: (next: Locale) => void;
  label: string;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="flex overflow-hidden rounded-md border border-line"
    >
      {(["id", "en"] as const).map((option) => (
        <button
          key={option}
          onClick={() => onChange(option)}
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
