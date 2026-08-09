import { useEffect, useRef } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useI18n } from "@/i18n/context";
import { useNavigationGroups } from "@/components/navigation";

/**
 * The primary navigation, rendered.
 *
 * A flat row of seven links said nothing about how the product is organised:
 * "Picks" and "Chat" are both research, "Portfolio" and "Journal" are both
 * records of what you actually did, and Admin is a different job entirely.
 *
 * Groups are headings rather than collapsible drawers. There are four of them
 * with a dozen links in total; hiding any of that behind a disclosure costs a
 * click and saves nothing worth the click.
 */
export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const { t } = useI18n();
  const groups = useNavigationGroups();

  return (
    <nav className="flex flex-col gap-5 py-4">
      {groups.map((group) => (
        <div key={group.label}>
          <p className="px-3 pb-1.5 text-[0.65rem] font-medium uppercase tracking-wider text-faint">
            {t(group.label)}
          </p>
          <ul className="space-y-0.5">
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
      ))}
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
