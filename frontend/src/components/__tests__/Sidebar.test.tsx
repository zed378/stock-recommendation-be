import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthContext, type Auth } from "@/auth/context";
import { SidebarNav } from "@/components/Sidebar";
import { readCollapsed } from "@/components/useCollapsedGroups";
import { I18nContext, type I18n } from "@/i18n/context";
import { locales } from "@/i18n/messages";

const KEY = "aidss.nav.collapsed";

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const i18n: I18n = {
  locale: "en",
  setLocale: () => {},
  t: (key) => locales.en[key] ?? key,
  n: (v) => String(v ?? "-"),
  money: (v) => String(v ?? "-"),
  pct: (v) => String(v ?? "-"),
  date: (v) => String(v ?? "-"),
  dateTime: (v) => String(v ?? "-"),
};

function renderNav(path = "/watchlist", role: "trader" | "viewer" = "trader") {
  const auth = {
    user: { id: "u", email: "o@example.com", full_name: "O", role },
    loading: false,
    signIn: async () => {},
    signUp: async () => {},
    signOut: () => {},
    expiredNotice: false,
    dismissExpiredNotice: () => {},
  } as unknown as Auth;
  return render(
    <I18nContext.Provider value={i18n}>
      <AuthContext.Provider value={auth}>
        <MemoryRouter initialEntries={[path]}>
          <SidebarNav />
        </MemoryRouter>
      </AuthContext.Provider>
    </I18nContext.Provider>,
  );
}

const header = (name: RegExp | string) => screen.getByRole("button", { name });

describe("collapsible sidebar groups", () => {
  it("starts with every group open and each header says so", () => {
    renderNav();
    const headers = screen.getAllByRole("button");
    expect(headers.length).toBeGreaterThanOrEqual(4);
    for (const h of headers) expect(h).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Watchlist" })).toBeVisible();
  });

  it("folds a group, hides its links from view and the accessibility tree, and reports it", () => {
    renderNav();
    fireEvent.click(header(/trading/i));
    expect(header(/trading/i)).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "Approvals" })).not.toBeInTheDocument();
    // The other groups are untouched.
    expect(screen.getByRole("link", { name: "Watchlist" })).toBeVisible();
  });

  it("unfolds it again with the same control", () => {
    renderNav();
    fireEvent.click(header(/trading/i));
    fireEvent.click(header(/trading/i));
    expect(header(/trading/i)).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Approvals" })).toBeVisible();
  });

  it("is operable by keyboard: the header is a real button reachable by Tab", () => {
    renderNav();
    const h = header(/trading/i);
    expect(h.tagName).toBe("BUTTON");
    expect(h).toHaveAttribute("type", "button");
    h.focus();
    expect(h).toHaveFocus();
    expect(h).toHaveAttribute("aria-controls");
    expect(document.getElementById(h.getAttribute("aria-controls")!)).toBeInTheDocument();
  });

  it("remembers the choice for the next visit", () => {
    const first = renderNav();
    fireEvent.click(header(/trading/i));
    expect(JSON.parse(window.localStorage.getItem(KEY) ?? "{}")).toMatchObject({
      "nav.group.trading": true,
    });
    first.unmount();
    renderNav("/watchlist");
    expect(header(/trading/i)).toHaveAttribute("aria-expanded", "false");
  });

  it("opens the group that holds the page you arrive on, even if it was folded", () => {
    window.localStorage.setItem(KEY, JSON.stringify({ "nav.group.trading": true }));
    renderNav("/trader/limits");
    expect(header(/trading/i)).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Risk limits" })).toBeVisible();
  });

  it("does not reopen a group the reader folds after arriving", () => {
    renderNav("/trader/limits");
    fireEvent.click(header(/trading/i));
    act(() => {});
    expect(header(/trading/i)).toHaveAttribute("aria-expanded", "false");
  });

  it("still works when browser storage is blocked, in both directions", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    renderNav();
    fireEvent.click(header(/trading/i));
    expect(header(/trading/i)).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(header(/trading/i));
    expect(header(/trading/i)).toHaveAttribute("aria-expanded", "true");
  });

  it("ignores a stored value it cannot understand and starts open", () => {
    window.localStorage.setItem(KEY, "{not json");
    expect(readCollapsed()).toEqual({});
    window.localStorage.setItem(KEY, JSON.stringify({ "nav.group.trading": "yes", ok: true }));
    expect(readCollapsed()).toEqual({ ok: true });
    renderNav();
    expect(header(/trading/i)).toHaveAttribute("aria-expanded", "true");
  });

  it("shows no Trading group to a role that cannot use it, so nothing about it can be folded", () => {
    renderNav("/watchlist", "viewer");
    expect(screen.queryByRole("button", { name: /trading/i })).not.toBeInTheDocument();
  });
});
