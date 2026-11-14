import type { MessageKey } from "@/i18n/context";
import { useAuth } from "@/auth/context";

/**
 * What the primary navigation contains.
 *
 * Kept apart from the components that render it, and not as a matter of taste:
 * a module exporting both a hook and a component cannot be hot-reloaded, and
 * this project has already lost an afternoon to exactly that - the i18n
 * context did it, the app white-screened on any edit, and the warning had been
 * dismissed as "only costs HMR state".
 *
 * The grouping is the point of the change. A flat row of seven links said
 * nothing about how the product is organised: "Picks" and "Chat" are both
 * research, "Portfolio" and "Journal" are both records of what you actually
 * did, and Admin is a different job entirely. It is also what makes room for
 * the admin sections to be reachable at all - as tabs they were somewhere you
 * could only arrive at by clicking through.
 */

type Item = { to: string; label: MessageKey; end?: boolean };
type Group = { label: MessageKey; items: Item[] };

const RESEARCH: Group = {
  label: "nav.group.research",
  items: [
    { to: "/watchlist", label: "nav.watchlist" },
    { to: "/picks", label: "nav.picks" },
    // Beside the built-in screener rather than under the account: it
    // answers the same question, with conditions the reader chose.
    { to: "/screens", label: "nav.screens" },
    // Two entries because they answer differently shaped questions. Ask AI
    // is anchored on an issuer you have already chosen; this one is for
    // the questions you ask before you have one.
    { to: "/market-chat", label: "nav.marketChat" },
    { to: "/chat", label: "nav.chat" },
  ],
};

const POSITIONS: Group = {
  label: "nav.group.positions",
  items: [
    { to: "/portfolio", label: "nav.portfolio" },
    { to: "/journal", label: "nav.journal" },
  ],
};

const WATCHING: Group = {
  label: "nav.group.watching",
  items: [
    { to: "/monitoring", label: "nav.monitoring" },
    // The calendar sits with monitoring rather than with research: both are
    // about things arriving on their own schedule rather than questions the
    // reader went looking for.
    { to: "/agenda", label: "nav.agenda" },
  ],
};

/**
 * The Trader's operator surface. Offered only to the roles that operate or
 * oversee trading; the Trader API is what actually enforces it.
 */
const TRADING: Group = {
  label: "nav.group.trading",
  items: [
    { to: "/trader", label: "nav.trader", end: true },
    { to: "/trader/approvals", label: "nav.traderApprovals" },
    { to: "/trader/strategies", label: "nav.traderStrategies" },
  ],
};

/**
 * Settings that belong to the reader rather than to the platform.
 *
 * Kept out of Administration, which is a different job: an investor sets their
 * own horizon and decides who sees their watchlist, and neither needs the
 * admin role.
 */
const YOU: Group = {
  label: "nav.group.you",
  items: [
    { to: "/profile", label: "nav.profile" },
    { to: "/shared", label: "nav.shared" },
  ],
};

/**
 * Admin sections as routes rather than tab state.
 *
 * They were tabs, which meant no section had an address: an admin could not
 * bookmark the news sources, link a colleague to the audit log, or reload
 * without landing back on the overview.
 */
const ADMINISTRATION: Group = {
  label: "nav.group.administration",
  items: [
    { to: "/admin", label: "admin.tab.overview", end: true },
    { to: "/admin/users", label: "admin.tab.users" },
    { to: "/admin/news", label: "admin.tab.news" },
    { to: "/admin/issuers", label: "admin.tab.issuers" },
    { to: "/admin/queue", label: "admin.tab.queue" },
    { to: "/admin/providers", label: "admin.tab.providers" },
    { to: "/admin/settings", label: "admin.tab.settings" },
    { to: "/admin/budget", label: "admin.tab.budget" },
    { to: "/admin/audit", label: "admin.tab.audit" },
  ],
};

export function useNavigationGroups(): Group[] {
  const { user } = useAuth();
  // Hidden rather than guarded. The route and the API each stand on their own;
  // this only avoids offering a link to somewhere the reader cannot use.
  const base = [RESEARCH, WATCHING, POSITIONS];
  if (user?.role === "trader" || user?.role === "admin") base.push(TRADING);
  base.push(YOU);
  if (user?.role === "admin") base.push(ADMINISTRATION);
  return base;
}
