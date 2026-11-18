import { describe, expect, it } from "vitest";
import { locales } from "../../i18n/messages";

const INTERNAL_DOC_REF = /\b(?:ADR|OQ)-\d+\b/;

describe("UI copy hygiene", () => {
  it("contains no internal ADR or OQ document identifiers in id or en copy", () => {
    for (const [localeName, table] of Object.entries(locales)) {
      for (const [key, value] of Object.entries(table)) {
        expect(
          INTERNAL_DOC_REF.test(value),
          `${localeName}.${key} leaks internal doc id: ${value}`,
        ).toBe(false);
      }
    }
  });
});
