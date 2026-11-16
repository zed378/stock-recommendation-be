import { useState } from "react";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthContext, type Auth } from "@/auth/context";
import { I18nContext, type I18n } from "@/i18n/context";
import { locales, type Locale, type MessageKey } from "@/i18n/messages";
import { Landing } from "@/pages/Landing";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function Harness({ initialLocale = "id", signedIn = false }: { initialLocale?: Locale; signedIn?: boolean }) {
  const [locale, setLocale] = useState<Locale>(initialLocale);
  const dict = locales[locale];
  const i18n: I18n = {
    locale,
    setLocale,
    t: (key: MessageKey, values?: Record<string, string | number>) => {
      let msg: string = dict[key] ?? key;
      if (values) for (const [k, v] of Object.entries(values)) msg = msg.replaceAll(`{${k}}`, String(v));
      return msg;
    },
    n: (v) => String(v ?? "-"),
    money: (v) => String(v ?? "-"),
    pct: (v) => String(v ?? "-"),
    date: (v) => String(v ?? "-"),
    dateTime: (v) => String(v ?? "-"),
  };
  const auth = {
    user: signedIn ? { id: "u", email: "o@example.com", full_name: "O", role: "trader" } : null,
    loading: false,
    signIn: async () => {},
    signUp: async () => {},
    signOut: () => {},
    expiredNotice: false,
    dismissExpiredNotice: () => {},
  } as unknown as Auth;
  return (
    <MemoryRouter initialEntries={["/"]}>
      <I18nContext.Provider value={i18n}>
        <AuthContext.Provider value={auth}>
          <Landing />
        </AuthContext.Provider>
      </I18nContext.Provider>
    </MemoryRouter>
  );
}

describe("landing page content is honest", () => {
  it("has no em dash, in either language (R-02)", () => {
    for (const locale of ["id", "en"] as const) {
      const { container, unmount } = render(<Harness initialLocale={locale} />);
      expect(container.textContent).not.toContain("—");
      unmount();
    }
  });

  // R-17 and R-38: no price, no confidence, no count of users. The only figures allowed are the ones that
  // are facts about the product (13 indicators; the 1, 7, 14 and 30 day horizons of the stock picks) and the
  // year in the copyright line.
  it("contains no figure other than the ones that are facts about the product", () => {
    for (const locale of ["id", "en"] as const) {
      const { container, unmount } = render(<Harness initialLocale={locale} />);
      const text = container.textContent ?? "";
      // "01" to "05" are the zero-padded list markers of the workspaces; they are compared as numbers.
      const figures = new Set((text.match(/\d+/g) ?? []).map((f) => (f.length === 4 ? f : String(Number(f)))));
      const allowed = new Set(["13", "1", "7", "14", "30", String(new Date().getFullYear())]);
      // Layer numbers 1 to 5 and the part indices 1 to 6 are list markers, not data.
      for (const marker of ["2", "3", "4", "5", "6"]) allowed.add(marker);
      for (const figure of figures) expect(allowed.has(figure), `unexpected figure ${figure}`).toBe(true);
      expect(text).not.toMatch(/Rp|IDR\s?\d|%|BBCA|BMRI|TLKM/);
      unmount();
    }
  });

  it("says the Trader has never been connected to an exchange and offers no order path", () => {
    const { container, unmount } = render(<Harness initialLocale="id" />);
    expect(container.textContent).toContain("belum pernah terhubung ke bursa sungguhan");
    expect(container.textContent).toContain("Tidak ada pesanan dan tidak ada broker");
    unmount();
    const en = render(<Harness initialLocale="en" />);
    expect(en.container.textContent).toContain("never been connected to a real one");
    expect(en.container.textContent).toContain("No orders and no broker");
  });

  it("uses no raster image: the stack is drawn, and only the logo is an <img>", () => {
    const { container } = render(<Harness />);
    const images = Array.from(container.querySelectorAll("img"));
    expect(images.length).toBe(2);
    for (const img of images) {
      expect(img.getAttribute("src")).toBe("/logo-symbol.svg");
      expect(img.getAttribute("width")).toBeTruthy();
      expect(img.getAttribute("height")).toBeTruthy();
      expect(img.getAttribute("alt")).toBe("");
    }
  });
});

describe("landing page behaviour", () => {
  it("sends a visitor to sign in, and a signed-in user to the workspace", () => {
    const out = render(<Harness />);
    const signIn = screen.getAllByRole("link", { name: "Masuk ke ruang kerja" });
    expect(signIn.length).toBeGreaterThan(1);
    for (const link of signIn) expect(link.getAttribute("href")).toBe("/login");
    out.unmount();
    render(<Harness signedIn />);
    for (const link of screen.getAllByRole("link", { name: "Buka ruang kerja" })) {
      expect(link.getAttribute("href")).toBe("/watchlist");
    }
  });

  it("only links to sections that exist, and every workspace link is a real route", () => {
    const { container } = render(<Harness />);
    const hrefs = Array.from(container.querySelectorAll("a[href]")).map((a) => a.getAttribute("href")!);
    for (const href of hrefs.filter((h) => h.startsWith("#") && h.length > 1)) {
      expect(container.querySelector(href), `${href} has no target`).not.toBeNull();
    }
    for (const route of ["/login", "/watchlist", "/picks", "/portfolio", "/monitoring", "/trader"]) {
      expect(hrefs).toContain(route);
    }
    expect(container.querySelectorAll("h1").length).toBe(1);
    expect(container.querySelector("main#main-content")).not.toBeNull();
  });

  it("switches language", () => {
    render(<Harness initialLocale="id" />);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("bukti sebaliknya");
    fireEvent.click(screen.getByRole("button", { name: "en" }));
    expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("the evidence against them");
  });

  it("opens the phone menu, and Escape closes it", () => {
    render(<Harness />);
    const menu = screen.getByRole("button", { name: "Menu" });
    expect(menu.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(menu);
    expect(screen.getByRole("button", { name: "Tutup menu" }).getAttribute("aria-expanded")).toBe("true");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("button", { name: "Menu" }).getAttribute("aria-expanded")).toBe("false");
  });

  it("lights the matching part of the card when a part is pointed at or focused", () => {
    const { container } = render(<Harness />);
    const lit = () => container.querySelectorAll('.lp-field[data-active="true"]').length;
    expect(lit()).toBe(0);
    const confidence = within(container.querySelector("#kartu ol")!).getByRole("button", { name: /Keyakinan/ });
    fireEvent.focus(confidence);
    expect(lit()).toBe(1);
    fireEvent.blur(confidence);
    expect(lit()).toBe(0);
    // The three lists of factors are one part and light together.
    fireEvent.mouseEnter(within(container.querySelector("#kartu ol")!).getByRole("button", { name: /Tiga daftar faktor/ }));
    expect(lit()).toBe(3);
  });
});

describe("the five layers beside the stack", () => {
  const callbacks: Array<(entries: Array<{ isIntersecting: boolean; target: Element }>) => void> = [];

  beforeEach(() => {
    callbacks.length = 0;
    class FakeObserver {
      constructor(cb: (entries: Array<{ isIntersecting: boolean; target: Element }>) => void) {
        callbacks.push(cb);
      }
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    vi.stubGlobal("IntersectionObserver", FakeObserver);
  });

  it("brings forward the plane of the step that reaches the middle of the screen", () => {
    const { container } = render(<Harness />);
    const stacks = () => Array.from(container.querySelectorAll(".lp-stack[data-active]")).map((e) => e.getAttribute("data-active"));
    expect(stacks()).toContain("0");
    const step = container.querySelector('[data-step="3"]')!;
    act(() => {
      for (const cb of callbacks) cb([{ isIntersecting: true, target: step }]);
    });
    expect(stacks()).toContain("3");
    expect(stacks()).not.toContain("0");
  });
});
