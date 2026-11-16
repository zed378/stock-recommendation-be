import { describe, expect, it } from "vitest";
import { locales } from "../../i18n/messages";

// Mirrors src/aidss/domain/types.py RecommendationLabel.
const VALID_RECOMMENDATION_LABELS = [
  "strong_buy",
  "buy",
  "watchlist",
  "hold",
  "reduce",
  "sell",
] as const;

describe("recommendation label i18n keys", () => {
  it("provides non-empty id and en labels for every backend RecommendationLabel", () => {
    for (const label of VALID_RECOMMENDATION_LABELS) {
      const key = `rec.label.${label}` as keyof typeof locales.id;
      const idText = locales.id[key];
      const enText = locales.en[key];
      expect(idText, `missing id label for ${key}`).toBeTruthy();
      expect(enText, `missing en label for ${key}`).toBeTruthy();
      expect(idText).not.toBe(key);
      expect(enText).not.toBe(key);
    }
  });
});
