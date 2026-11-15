import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthContext, type Auth } from "@/auth/context";
import { ToastContext } from "@/components/toastContext";
import { I18nContext, type I18n } from "@/i18n/context";
import { locales, type Locale, type MessageKey } from "@/i18n/messages";
import { TraderCredentials } from "@/pages/TraderCredentials";
import { OriginBadge, PanelBody, TraderErrorNote } from "@/trader/components";
import { TraderError, traderApi } from "@/trader/client";
import { HaltButton, KillControls } from "@/trader/KillControls";
import { StateBar } from "@/trader/StateBar";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function makeI18n(locale: Locale = "en"): I18n {
  const dict = locales[locale];
  return {
    locale,
    setLocale: () => {},
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
}

function renderWithProviders(
  ui: ReactNode,
  {
    role = "trader",
    locale = "en",
  }: { role?: "trader" | "admin" | "investor" | "viewer" | null; locale?: Locale } = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const auth: Auth = {
    user: role
      ? {
          id: "u-1",
          email: "owner@example.com",
          full_name: "Owner",
          role,
          mfa_enabled: false,
        }
      : null,
    loading: false,
    signIn: async () => {},
    signUp: async () => {},
    signOut: () => {},
    expiredNotice: false,
    dismissExpiredNotice: () => {},
  };
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <AuthContext.Provider value={auth}>
          <I18nContext.Provider value={makeI18n(locale)}>
            <ToastContext.Provider value={{ show: () => {} }}>{ui}</ToastContext.Provider>
          </I18nContext.Provider>
        </AuthContext.Provider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("Trader UI key components and safety invariants", () => {
  it("keeps Indonesian and English trader.* message keys in sync and free of em-dashes", () => {
    const idKeys = Object.keys(locales.id).filter((k) => k.startsWith("trader.") || k.startsWith("nav.trader"));
    const enKeys = Object.keys(locales.en).filter((k) => k.startsWith("trader.") || k.startsWith("nav.trader"));
    expect(idKeys.sort()).toEqual(enKeys.sort());

    for (const key of idKeys as MessageKey[]) {
      expect(locales.id[key], `id:${key} contains em-dash`).not.toContain("—");
      expect(locales.en[key], `en:${key} contains em-dash`).not.toContain("—");
    }
  });

  it("KillControls FLATTEN dialog requires typing FLATTEN and completing step-up before executing", async () => {
    renderWithProviders(<KillControls state="RUNNING" openOrderCount={2} />);

    fireEvent.click(screen.getByRole("button", { name: /^FLATTEN/ }));
    const dialog = screen.getByRole("dialog", { name: "FLATTEN" });
    expect(dialog).toBeTruthy();

    const runBtn = screen.getByRole("button", { name: "Run FLATTEN" }) as HTMLButtonElement;
    expect(runBtn.disabled).toBe(true);

    const wordInput = screen.getByRole("textbox") as HTMLInputElement;
    fireEvent.change(wordInput, { target: { value: "flatten" } });
    expect(runBtn.disabled).toBe(true);

    fireEvent.change(wordInput, { target: { value: "FLATTEN" } });
    expect(runBtn.disabled).toBe(false);

    // Clicking Run FLATTEN opens the password step-up dialog rather than calling /kill directly
    fireEvent.click(runBtn);
    expect(screen.getByRole("dialog", { name: "Confirm your identity again" })).toBeTruthy();

    // Pressing Escape closes the dialog cleanly
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Confirm your identity again" })).toBeNull();
    });
  });

  it("TraderCredentials never displays stored secret values and clears inputs after submission", async () => {
    vi.spyOn(traderApi, "GET").mockResolvedValue({
      data: {
        data: {
          available: true,
          items: [
            {
              kind: "indodax",
              configured: true,
              hint: "9f2a",
              created_at: "2026-11-15T00:00:00Z",
              last_test_at: "2026-11-15T00:00:00Z",
              last_test_ok: true,
              readable: true,
            },
            {
              kind: "telegram",
              configured: false,
            },
          ],
        },
        meta: {
          source: "trader",
          origin: "LIVE",
          as_of: "2026-11-15T00:00:00Z",
          stale: false,
        },
      },
      response: new Response(null, { status: 200 }),
    } as never);

    vi.spyOn(traderApi, "POST").mockResolvedValue({
      data: {
        data: { grant: "grant-token-1" },
        meta: { source: "trader", origin: "LIVE", as_of: "2026-11-15T00:00:00Z", stale: false },
      },
      response: new Response(null, { status: 200 }),
    } as never);

    const putSpy = vi.spyOn(traderApi, "PUT").mockResolvedValue({
      error: {
        error: {
          class: "VALIDATION",
          code: "credential_refused",
          message: "withdrawal permission detected",
          correlation_id: "corr-99",
        },
      },
      response: new Response(null, { status: 422 }),
    } as never);

    renderWithProviders(<TraderCredentials />);

    await waitFor(() => {
      expect(screen.getByText(/Stored, ending in 9f2a/i)).toBeTruthy();
    });

    const keyInput = screen.getByLabelText("API key") as HTMLInputElement;
    const secretInput = screen.getByLabelText("Secret") as HTMLInputElement;
    expect(keyInput.type).toBe("password");
    expect(secretInput.type).toBe("password");
    expect(keyInput.value).toBe("");
    expect(secretInput.value).toBe("");

    fireEvent.change(keyInput, { target: { value: "candidate-key-123456" } });
    fireEvent.change(secretInput, { target: { value: "candidate-secret-123456" } });

    fireEvent.click(screen.getAllByRole("button", { name: "Test, then store" })[0]);

    // Step-up dialog opens; enter password and submit
    const stepUpDialog = screen.getByRole("dialog", { name: "Confirm your identity again" });
    expect(stepUpDialog).toBeTruthy();
    const pwdInput = screen.getByLabelText("Password") as HTMLInputElement;
    fireEvent.change(pwdInput, { target: { value: "owner-pass" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm and continue" }));

    await waitFor(() => {
      expect(putSpy).toHaveBeenCalledTimes(1);
    });

    // Even when the server refuses the credential, both inputs are immediately cleared
    await waitFor(() => {
      expect(keyInput.value).toBe("");
      expect(secretInput.value).toBe("");
      expect(screen.getByText("withdrawal permission detected")).toBeTruthy();
    });
  });

  it("StateBar renders for trader and admin roles, hides for investor, and offers HALT even when status is unavailable", async () => {
    vi.spyOn(traderApi, "GET").mockResolvedValue({
      error: {
        error: {
          class: "UNAVAILABLE",
          code: "db_down",
          message: "unavailable",
          correlation_id: "c-1",
        },
      },
      response: new Response(null, { status: 503 }),
    } as never);

    const { unmount } = renderWithProviders(<StateBar />, { role: "investor" });
    expect(screen.queryByRole("region")).toBeNull();
    unmount();

    renderWithProviders(<StateBar />, { role: "admin" });
    const region = screen.getByRole("region", { name: "Trader status and stop" });
    expect(region).toBeTruthy();
    expect(screen.getByRole("button", { name: "HALT" })).toBeTruthy();

    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain("UNAVAILABLE");
    });
  });

  it("OriginBadge, TraderErrorNote, and PanelBody distinguish loading, unavailable, stale, and PAPER origin", () => {
    renderWithProviders(
      <div>
        <OriginBadge origin="PAPER" />
        <TraderErrorNote
          error={new TraderError("timeout", "UNAVAILABLE", "indodax_timeout", "ref-1234", 503)}
        />
        <PanelBody
          query={{
            data: {
              data: "ok",
              meta: {
                source: "trader",
                origin: "PAPER",
                as_of: "2026-11-15T00:00:00Z",
                stale: true,
              },
            },
            error: null,
            isPending: false,
            isError: false,
            refetch: () => {},
            dataUpdatedAt: Date.now() - 15_000,
          }}
        >
          {(val) => <span>panel-{val}</span>}
        </PanelBody>
        <HaltButton disabled={false} />
      </div>,
    );

    expect(screen.getByText("PAPER, not real trades")).toBeTruthy();
    expect(screen.getByText("Reference: ref-1234")).toBeTruthy();
    expect(screen.getByText("Stale data")).toBeTruthy();
    expect(screen.getByText("panel-ok")).toBeTruthy();
  });
});
