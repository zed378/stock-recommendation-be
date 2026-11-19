import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nContext, type I18n } from "@/i18n/context";
import { locales, type MessageKey } from "@/i18n/messages";
import { StrategyBuilder, type BuilderStart } from "@/trader/StrategyBuilder";
import type { StrategyKind } from "@/trader/types";

const mutate = vi.fn();
vi.mock("@/trader/mutations", () => ({
  useSaveStrategyDef: () => ({ mutate, isPending: false, error: null }),
}));

afterEach(() => {
  cleanup();
  mutate.mockReset();
});

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

const KINDS: StrategyKind[] = [
  {
    kind: "donchian_breakout",
    family: "trend",
    fields: [
      { name: "entry_period", kind: "int", minimum: "2", maximum: "250", suggested: "20" },
      { name: "exit_period", kind: "int", minimum: "2", maximum: "250", suggested: "10" },
    ],
  },
];

function mount(start: Partial<BuilderStart> = {}) {
  render(
    <I18nContext.Provider value={i18n}>
      <StrategyBuilder
        kinds={KINDS}
        start={{ existing: false, id: "", label: "", kind: "donchian_breakout", params: {}, ...start }}
        onClose={() => {}}
        onSaved={() => {}}
      />
    </I18nContext.Provider>,
  );
}

const save = () => screen.getByRole("button", { name: "Save" }) as HTMLButtonElement;

describe("StrategyBuilder", () => {
  it("cannot save until every number is filled; suggested values are copied only on request", () => {
    mount();
    fireEvent.change(screen.getByLabelText(/^ID/), { target: { value: "my_break" } });
    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: "My break" } });
    expect((screen.getByLabelText(/entry_period/) as HTMLInputElement).value).toBe("");
    expect(save().disabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Fill with suggested values" }));
    expect((screen.getByLabelText(/entry_period/) as HTMLInputElement).value).toBe("20");
    expect(save().disabled).toBe(false);

    fireEvent.click(save());
    expect(mutate).toHaveBeenCalledTimes(1);
    expect(mutate.mock.calls[0][0]).toEqual({
      id: "my_break",
      label: "My break",
      kind: "donchian_breakout",
      params: { entry_period: "20", exit_period: "10" },
      existing: false,
    });
  });

  it("filling suggestions keeps numbers the owner already typed", () => {
    mount();
    fireEvent.change(screen.getByLabelText(/entry_period/), { target: { value: "30" } });
    fireEvent.click(screen.getByRole("button", { name: "Fill with suggested values" }));
    expect((screen.getByLabelText(/entry_period/) as HTMLInputElement).value).toBe("30");
    expect((screen.getByLabelText(/exit_period/) as HTMLInputElement).value).toBe("10");
  });

  it("rejects a bad id before anything is sent", () => {
    mount({ params: { entry_period: "20", exit_period: "10" }, label: "x" });
    fireEvent.change(screen.getByLabelText(/^ID/), { target: { value: "Bad Id" } });
    expect(screen.getByRole("alert").textContent).toMatch(/2 to 32 characters/);
    expect(save().disabled).toBe(true);
  });

  it("an edit keeps the id fixed", () => {
    mount({ existing: true, id: "my_break", label: "x", params: { entry_period: "20", exit_period: "10" } });
    expect((screen.getByLabelText(/^ID/) as HTMLInputElement).disabled).toBe(true);
    expect(save().disabled).toBe(false);
  });
});
