import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { I18nContext, type I18n } from "@/i18n/context";
import { locales, type MessageKey } from "@/i18n/messages";
import { OriginPortfolioBlock } from "@/pages/Trader";

afterEach(cleanup);

const i18n: I18n = {
  locale: "en",
  setLocale: () => {},
  t: (key: MessageKey, values?: Record<string, string | number>) => {
    let msg: string = locales.en[key] ?? key;
    for (const [k, v] of Object.entries(values ?? {})) msg = msg.replaceAll(`{${k}}`, String(v));
    return msg;
  },
  n: (v) => String(v ?? "-"),
  money: (v) => String(v ?? "-"),
  pct: (v) => String(v ?? "-"),
  date: (v) => String(v ?? "-"),
  dateTime: (v) => String(v ?? "-"),
};

// The long values a live paper book produced.
const DATA = {
  origin: "PAPER" as const,
  configured: true,
  start_equity_idr: "74000",
  latest_equity_idr: "73843.43374045872",
  realised_pnl_idr: "0",
  daily_loss_idr: "0",
  drawdown_pct: "0.2506244550557837837837838",
  trades_closed: 0,
  positions: [
    {
      origin: "PAPER" as const,
      pair: "PIPPINIDR",
      quantity: "16.000000000000000000",
      avg_cost: "340.397370875",
      cost_basis_idr: "5446.357934",
      stop_price: "305.496321340000000000",
      target_price: null,
    },
  ],
};

// Testing Library collapses the non-breaking space the screen uses into a plain one.
const NBSP = " ";

describe("the portfolio block reads cleanly", () => {
  it("rounds for reading and keeps the exact value in the tooltip", () => {
    render(
      <I18nContext.Provider value={i18n}>
        <OriginPortfolioBlock data={DATA} />
      </I18nContext.Provider>,
    );
    expect(screen.getByText(`Rp${NBSP}73,843`).getAttribute("title")).toBe("73843.43374045872");
    expect(screen.getByText("0.25%").getAttribute("title")).toBe("0.2506244550557837837837838");
    expect(screen.getByText(`Rp${NBSP}340.3974`)).toBeTruthy();
    expect(screen.getByText(`Rp${NBSP}5,446`)).toBeTruthy();
    expect(screen.getByText(`Rp${NBSP}305.4963`)).toBeTruthy();
    expect(screen.queryByText(/43374045872/)).toBeNull(); // no long tail on screen
    expect(screen.getByText("16")).toBeTruthy();
  });

  it("keeps the origin on every figure: short word shown, full words for assistive tech", () => {
    render(
      <I18nContext.Provider value={i18n}>
        <OriginPortfolioBlock data={DATA} />
      </I18nContext.Provider>,
    );
    const full = screen.getAllByText("PAPER, not real trades");
    expect(full.length).toBeGreaterThanOrEqual(6); // five tiles plus the position row
    for (const node of full) expect(node.className).toContain("sr-only");
    const shown = screen.getAllByText("PAPER");
    expect(shown.length).toBe(full.length);
    // The badge wraps nothing: it cannot be squeezed into the figure beside it.
    expect(shown[0].parentElement?.className).toContain("whitespace-nowrap");
  });

  it("puts the figures in a table whose numbers are right-aligned and do not wrap", () => {
    render(
      <I18nContext.Provider value={i18n}>
        <OriginPortfolioBlock data={DATA} />
      </I18nContext.Provider>,
    );
    const row = screen.getByText("PIPPINIDR").closest("tr") as HTMLElement;
    const cells = within(row).getAllByRole("cell");
    for (const cell of cells.slice(1)) {
      expect(cell.className).toContain("text-right");
      expect(cell.className).toContain("whitespace-nowrap");
    }
    expect(within(row).getByText("-")).toBeTruthy(); // no target set
  });
});
