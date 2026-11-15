import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { AuthContext, type Auth } from "@/auth/context";
import { I18nContext, type I18n } from "@/i18n/context";
import { locales, type Locale, type MessageKey } from "@/i18n/messages";
import { Landing } from "@/pages/Landing";

afterEach(() => {
  cleanup();
});

function LandingHarness({ initialLocale = "id" }: { initialLocale?: Locale }) {
  const [locale, setLocale] = useState<Locale>(initialLocale);
  const dict = locales[locale];
  const i18n: I18n = {
    locale,
    setLocale,
    t: (key: MessageKey, values?: Record<string, string | number>) => {
      let msg: string = dict[key] ?? key;
      if (values) {
        for (const [k, v] of Object.entries(values)) {
          msg = msg.replaceAll(`{${k}}`, String(v));
        }
      }
      return msg;
    },
    n: (v) => String(v ?? "-"),
    money: (v) => String(v ?? "-"),
    pct: (v) => String(v ?? "-"),
    date: (v) => String(v ?? "-"),
    dateTime: (v) => String(v ?? "-"),
  };
  const auth: Auth = {
    user: null,
    loading: false,
    signIn: async () => {},
    signUp: async () => {},
    signOut: () => {},
    expiredNotice: false,
    dismissExpiredNotice: () => {},
  };

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

describe("Landing page luxury product revamp", () => {
  it("renders without em dashes in any landing copy (R-02) and sets explicit image attributes (R-40)", () => {
    const { container } = render(<LandingHarness initialLocale="id" />);
    expect(container.textContent).not.toContain("\u2014");

    const allImages = Array.from(container.querySelectorAll("img"));
    expect(allImages.length).toBe(5);
    for (const img of allImages) {
      expect(img.getAttribute("width")).toBeTruthy();
      expect(img.getAttribute("height")).toBeTruthy();
    }

    const editorialImages = Array.from(
      container.querySelectorAll<HTMLImageElement>('img[src^="/landing/"]'),
    );
    expect(editorialImages.length).toBe(3);

    const heroImg = editorialImages[0]!;
    expect(heroImg.getAttribute("src")).toBe("/landing/hero-jakarta-skyline.jpg");
    expect(heroImg.getAttribute("width")).toBe("1600");
    expect(heroImg.getAttribute("height")).toBe("2411");
    expect(heroImg.getAttribute("loading")).toBeNull();

    for (const belowFoldImg of editorialImages.slice(1)) {
      expect(belowFoldImg.getAttribute("loading")).toBe("lazy");
      expect(belowFoldImg.getAttribute("width")).toBe("1200");
      expect(belowFoldImg.getAttribute("height")).toBe("800");
    }
  });

  it("wires issuer specimen switcher, pause/play motion toggle, studio tabs, debate graph nodes, language switcher, and mobile menu (R-35)", () => {
    const { container } = render(<LandingHarness initialLocale="id" />);

    // 1. Issuer Specimen Switcher updates hero stage metrics and issuer name
    expect(screen.getAllByText(/Bank Central Asia Tbk/i).length).toBeGreaterThan(0);
    const tlkmBtn = screen.getByRole("button", { name: /TLKM\.JK/i });
    fireEvent.click(tlkmBtn);
    expect(tlkmBtn.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getAllByText(/Telkom Indonesia \(Persero\) Tbk/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/2,890/i).length).toBeGreaterThan(0);

    // 2. Pause / Play Animation button toggles data-motion-paused and aria-pressed (R-39)
    // Note: clicking TLKM.JK already paused auto-cycling so the user's chosen specimen stays pinned.
    const rootWrapper = container.querySelector("[data-motion-paused]")!;
    expect(rootWrapper.getAttribute("data-motion-paused")).toBe("true");
    const motionBtn = screen.getByRole("button", { name: /Putar Animasi/i });
    fireEvent.click(motionBtn);
    expect(rootWrapper.getAttribute("data-motion-paused")).toBe("false");
    expect(motionBtn.getAttribute("aria-pressed")).toBe("false");

    // 3. Interactive Product Studio tabs (click + ArrowRight keyboard navigation)
    const tab1 = screen.getByRole("tab", { name: /Kanvas Kronos & Level Harga/i });
    const tab2 = screen.getByRole("tab", { name: /Teater Debat Multi-Agen/i });
    const tab3 = screen.getByRole("tab", { name: /Memori Situasi & Kalibrasi/i });

    expect(tab1.getAttribute("aria-selected")).toBe("true");
    fireEvent.click(tab2);
    expect(tab2.getAttribute("aria-selected")).toBe("true");

    // 4. Debate Graph Node buttons update the active transcript card
    const bearNodeBtn = screen.getByRole("button", { name: /Bear Researcher/i });
    fireEvent.click(bearNodeBtn);
    expect(bearNodeBtn.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText(/Uji Tekanan & Valuasi/i)).toBeTruthy();

    // Keyboard navigation from tab2 -> tab3
    fireEvent.keyDown(tab2, { key: "ArrowRight" });
    expect(tab3.getAttribute("aria-selected")).toBe("true");
    expect(screen.getAllByText(/Bukti penyangkal wajib/i).length).toBeGreaterThan(0);

    // 5. Mobile navigation toggle and Escape key close
    const menuBtn = screen.getByRole("button", { name: "Menu" });
    expect(menuBtn.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(menuBtn);
    expect(menuBtn.getAttribute("aria-expanded")).toBe("true");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(menuBtn.getAttribute("aria-expanded")).toBe("false");

    // 6. Language switcher switches to English without em dashes
    const enBtns = screen.getAllByRole("button", { name: /^en$/i });
    fireEvent.click(enBtns[0]!);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toContain(
      "Investment decisions stress-tested",
    );
    expect(container.textContent).not.toContain("\u2014");
  });
});
