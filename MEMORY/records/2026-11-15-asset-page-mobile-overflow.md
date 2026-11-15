# 2026-11-15 — `/assets/:ticker` overflowed 148px sideways on a 375px phone

Found by Task O (Playwright on production): `scrollWidth 523` on a 375px viewport for `/assets/BBCA`; 0 at 768 and 1280.
Fixed in the repository; **not built or deployed**, so production still has it.

## Cause

The six asset tabs (Chart, Indicators, Fundamentals, Analysis, Strategy, News) were a plain `<nav class="flex gap-1 border-b">`.
Their labels add up to about 507px, wider than the 343px content column of a 375px phone, so the row pushed the whole document
wider. It does not depend on data. Earlier guesses (the fundamentals table, the `min-w-64` blocks) were wrong; those are already
inside `overflow-x-auto` or `flex-wrap`.

## Reproduction

A local Vite server with the API mocked in Playwright (scripts in `%TEMP%\aidss-pw-verify`, not in the repo; mock data is
invented, no production call). With empty responses nothing overflowed; with the page rendering for real it gave
`scrollWidth 523` at 375, 360 and 320, the same figure as production, and listed the tab buttons as the only elements past the edge.
(A first attempt was invalid: the mock pattern `**/api/**` also caught the module `/src/api/client.ts`, so the page never rendered.)

## Fix

New `frontend/src/components/TabStrip.tsx`: the strip scrolls inside itself (`overflow-x-auto`), each tab keeps its whole label
(`shrink-0 whitespace-nowrap`), the selected tab is scrolled into view, `aria-current="page"` marks it, and under `sm` each tab is 44px
high (46px measured; 38px from `sm` up, unchanged). `AssetDetail.tsx` uses it. `-mb-px` was dropped: inside a scroll container it would clip
the bottom pixel of the active underline, so the red line now sits just above the grey baseline instead of over it (1px difference).

## Measured after the fix (browser, mocked API)

- Document `scrollWidth` equals the viewport at 375, 360, 320, 768 and 1280.
- At 375 the strip is 343px wide with 507px of content; clicking News scrolls it into view (`scrollLeft 164`, fully visible, `aria-current="page"`);
  back to Chart returns to 0. At 320 the same. At 1280 the strip does not scroll.
- `tsc` 5.9.3 clean, `oxlint` clean, Vitest 78 passed with `--pool=vmThreads` (4 new tests in `TabStrip.test.tsx`), build 1.0 s. The default
  pool failed on this machine, also on a clean HEAD (see memory note); not a result of this change.

## Not verified / left alone

- Not run against production, and not with real API data: the mock stands in for it. The cause does not depend on data, but the final proof is a
  re-run of the 375px check after a deploy.
- `Monitoring.tsx` has the same tab markup (two tabs, no overflow today); left as is.
- Other small targets on the same page (the `1d / 1w / 1M` timeframe buttons are about 28px high, under the 44px guideline) were not changed.
- jsdom has no layout, so the unit tests pin the two properties that fix it (`overflow-x-auto`, `shrink-0 whitespace-nowrap`), not the width.
