import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TabStrip } from "@/components/TabStrip";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const tabs = [
  { id: "chart", label: "Chart" },
  { id: "indicators", label: "Indicators" },
  { id: "fundamentals", label: "Fundamentals" },
  { id: "analysis", label: "Analysis" },
  { id: "strategy", label: "Strategy" },
  { id: "news", label: "News" },
] as const;

describe("TabStrip", () => {
  it("marks only the selected tab as current and reports clicks by id", () => {
    const onChange = vi.fn();
    render(<TabStrip tabs={[...tabs]} active="analysis" onChange={onChange} label="Asset sections" />);

    expect(screen.getByRole("navigation", { name: "Asset sections" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Analysis" })).toHaveAttribute("aria-current", "page");
    expect(screen.getAllByRole("button").filter((b) => b.hasAttribute("aria-current"))).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "News" }));
    expect(onChange).toHaveBeenCalledWith("news");
  });

  // The bug: six tabs added up to ~520px, and a plain flex row of that width made the whole
  // page scroll sideways on a 375px phone. jsdom has no layout, so this pins the two
  // properties that fix it; the real measurement was taken in a browser at 375/360/320px.
  it("scrolls inside itself and keeps every tab label whole", () => {
    render(<TabStrip tabs={[...tabs]} active="chart" onChange={() => {}} />);

    expect(screen.getByRole("navigation")).toHaveClass("overflow-x-auto");
    for (const button of screen.getAllByRole("button")) {
      expect(button).toHaveClass("shrink-0", "whitespace-nowrap");
    }
  });

  it("scrolls the selected tab into view when it changes", () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    const { rerender } = render(<TabStrip tabs={[...tabs]} active="chart" onChange={() => {}} />);
    scrollIntoView.mockClear();

    rerender(<TabStrip tabs={[...tabs]} active="news" onChange={() => {}} />);

    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(scrollIntoView).toHaveBeenCalledWith({ block: "nearest", inline: "nearest" });
    // @ts-expect-error restoring the jsdom default (the method does not exist there)
    delete Element.prototype.scrollIntoView;
  });

  it("does not fail where scrollIntoView is not implemented", () => {
    expect(() =>
      render(<TabStrip tabs={[...tabs]} active="strategy" onChange={() => {}} />),
    ).not.toThrow();
  });
});
