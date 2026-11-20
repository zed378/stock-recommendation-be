import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nContext, type I18n } from "@/i18n/context";
import { locales } from "@/i18n/messages";
import { SignalBuilder } from "@/trader/SignalBuilder";

const mutate = vi.fn();
vi.mock("@/trader/mutations", () => ({
  useSaveStrategyDef: () => ({ mutate, isPending: false, error: null }),
}));
const i18n: I18n = {
  locale: "en", setLocale: () => {}, t: (key) => locales.en[key],
  n: String, money: String, pct: String, date: String, dateTime: String,
};
afterEach(() => { cleanup(); mutate.mockReset(); });
function mount() {
  render(<I18nContext.Provider value={i18n}><SignalBuilder
    start={{ existing: false, id: "", label: "", kind: "signal_builder", params: {} }}
    onClose={() => {}} onSaved={() => {}} /></I18nContext.Provider>);
}
const save = () => screen.getByRole("button", { name: "Save" }) as HTMLButtonElement;

describe("Indodax signal builder", () => {
  it("leaves every owner number empty and refuses incomplete definitions", () => {
    mount();
    expect(screen.getByLabelText("ATR stop multiple")).toHaveValue("");
    expect(screen.getByLabelText("Minimum AI review score (0-100)")).toHaveValue("");
    expect(save()).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/^ID/), { target: { value: "my_rules" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "My rules" } });
    expect(save()).toBeDisabled();
  });
  it("saves explicit Indodax IDR rule groups through the existing audited definition mutation", () => {
    mount();
    fireEvent.change(screen.getByLabelText(/^ID/), { target: { value: "my_rules" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "My rules" } });
    for (const input of screen.getAllByLabelText("Value"))
      fireEvent.change(input, { target: { value: "100" } });
    const values: Record<string, string> = {
      "ATR period": "14", "ATR stop multiple": "2", "Cooldown after exit (seconds)": "0",
      "Maximum data age after candle close (seconds)": "3600",
      "Maximum review age (seconds)": "300", "Kronos forecast candles": "3",
      "Kronos samples": "1", "Minimum projected return (%)": "0.5",
      "Minimum AI review score (0-100)": "70",
    };
    for (const [label, value] of Object.entries(values))
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
    expect(save()).toBeEnabled();
    fireEvent.click(save());
    const submitted = mutate.mock.calls[0][0];
    expect(submitted.kind).toBe("signal_builder");
    const definition = JSON.parse(submitted.params.definition);
    expect(definition.exchange).toBe("INDODAX");
    expect(definition.quote).toBe("IDR");
    expect(definition.atr_stop_multiple).toBe("2");
    expect(definition.ai_min_score).toBe(70);
    expect(definition.entry.rules[0].right.value).toBe("100");
    expect(submitted.existing).toBe(false);
  });
  it("supports additional rules and crossover selection without running code", () => {
    mount();
    fireEvent.click(screen.getAllByRole("button", { name: "Add rule" })[0]);
    expect(screen.getAllByLabelText("Left operand")).toHaveLength(3);
    fireEvent.change(screen.getAllByLabelText("Comparison")[0], { target: { value: "crosses_above" } });
    expect(screen.getAllByLabelText("Comparison")[0]).toHaveValue("crosses_above");
    fireEvent.click(screen.getAllByRole("button", { name: "Remove rule" })[0]);
    expect(screen.getAllByLabelText("Left operand")).toHaveLength(2);
  });
});
