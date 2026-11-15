import { useEffect, useRef } from "react";
import { matchPath, NavLink, useLocation } from "react-router-dom";
import { useI18n } from "@/i18n/context";
import { useNavigationGroups } from "@/components/navigation";
import { useCollapsedGroups } from "@/components/useCollapsedGroups";

/**
 * The primary navigation, rendered.
 *
 * A flat row of seven links said nothing about how the product is organised:
 * "Picks" and "Chat" are both research, "Portfolio" and "Journal" are both
 * records of what you actually did, and Admin is a different job entirely.
 *
 * Each group folds. That was once declined ("four groups, a dozen links, a
 * disclosure costs a click and saves nothing"), and it stopped being true when the
 * Trading group arrived with seven links of its own: a reader who never trades
 * should not scroll past them, and one who only trades should not scroll past
 * research. The choice is remembered, and the group holding the current page opens
 * itself when you arrive there, so "where am I" is never hidden by a fold.
 */
export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const { t } = useI18n();
  const groups = useNavigationGroups();
  const { pathname } = useLocation();
  const { collapsed, toggle, expand } = useCollapsedGroups();

  const holdsCurrentPage = (group: (typeof groups)[number]) =>
    group.items.some((item) => matchPath({ path: item.to, end: item.end ?? false }, pathname));

  // Opens the group of the page you arrive on, once per navigation. Keyed on the path
  // rather than on the groups array, which is rebuilt on every render and would reopen
  // a group the reader had just folded.
  const openedFor = useRef<string | null>(null);
  useEffect(() => {
    if (openedFor.current === pathname) return;
    openedFor.current = pathname;
    const current = groups.find((g) =>
      g.items.some((item) => matchPath({ path: item.to, end: item.end ?? false }, pathname)),
    );
    if (current) expand(current.label);
  }, [pathname, groups, expand]);

  return (
    <nav aria-label={t("app.shortName")} className="flex flex-col gap-1 py-4">
      {groups.map((group) => {
        const open = !(collapsed[group.label] ?? false);
        const here = holdsCurrentPage(group);
        const listId = `nav-group-${group.label.replaceAll(".", "-")}`;
        return (
          <div key={group.label}>
            <button
              type="button"
              aria-expanded={open}
              aria-controls={listId}
              onClick={() => toggle(group.label)}
              className={`flex min-h-9 w-full cursor-pointer items-center justify-between rounded-md px-3 py-2 text-[0.65rem] font-medium uppercase tracking-wider transition-colors hover:bg-hover/60 hover:text-muted focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-rise ${
                here ? "text-muted" : "text-faint"
              }`}
            >
              <span>{t(group.label)}</span>
              {/* Drawn, not imported, like the menu glyph in the shell. It turns with the
                  state and carries no meaning of its own: aria-expanded says it. */}
              <svg
                width="10"
                height="10"
                viewBox="0 0 10 10"
                aria-hidden
                className={`shrink-0 transition-transform motion-reduce:transition-none ${
                  open ? "rotate-90" : ""
                }`}
              >
                <path
                  d="M3 1.5 6.5 5 3 8.5"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
            {/* `hidden` rather than unmounting: the links leave the tab order and the
                accessibility tree while folded, and come back without a re-render cost. */}
            <ul id={listId} hidden={!open} className="mb-3 space-y-0.5">
              {group.items.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.end}
                    onClick={onNavigate}
                    className={({ isActive }) =>
                      `block rounded-md px-3 py-1.5 text-sm transition-colors ${
                        isActive
                          ? "bg-hover font-medium text-ink"
                          : "text-muted hover:bg-hover/60 hover:text-ink"
                      }`
                    }
                  >
                    {t(item.label)}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}

/**
 * The same navigation as a drawer, for viewports too narrow for a column.
 *
 * Closed on navigation, because a drawer that stays open over the page you
 * just asked for is a drawer you have to dismiss twice.
 */
export function SidebarDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const location = useLocation();

  // The path this drawer was last closed for. Compared rather than relying on
  // the effect's dependency list, and that is the whole fix: `onClose` is an
  // inline arrow in the shell, so it has a new identity on every render, so an
  // effect depending on it runs on every render. Opening the drawer set state,
  // the shell re-rendered, the effect fired, and the drawer closed itself
  // before it could paint - the menu simply never appeared on a narrow screen.
  //
  // Dropping `onClose` from the dependency list would silence the lint rule and
  // leave a stale closure; comparing the path is correct however the callback
  // is declared.
  const closedFor = useRef(location.pathname);

  useEffect(() => {
    if (closedFor.current === location.pathname) return;
    closedFor.current = location.pathname;
    // Any navigation closes it, including one from a link inside the page
    // rather than from the drawer.
    onClose();
  }, [location.pathname, onClose]);

  useEffect(() => {
    if (!open) return;
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-30 lg:hidden">
      <button
        aria-hidden
        tabIndex={-1}
        onClick={onClose}
        className="absolute inset-0 bg-black/50"
      />
      <div className="absolute inset-y-0 left-0 w-64 overflow-y-auto border-r border-line bg-surface px-2 shadow-xl">
        <SidebarNav onNavigate={onClose} />
      </div>
    </div>
  );
}
