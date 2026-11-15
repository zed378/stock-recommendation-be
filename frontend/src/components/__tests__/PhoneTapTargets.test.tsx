import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Button, inlineControlClass, inputClass } from "@/components/primitives";

afterEach(cleanup);

// 44px is the touch-target minimum; `max-sm:min-h-11` applies it below the `sm` breakpoint only, so the
// compact desktop height is unchanged. jsdom has no layout, so these pin the classes; the heights were
// measured in a browser at 375px (and left unchanged at 1280px).
describe("phone tap targets", () => {
  it("gives both Button sizes a 44px minimum height on phones", () => {
    render(
      <>
        <Button size="sm">Small</Button>
        <Button>Medium</Button>
      </>,
    );
    expect(screen.getByRole("button", { name: "Small" })).toHaveClass("max-sm:min-h-11");
    expect(screen.getByRole("button", { name: "Medium" })).toHaveClass("max-sm:min-h-11");
  });

  it("gives form and toolbar controls the same minimum", () => {
    expect(inputClass).toContain("max-sm:min-h-11");
    expect(inlineControlClass).toContain("max-sm:min-h-11");
  });
});
