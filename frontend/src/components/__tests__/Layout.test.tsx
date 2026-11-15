import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthContext, type Auth } from "@/auth/context";
import { Layout } from "@/components/Layout";
import { I18nContext, type I18n } from "@/i18n/context";
import { locales } from "@/i18n/messages";

// The shell opens a socket, polls notifications, and loads the Trader's state. None of that is
// what is under test here.
vi.mock("@/realtime/useEvents", () => ({ useEvents: () => {} }));
vi.mock("@/components/Notifications", () => ({ NotificationBell: () => null }));
vi.mock("@/trader/StateBar", () => ({ StateBar: () => null }));

const KEY = "aidss.nav.sidebar";

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

function renderShell() {
  const auth = {
    user: { id: "u", email: "o@example.com", full_name: "O", role: "trader" },
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
        <MemoryRouter initialEntries={["/watchlist"]}>
          <Routes>
            <Route element={<Layout />}>
              <Route path="*" element={<p>page</p>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </AuthContext.Provider>
    </I18nContext.Provider>,
  );
}

const sidebar = (c: HTMLElement) => c.querySelector("#app-sidebar");
const toggle = (c: HTMLElement) => c.querySelector<HTMLButtonElement>('button[aria-controls="app-sidebar"]');

describe("collapsible desktop sidebar", () => {
  it("is shown by default, with a labelled control that says it is open", () => {
    const { container } = renderShell();
    expect(sidebar(container)).toBeInTheDocument();
    const hide = screen.getByRole("button", { name: "Hide menu" });
    expect(hide).toHaveAttribute("aria-expanded", "true");
    expect(hide).toHaveAttribute("aria-controls", "app-sidebar");
  });

  it("puts the column away and offers a control to bring it back", () => {
    const { container } = renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Hide menu" }));
    expect(sidebar(container)).not.toBeInTheDocument();
    const show = toggle(container);
    expect(show).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(show!);
    expect(sidebar(container)).toBeInTheDocument();
  });

  it("keeps the page, and the navigation links inside it, intact either way", () => {
    renderShell();
    expect(screen.getByText("page")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Watchlist" }).length).toBeGreaterThan(0);
  });

  it("remembers that it was put away", () => {
    const first = renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Hide menu" }));
    expect(window.localStorage.getItem(KEY)).toBe("hidden");
    first.unmount();
    const second = renderShell();
    expect(sidebar(second.container)).not.toBeInTheDocument();
  });

  it("still opens and closes when browser storage is blocked", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const { container } = renderShell();
    expect(sidebar(container)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hide menu" }));
    expect(sidebar(container)).not.toBeInTheDocument();
    fireEvent.click(toggle(container)!);
    expect(sidebar(container)).toBeInTheDocument();
  });

  it("folds the groups inside the open sidebar independently of the sidebar itself", () => {
    renderShell();
    const trading = screen.getByRole("button", { name: /trading/i });
    fireEvent.click(trading);
    expect(trading).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: "Hide menu" })).toHaveAttribute("aria-expanded", "true");
  });
});

// 44px is the touch-target minimum. The header's controls are written by hand (not the shared Button), so
// each one carries the phone height itself. jsdom has no layout: this pins the classes; the sizes were
// measured in a browser at 375, 360 and 320px.
describe("header tap targets on phones", () => {
  it("gives the menu, language, and sign-out controls a 44px minimum below sm", () => {
    renderShell();
    const menu = screen.getAllByRole("button", { name: "Open menu" })[0];
    expect(menu).toHaveClass("max-sm:size-11", "max-sm:shrink-0");
    for (const name of ["id", "en"]) {
      expect(screen.getByRole("button", { name })).toHaveClass("max-sm:min-h-11", "max-sm:min-w-11");
    }
    const signOut = screen.getByRole("button", { name: "Sign out" });
    expect(signOut).toHaveClass("max-sm:min-h-11", "max-sm:whitespace-nowrap");
  });

  it("hides the brand text on very narrow phones so the larger controls still fit", () => {
    const { container } = renderShell();
    const brand = container.querySelector<HTMLAnchorElement>("header a[href='/']");
    expect(brand).toHaveClass("max-sm:min-h-11", "max-[23rem]:hidden");
  });
});
