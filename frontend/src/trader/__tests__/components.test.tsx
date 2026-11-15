import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthContext, type Auth } from "@/auth/context";
import { ToastContext } from "@/components/toastContext";
import { I18nContext, type I18n } from "@/i18n/context";
import { locales, type Locale, type MessageKey } from "@/i18n/messages";
import { OriginPortfolioBlock, Trader } from "@/pages/Trader";
import { TraderApprovals } from "@/pages/TraderApprovals";
import { TraderCredentials } from "@/pages/TraderCredentials";
import { TraderLimits } from "@/pages/TraderLimits";
import { TraderPaper } from "@/pages/TraderPaper";
import { TraderParameters } from "@/pages/TraderParameters";
import { TraderStrategies } from "@/pages/TraderStrategies";
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

  it("OriginPortfolioBlock labels every figure and position with its origin badge", () => {
    renderWithProviders(
      <OriginPortfolioBlock
        data={{
          origin: "PAPER",
          configured: true,
          start_equity_idr: "100000000",
          latest_equity_idr: "102500000",
          realised_pnl_idr: "2500000",
          daily_loss_idr: "0",
          drawdown_pct: "1.2",
          trades_closed: 4,
          positions: [
            {
              origin: "PAPER",
              pair: "BTCIDR",
              quantity: "0.01",
              avg_cost: "1000000000",
              cost_basis_idr: "10000000",
              stop_price: "950000000",
              target_price: "1100000000",
            },
          ],
        }}
      />,
    );

    expect(screen.getByText("BTCIDR")).toBeTruthy();
    expect(screen.getAllByText("PAPER, not real trades").length).toBeGreaterThanOrEqual(6);
  });

  it("renders all 7 Trader pages with populated tables in ID and EN, localizes ledger headers, and never uses low-contrast text-faint", async () => {
    vi.spyOn(traderApi, "GET").mockImplementation(async (url: string) => {
      const meta = {
        source: "trader",
        origin: "LIVE",
        as_of: "2026-11-15T00:00:00Z",
        stale: false,
      };
      if (url === "/trader/v1/dashboard") {
        return {
          data: {
            data: {
              state: "HALTED",
              state_reason: "manual",
              state_since: "2026-11-15T00:00:00Z",
              balances: [
                {
                  origin: "LIVE",
                  asset: "IDR",
                  free: "10000000",
                  locked: "0",
                  updated_at: "2026-11-15T00:00:00Z",
                },
              ],
              positions: [],
              open_orders: [
                {
                  client_order_id: "ord-1",
                  intent_identity: "int-1",
                  exchange_order_id: "ex-1",
                  origin: "LIVE",
                  pair: "BTCIDR",
                  side: "BUY",
                  order_type: "LIMIT",
                  price: "1500000000",
                  quantity: "0.001",
                  filled_quantity: "0",
                  state: "OPEN",
                  submitted_at: "2026-11-15T00:00:00Z",
                },
              ],
              approvals_pending: [],
            },
            meta,
          },
          response: new Response(null, { status: 200 }),
        } as never;
      }
      if (url === "/trader/v1/reconciliation") {
        return {
          data: {
            data: {
              runs: [
                {
                  started_at: "2026-11-15T00:00:00Z",
                  result: "clean",
                  differences: 0,
                },
              ],
              unresolved: [],
            },
            meta,
          },
          response: new Response(null, { status: 200 }),
        } as never;
      }
      if (url === "/trader/v1/events") {
        return {
          data: {
            data: [
              {
                id: 1,
                severity: "INFO",
                message: "halted by operator",
                created_at: "2026-11-15T00:00:00Z",
                acked_at: null,
              },
            ],
            meta,
          },
          response: new Response(null, { status: 200 }),
        } as never;
      }
      if (url === "/trader/v1/portfolio") {
        return {
          data: {
            data: {
              live: {
                origin: "LIVE",
                configured: true,
                start_equity_idr: "10000000",
                latest_equity_idr: "10000000",
                realised_pnl_idr: "0",
                daily_loss_idr: "0",
                drawdown_pct: "0",
                trades_closed: 0,
                positions: [],
              },
              paper: {
                origin: "PAPER",
                configured: true,
                start_equity_idr: "50000000",
                latest_equity_idr: "51000000",
                realised_pnl_idr: "1000000",
                daily_loss_idr: "0",
                drawdown_pct: "0.5",
                trades_closed: 2,
                positions: [],
              },
              backtests: [
                {
                  id: "bt-1",
                  origin: "BACKTEST",
                  strategy_id: "strat-1",
                  strategy_version: "v-1-2026-11-15",
                  pair: "BTCIDR",
                  trades: 5,
                  win_rate_pct: "60.0",
                  total_return_pct: "4.5",
                  max_drawdown_pct: "3.2",
                  ran_at: "2026-11-15T00:00:00Z",
                },
              ],
            },
            meta,
          },
          response: new Response(null, { status: 200 }),
        } as never;
      }
      if (url === "/trader/v1/ledger") {
        return {
          data: {
            data: [
              {
                at: "2026-11-15T00:00:00Z",
                origin: "PAPER",
                entry_type: "DEPOSIT",
                asset: "IDR",
                amount: "50000000",
                reason: "initial paper capital",
              },
            ],
            meta: { ...meta, origin: "PAPER" },
          },
          response: new Response(null, { status: 200 }),
        } as never;
      }
      if (url === "/trader/v1/intents") {
        return {
          data: {
            data: [
              {
                identity: "int-1",
                strategy_id: "ema_adx",
                pair: "BTCIDR",
                side: "BUY",
                entry_price: "1500000000",
                quantity: "0.001",
                stop_price: "1450000000",
                risk_amount_idr: "50000",
                approval: {
                  state: "AWAITING",
                  expires_at: "2026-11-15T01:00:00Z",
                  card_hash: "hash-1",
                  reason: null,
                },
              },
            ],
            meta,
          },
          response: new Response(null, { status: 200 }),
        } as never;
      }
      if (url === "/trader/v1/strategies") {
        return {
          data: {
            data: [
              {
                strategy_id: "ema_adx",
                mode: "PAPER",
                version: "v-1",
                since: "2026-11-15T00:00:00Z",
              },
            ],
            meta,
          },
          response: new Response(null, { status: 200 }),
        } as never;
      }
      if (url === "/trader/v1/strategies/{strategy_id}/promotion") {
        return {
          data: {
            data: {
              strategy_id: "ema_adx",
              mode: "PAPER",
              next: "APPROVAL",
              gates: [
                {
                  name: "duration",
                  passed: false,
                  measured: "14",
                  threshold: null,
                  reason: "threshold unset",
                },
              ],
            },
            meta,
          },
          response: new Response(null, { status: 200 }),
        } as never;
      }
      if (url === "/trader/v1/strategies/{strategy_id}/parameters") {
        return {
          data: {
            data: {
              strategy_id: "ema_adx",
              version: "v-1",
              mode: "PAPER",
              max_history_bars: 500,
              params: {
                ema_fast: "12",
                ema_slow: "26",
                adx_period: "14",
                adx_threshold: "25",
                atr_period: "14",
                atr_stop_multiple: "2",
                cooldown_s: "60",
              },
            },
            meta,
          },
          response: new Response(null, { status: 200 }),
        } as never;
      }
      if (url === "/trader/v1/paper-config") {
        return {
          data: {
            data: {
              configured: true,
              paper_fills: 2,
              starting_capital_idr: "50000000",
              maker_fee_pct: "0.1",
              taker_fee_pct: "0.2",
              slippage_bps: "5",
            },
            meta: { ...meta, origin: "PAPER" },
          },
          response: new Response(null, { status: 200 }),
        } as never;
      }
      if (url === "/trader/v1/promotion-thresholds") {
        return {
          data: {
            data: {
              thresholds: {
                min_paper_trades: null,
                max_paper_drawdown_pct: null,
                backtest_min_return_pct: null,
                max_live_capital_idr: null,
                max_slippage_pct: null,
              },
              unset: ["min_paper_trades"],
            },
            meta,
          },
          response: new Response(null, { status: 200 }),
        } as never;
      }
      if (url === "/trader/v1/limits") {
        return {
          data: {
            data: {
              version: 1,
              limits: {
                max_order_notional_idr: null,
              },
              unset: ["max_order_notional_idr"],
            },
            meta,
          },
          response: new Response(null, { status: 200 }),
        } as never;
      }
      if (url === "/trader/v1/allowlist") {
        return {
          data: {
            data: {
              active: false,
              pairs: ["BTCIDR"],
              min_quote_volume_24h_idr: null,
              max_spread_pct: null,
            },
            meta,
          },
          response: new Response(null, { status: 200 }),
        } as never;
      }
      if (url === "/trader/v1/credentials") {
        return {
          data: {
            data: {
              available: true,
              items: [
                { kind: "indodax", configured: false, readable: true },
                { kind: "telegram", configured: false, readable: true },
              ],
            },
            meta,
          },
          response: new Response(null, { status: 200 }),
        } as never;
      }
      return {
        data: { data: [], meta },
        response: new Response(null, { status: 200 }),
      } as never;
    });

    const pages = [
      <Trader key="trader" />,
      <TraderApprovals key="approvals" />,
      <TraderStrategies key="strategies" />,
      <TraderParameters key="parameters" />,
      <TraderPaper key="paper" />,
      <TraderLimits key="limits" />,
      <TraderCredentials key="credentials" />,
    ];

    // Check Indonesian rendering
    const { container: idContainer, unmount: unmountId } = renderWithProviders(<div>{pages}</div>, {
      locale: "id",
    });
    await waitFor(() => {
      expect(screen.getByText("initial paper capital")).toBeTruthy();
      expect(screen.getByText("Waktu")).toBeTruthy();
      expect(screen.getByText("Alasan")).toBeTruthy();
      expect(screen.getAllByText("BACKTEST, simulasi historis").length).toBeGreaterThanOrEqual(2);
    });
    expect(idContainer.querySelectorAll(".text-faint").length).toBe(0);
    expect(idContainer.querySelectorAll(".overflow-x-auto").length).toBeGreaterThanOrEqual(3);
    unmountId();

    // Check English rendering
    const { container: enContainer, unmount: unmountEn } = renderWithProviders(<div>{pages}</div>, {
      locale: "en",
    });
    await waitFor(() => {
      expect(screen.getByText("initial paper capital")).toBeTruthy();
      expect(screen.getByText("Reason")).toBeTruthy();
      expect(screen.getAllByText("BACKTEST, historical simulation").length).toBeGreaterThanOrEqual(2);
    });
    expect(enContainer.querySelectorAll(".text-faint").length).toBe(0);
    unmountEn();
  });
});
