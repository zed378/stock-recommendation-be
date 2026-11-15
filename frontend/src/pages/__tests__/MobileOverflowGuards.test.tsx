import "@testing-library/jest-dom/vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "@/i18n";
import { AssetDetail } from "@/pages/AssetDetail";
import { StockPicks } from "@/pages/StockPicks";

afterEach(cleanup);

vi.mock("@/components/Toasts", () => ({
  useToasts: () => ({ push: vi.fn() }),
}));

vi.mock("@/components/PriceChart", () => ({
  PriceChart: () => <div data-testid="mock-chart" />,
}));

vi.mock("@/api/client", () => {
  const picksPayload = {
    horizon: "swing",
    considered: 1,
    insufficient_history: [],
    picks: [
      {
        ticker: "ACES",
        name: "PT Aspirasi Hidup Indonesia Tbk",
        sector: "Consumer",
        close: 625,
        score: 4,
        out_of: 4,
        met: [{ key: "trend", describes: "Above SMA 50" }],
        unmet: [],
        unevaluable: [],
        limit_proximity: null,
      },
    ],
  };
  return {
    api: {
      GET: vi.fn().mockImplementation(async (path: string) => {
        if (path.includes("picks")) return { data: picksPayload };
        if (path.includes("candles") || path.includes("news")) return { data: [] };
        if (path.includes("analysis")) return { data: null };
        return { data: {} };
      }),
      POST: vi.fn().mockResolvedValue({ data: {} }),
      getAsset: vi.fn().mockResolvedValue({
        ticker: "BBCA",
        name: "Bank Central Asia",
        market: "IDX",
        sector: "Finance",
        latest_price: { close: 6500, change: 25, change_pct: 0.39, date: "2026-08-31" },
      }),
      getOhlcv: vi.fn().mockResolvedValue({ ticker: "BBCA", bars: [] }),
      getIndicators: vi.fn().mockResolvedValue({ ticker: "BBCA", indicators: {} }),
      getFundamentals: vi.fn().mockResolvedValue({ ticker: "BBCA", periods: [] }),
      getLatestAnalysis: vi.fn().mockResolvedValue(null),
      getNews: vi.fn().mockResolvedValue({ items: [] }),
      getStockPicks: vi.fn().mockResolvedValue(picksPayload),
    },
  };
});

function wrap(ui: React.ReactElement, initialEntry = "/") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <I18nProvider>
        <MemoryRouter initialEntries={[initialEntry]}>{ui}</MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("Mobile overflow guards", () => {
  it("wraps the AssetDetail Analysis mode selector and run button at narrow widths", async () => {
    wrap(
      <Routes>
        <Route path="/assets/:ticker" element={<AssetDetail />} />
      </Routes>,
      "/assets/BBCA",
    );

    const analysisTab = await screen.findByRole("button", { name: /Analysis|Analisis/i });
    fireEvent.click(analysisTab);

    const modeSelects = await screen.findAllByLabelText("Analysis mode");
    expect(modeSelects.length).toBeGreaterThan(0);
    for (const select of modeSelects) {
      expect(select.parentElement).toHaveClass("flex", "flex-wrap");
    }
  });

  it("uses grid-cols-1 on StockPicks so narrow viewports keep minmax(0, 1fr) tracks", async () => {
    wrap(<StockPicks />);

    const tickerLink = await screen.findByRole("link", { name: "ACES" });
    const cardSection = tickerLink.closest("section");
    expect(cardSection?.parentElement).toHaveClass("grid", "grid-cols-1");
  });
});
