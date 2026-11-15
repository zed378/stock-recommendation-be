import { useCallback, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "@/auth/context";
import { useI18n } from "@/i18n/context";
import type { Locale } from "@/i18n/context";
import { NotificationBell } from "@/components/Notifications";
import { SidebarDrawer, SidebarNav } from "@/components/Sidebar";
import { useSidebarVisible } from "@/components/useSidebarVisible";
import { useEvents } from "@/realtime/useEvents";
import { StateBar } from "@/trader/StateBar";

/**
 * The application shell.
 *
 * The disclaimer sits in the footer of every page rather than behind a dialog
 * that gets dismissed once and never seen again. Section 26 requires it to be
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

  const [drawerOpen, setDrawerOpen] = useState(false);
  // The desktop column can be put away to give the page the whole width. The drawer on a narrow
  // screen is a separate thing and is unaffected.
  const sidebar = useSidebarVisible();
  // Stable identity. Not what fixed the drawer - it compares the path itself
  // now - but an inline arrow here was what made an effect depending on it run
  // on every render, and leaving that trap set for the next caller is worse
  // than the one line it costs to remove.
  const closeDrawer = useCallback(() => setDrawerOpen(false), []);

  return (
    <div className="min-h-full lg:flex">
      {/* A column on wide screens, a drawer below. Fixed rather than scrolling
          with the page: navigation that scrolls away is navigation you have to
          scroll back for. */}
      {sidebar.visible && (
        <aside
          id="app-sidebar"
          className="hidden w-56 shrink-0 border-r border-line lg:block"
        >
          <div className="sticky top-0 flex h-screen flex-col overflow-y-auto px-2">
            <div className="flex items-center justify-between pr-1">
              <NavLink
                to="/"
                className="flex items-center gap-2 px-3 pb-1 pt-4 text-sm font-semibold tracking-tight text-ink"
              >
                <img src="/logo-symbol.svg" alt="" className="h-5 w-5" />
                {t("app.shortName")}
              </NavLink>
              <button
                type="button"
                onClick={sidebar.hide}
                aria-label={t("nav.hideMenu")}
                aria-expanded
                aria-controls="app-sidebar"
                className="mt-3 cursor-pointer rounded-md p-1.5 text-faint transition-colors hover:bg-hover hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rise"
              >
                {/* Two chevrons pointing at the edge it folds into. */}
                <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden>
                  <path
                    d="M8.5 3.5 4 8l4.5 4.5M13 3.5 8.5 8l4.5 4.5"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
            </div>
            <SidebarNav />
          </div>
        </aside>
      )}

      <SidebarDrawer open={drawerOpen} onClose={closeDrawer} />

      <div className="flex min-h-screen w-full min-w-0 flex-col">
        <header className="sticky top-0 z-20 border-b border-line bg-surface/95 backdrop-blur">
          <div className="flex items-center gap-3 px-4 py-3 max-sm:gap-1 max-sm:py-1.5">
            <button
              onClick={() => setDrawerOpen(true)}
              aria-label={t("nav.openMenu")}
              className="rounded-md p-1.5 text-muted transition-colors hover:bg-hover hover:text-ink max-sm:inline-flex max-sm:size-11 max-sm:shrink-0 max-sm:items-center max-sm:justify-center lg:hidden"
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

            {/* Brings the desktop column back. Only present while it is put away. */}
            {!sidebar.visible && (
              <button
                type="button"
                onClick={sidebar.show}
                aria-label={t("nav.openMenu")}
                aria-expanded={false}
                aria-controls="app-sidebar"
                className="hidden cursor-pointer rounded-md p-1.5 text-muted transition-colors hover:bg-hover hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rise lg:inline-flex"
              >
                <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
                  <path
                    d="M2 4.5h14M2 9h14M2 13.5h14"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                  />
                </svg>
              </button>
            )}

            <NavLink
              to="/"
              className={`flex items-center gap-2 text-sm font-semibold tracking-tight text-ink max-sm:min-h-11 max-[23rem]:hidden ${
                sidebar.visible ? "lg:hidden" : ""
              }`}
            >
              <img src="/logo-symbol.svg" alt="" className="h-5 w-5" />
              {t("app.shortName")}
            </NavLink>

            <div className="ml-auto flex items-center gap-3 max-sm:gap-1">
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
                    className="rounded-md px-2.5 py-1 text-xs text-muted transition-colors hover:bg-hover hover:text-ink max-sm:min-h-11 max-sm:whitespace-nowrap"
                  >
                    {t("nav.signOut")}
                  </button>
                </>
              )}
            </div>
          </div>
          {/* Inside the sticky header, so the Trader's state and the HALT control
              stay on screen on every page and while scrolling. */}
          <StateBar />
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
          className={`px-2 py-1 text-xs uppercase transition-colors max-sm:min-h-11 max-sm:min-w-11 ${
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
