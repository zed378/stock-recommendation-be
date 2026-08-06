import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "@/auth/context";
import { useI18n } from "@/i18n/context";
import type { Locale } from "@/i18n/context";
import { NotificationBell } from "@/components/Notifications";
import { SidebarDrawer, SidebarNav, useDrawer } from "@/components/Sidebar";
import { useEvents } from "@/realtime/useEvents";

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

  // One socket for the session, opened here because this shell wraps every
  // authenticated screen and unmounts on sign-out. Events invalidate the
  // cached queries they concern; the slower polls elsewhere stay as the floor
  // under it, for the case where a proxy refuses the upgrade.
  useEvents(Boolean(user));

  const drawer = useDrawer();

  return (
    <div className="min-h-full lg:flex">
      {/* A column on wide screens, a drawer below. Fixed rather than scrolling
          with the page: navigation that scrolls away is navigation you have to
          scroll back for. */}
      <aside className="hidden w-56 shrink-0 border-r border-line lg:block">
        <div className="sticky top-0 flex h-screen flex-col overflow-y-auto px-2">
          <NavLink
            to="/watchlist"
            className="flex items-baseline gap-2 px-3 pb-1 pt-4 text-sm font-semibold tracking-tight text-ink"
          >
            {t("app.shortName")}
          </NavLink>
          <SidebarNav />
        </div>
      </aside>

      <SidebarDrawer open={drawer.open} onClose={() => drawer.setOpen(false)} />

      <div className="flex min-h-screen w-full min-w-0 flex-col">
        <header className="sticky top-0 z-20 border-b border-line bg-surface/95 backdrop-blur">
          <div className="flex items-center gap-3 px-4 py-3">
            <button
              onClick={() => drawer.setOpen(true)}
              aria-label={t("nav.openMenu")}
              className="rounded-md p-1.5 text-muted transition-colors hover:bg-hover hover:text-ink lg:hidden"
            >
              {/* Drawn rather than imported: one glyph is not worth an icon
                  dependency, and an emoji would inherit the platform's idea of
                  what a menu looks like. */}
              <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
                <path
                  d="M2 4.5h14M2 9h14M2 13.5h14"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                />
              </svg>
            </button>

            <NavLink
              to="/watchlist"
              className="text-sm font-semibold tracking-tight text-ink lg:hidden"
            >
              {t("app.shortName")}
            </NavLink>

            <div className="ml-auto flex items-center gap-3">
              {user && <NotificationBell />}
              <LocaleSwitch
                locale={locale}
                onChange={setLocale}
                label={t("nav.language")}
              />
              {user && (
                <>
                  <span className="hidden text-xs text-faint md:inline">
                    {user.email}
                  </span>
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

        <main className="w-full flex-1 px-4 py-6">
          <div className="mx-auto max-w-6xl">
            <Outlet />
          </div>
        </main>

        <footer className="border-t border-line px-4 py-4">
          <p className="mx-auto max-w-6xl text-xs leading-relaxed text-faint">
            <span className="font-medium text-muted">
              {t("disclaimer.title")}.{" "}
            </span>
            {t("disclaimer.long")}
          </p>
        </footer>
      </div>
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
            locale === option
              ? "bg-hover text-ink"
              : "text-faint hover:text-muted"
          }`}
        >
          {option}
        </button>
      ))}
    </div>
  );
}
