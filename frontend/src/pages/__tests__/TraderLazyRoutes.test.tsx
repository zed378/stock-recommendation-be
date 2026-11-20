import { Suspense, lazy } from "react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LazyTraderRoute } from "@/App";
import { I18nProvider } from "@/i18n";

afterEach(cleanup);

vi.mock("@/trader/TraderProvider", () => ({
  useTrader: () => ({
    status: {
      mode: "PAPER",
      halted: true,
      halt_reason: "manual",
      lease_holder: "trader-1",
      lease_expires_at: null,
      last_reconcile_at: null,
      exchange_configured: false,
      credentials: { indodax: { configured: false, readable: false }, telegram: { configured: false, readable: false } },
    },
    error: null,
    loading: false,
    refresh: vi.fn(),
  }),
}));

vi.mock("@/auth/context", () => ({
  useAuth: () => ({ user: { id: "1", email: "a@b.c", full_name: "A", role: "admin" } }),
}));

vi.mock("@/components/Toasts", () => ({
  useToasts: () => ({ push: vi.fn() }),
}));

vi.mock("@/trader/api", () => ({
  traderApi: {
    dashboard: vi.fn().mockResolvedValue({ orders: [], intents: [], approvals: [], equity: [], balances: [] }),
    approvals: vi.fn().mockResolvedValue([]),
    strategies: vi.fn().mockResolvedValue([]),
    limits: vi.fn().mockResolvedValue({}),
    parameters: vi.fn().mockResolvedValue({}),
    paperAssumptions: vi.fn().mockResolvedValue({}),
    credentials: vi.fn().mockResolvedValue({ indodax: { configured: false, readable: false }, telegram: { configured: false, readable: false } }),
    portfolio: vi.fn().mockResolvedValue({ origins: {} }),
    promotionThresholds: vi.fn().mockResolvedValue({}),
  },
}));

describe("Lazy-loaded Trader route modules", () => {
  it.each([
    ["Trader", () => import("@/pages/Trader").then((m) => ({ default: m.Trader }))],
    ["TraderApprovals", () => import("@/pages/TraderApprovals").then((m) => ({ default: m.TraderApprovals }))],
    ["TraderStrategies", () => import("@/pages/TraderStrategies").then((m) => ({ default: m.TraderStrategies }))],
    ["TraderSignals", () => import("@/pages/TraderSignals").then((m) => ({ default: m.TraderSignals }))],
    ["TraderLimits", () => import("@/pages/TraderLimits").then((m) => ({ default: m.TraderLimits }))],
    ["TraderParameters", () => import("@/pages/TraderParameters").then((m) => ({ default: m.TraderParameters }))],
    ["TraderPaper", () => import("@/pages/TraderPaper").then((m) => ({ default: m.TraderPaper }))],
    ["TraderCredentials", () => import("@/pages/TraderCredentials").then((m) => ({ default: m.TraderCredentials }))],
  ])("resolves and mounts %s via React.lazy", async (_name, loader) => {
    const LazyComp = lazy(loader);
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={qc}>
        <I18nProvider>
          <MemoryRouter>
            <Suspense fallback={<div>loading</div>}>
              <LazyComp />
            </Suspense>
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );
    const heading = await within(container).findByRole("heading", { level: 1 });
    expect(heading.textContent?.trim().length).toBeGreaterThan(0);
  });

  it("renders i18n error fallback with reload button when lazy import() rejects", async () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const onReload = vi.fn();
    const BrokenLazy = lazy(() => Promise.reject(new TypeError("Failed to fetch dynamically imported module")));
    const { container } = render(
      <I18nProvider>
        <MemoryRouter initialEntries={["/trader/paper"]}>
          <LazyTraderRoute onReload={onReload}>
            <BrokenLazy />
          </LazyTraderRoute>
        </MemoryRouter>
      </I18nProvider>,
    );
    const alert = await within(container).findByRole("alert");
    expect(within(alert).getByRole("heading", { level: 1 }).textContent).toBeTruthy();
    const btn = within(alert).getByRole("button");
    fireEvent.click(btn);
    expect(onReload).toHaveBeenCalledTimes(1);
    spy.mockRestore();
  });
});
