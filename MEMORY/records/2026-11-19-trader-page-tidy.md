# Trader page: the portfolio block tidied (2026-11-19)

Owner's request, with a screenshot of `/trader`: "rapikan UI nya". What the screenshot showed: figures with their full stored precision (`73,843.43374045872`, `0.2506244550557837837837838%`, `Rp 340.397370875`), the long origin badge ("PAPER, NOT REAL TRADES") repeated beside every figure and squeezed into overlapping boxes, "Rp" breaking away from its number, and a positions table whose columns overflowed the card.

Changes (display only; nothing sent to the server changes and the exact string stays in each figure's tooltip):
- `trader/format.ts`: exact decimal rounding on the digits (`roundDecimal`, half away from zero, no float) and `displayAmount` (whole rupiah from 1,000 up, two decimals below), `displayPrice` (more decimals the smaller the price), `displayQuantity` (up to eight decimals), `displayPercent` (two decimals), `trimZeros`.
- `trader/components.tsx`: `OriginBadge` gets a `compact` form for figures inside tiles and table rows: the short word (`PAPER`, `LIVE`) is shown, the full words ("PAPER, not real trades") stay as screen-reader text and as the tooltip, so every figure still states its origin. The card headers keep the full wording.
- `pages/Trader.tsx`: tiles with the value on one non-wrapping line and the badge under it; three columns from `sm` up; a positions table with right-aligned, non-wrapping numbers and a no-break space between "Rp" and the number; the page grids use `grid-cols-1`, because a bare grid column is `auto` and let the wide table stretch the card past a phone screen (204 px of horizontal page scroll at 390 px wide, now 0).
- Tests: 9 for the rounding and the block (131 Vitest in total); tsc and oxlint clean.

Checked in a real browser (Chrome, a local dev server with the API mocked, 1440 and 390 px wide): no element outside a scroller wider than the viewport at either size; screenshots read before and after. Not covered: the other Trader screens (paper assumptions, strategies, approvals), the live site, and any value shapes the mock did not include. Not deployed.
