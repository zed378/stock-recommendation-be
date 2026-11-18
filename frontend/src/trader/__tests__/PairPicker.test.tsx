import type { ReactNode } from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nContext, type I18n } from "@/i18n/context";
import { locales, type MessageKey } from "@/i18n/messages";
import { PairPicker } from "@/trader/PairPicker";
import type { CatalogPair } from "@/trader/types";

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

const row = (pair: string, volume: string | null, trading = true): CatalogPair => ({
  pair,
  asset: pair.slice(0, -3),
  min_order_idr: "10000",
  trading,
  quote_volume_24h_idr: volume,
  spread_pct: volume ? "0.1000" : null,
});

const CATALOG = [
  row("BTCIDR", "9000000000"),
  row("ETHIDR", "5000000000"),
  row("DOGEIDR", "2000000000"),
  row("HALTIDR", "100", false),
];

function mount(props: Partial<Parameters<typeof PairPicker>[0]> = {}): {
  onChange: ReturnType<typeof vi.fn>;
  onSaveGroups: ReturnType<typeof vi.fn>;
} {
  const onChange = vi.fn();
  const onSaveGroups = vi.fn();
  const ui: ReactNode = (
    <I18nContext.Provider value={i18n}>
      <PairPicker
        catalog={CATALOG}
        catalogError={null}
        selected={[]}
        onChange={onChange}
        groups={[]}
        onSaveGroups={onSaveGroups}
        groupsBusy={false}
        groupsError={null}
        {...props}
      />
    </I18nContext.Provider>
  );
  render(ui);
  return { onChange, onSaveGroups };
}

describe("PairPicker", () => {
  it("lists every market with its volume and marks the ones that are not trading", () => {
    mount();
    const list = screen.getByRole("group", { name: "IDR pairs on Indodax" });
    expect(within(list).getAllByRole("checkbox")).toHaveLength(4);
    expect(within(list).getByText("9,000,000,000")).toBeTruthy();
    expect(within(list).getByText("not trading")).toBeTruthy();
  });

  it("filters by search and selects only what is visible", () => {
    const { onChange } = mount({ selected: ["BTCIDR"] });
    fireEvent.change(screen.getByLabelText("Search pair or asset"), { target: { value: "doge" } });
    const list = screen.getByRole("group", { name: "IDR pairs on Indodax" });
    expect(within(list).getAllByRole("checkbox")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Select visible (1)" }));
    expect(onChange).toHaveBeenCalledWith(["BTCIDR", "DOGEIDR"]);
  });

  it("ticks and unticks a single pair", () => {
    const { onChange } = mount({ selected: ["ETHIDR"] });
    const list = screen.getByRole("group", { name: "IDR pairs on Indodax" });
    const boxes = within(list).getAllByRole("checkbox") as HTMLInputElement[];
    expect(boxes[1].checked).toBe(true);
    fireEvent.click(boxes[0]);
    expect(onChange).toHaveBeenLastCalledWith(["BTCIDR", "ETHIDR"]);
    fireEvent.click(boxes[1]);
    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  it("ticking a group selects its pairs without saving anything", () => {
    const { onChange, onSaveGroups } = mount({
      selected: ["DOGEIDR"],
      groups: [{ name: "Majors", pairs: ["BTCIDR", "ETHIDR"] }],
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /Majors/ }));
    expect(onChange).toHaveBeenCalledWith(["BTCIDR", "DOGEIDR", "ETHIDR"]);
    expect(onSaveGroups).not.toHaveBeenCalled();
  });

  it("saves the current selection as a named group, and deletes one", () => {
    const { onSaveGroups } = mount({
      selected: ["BTCIDR", "ETHIDR"],
      groups: [{ name: "Old", pairs: ["DOGEIDR"] }],
    });
    const save = screen.getByRole("button", { name: "Save selection as a group" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true); // no name yet
    fireEvent.change(screen.getByLabelText("Group name"), { target: { value: "  Large   caps " } });
    fireEvent.click(save);
    expect(onSaveGroups).toHaveBeenLastCalledWith([
      { name: "Large caps", pairs: ["BTCIDR", "ETHIDR"] },
      { name: "Old", pairs: ["DOGEIDR"] },
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Delete group Old" }));
    expect(onSaveGroups).toHaveBeenLastCalledWith([]);
  });

  it("a group is not saved from an empty selection", () => {
    mount({ selected: [] });
    fireEvent.change(screen.getByLabelText("Group name"), { target: { value: "Empty" } });
    expect((screen.getByRole("button", { name: "Save selection as a group" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Select some pairs first to save them as a group.")).toBeTruthy();
  });

  it("says why the list is missing, and still offers the groups section", () => {
    mount({ catalog: null, catalogError: "no exchange is configured, so the pair list cannot be fetched" });
    expect(screen.getByText(/no exchange is configured/)).toBeTruthy();
    expect(screen.getByText("Pair groups")).toBeTruthy();
  });

  it("flags a selected pair that the exchange no longer lists", () => {
    mount({ selected: ["GONEIDR"] });
    expect(screen.getByText("Not in the exchange list right now: GONEIDR")).toBeTruthy();
  });
});
