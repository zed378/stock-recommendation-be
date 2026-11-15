import { describe, expect, it } from "vitest";
import { loaders } from "@/lazyPages";

describe("signed-in pages are lazy chunks", () => {
  // `lazy()` takes whatever `m[name]` is. A page whose export was renamed would give
  // `undefined`, and the route would throw when opened - tsc does not see it.
  for (const [name, load] of Object.entries(loaders)) {
    it(`${name} resolves and exports a component under that name`, async () => {
      const module = (await load()) as Record<string, unknown>;
      expect(typeof module[name], `${name} export`).toBe("function");
    });
  }

  it("keeps Landing and Login out of the lazy set", () => {
    expect(Object.keys(loaders)).not.toContain("Landing");
    expect(Object.keys(loaders)).not.toContain("Login");
  });
});
