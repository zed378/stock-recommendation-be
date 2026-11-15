# 2026-11-15 — Signed-in pages as lazy chunks (main bundle 635 kB to 247 kB)

Branch `perf/lazy-pages`, built on `8cf6f9f`. Not merged into `main` and not deployed.

After the Trader pages were made lazy the main chunk was still 635 kB (gzip 145 kB). The rest was every signed-in page,
loaded eagerly. They are now one chunk each, behind `frontend/src/lazyPages.ts`; `App.tsx` wraps each route in a small
`Page` component (one `Suspense` per route, inside the layout, so the sidebar stays while a chunk loads).
`Landing` and `Login` stay in the main bundle: they are what a signed-out visitor sees first.

Measured (`npm run build`): main chunk `index-*.js` 635.03 kB to 247.18 kB, gzip 145.48 kB to 71.68 kB. Page chunks, for
example `Admin` 60.32 kB, `AssetDetail` 49.50 kB, `Watchlist` 12.29 kB, `Monitoring` 9.39 kB.

Tests: `src/pages/__tests__/LazyPages.test.ts` resolves every loader and checks the page is exported under the name
`lazy()` expects. That is the failure `tsc` cannot see: a renamed export would make a route render `undefined` when
opened. Vitest 72 passed (was 58), `tsc` and `oxlint` clean.

Merged with Task N's `ChunkErrorBoundary` (`e4e99c0`), which the Playwright pass showed was missing: with
`ab5a9ab` a lazy chunk that fails to load left a blank screen (the same applies to every page made lazy here). The boundary
component is now exported as `LazyRoute` and wraps all lazy routes, Trader and not; `LazyTraderRoute` stays as an alias so
Task N's test and call sites keep working. Its messages (`trader.routeError.*`) are generic ("Page failed to load").
Vitest 73 passed, `tsc` and `oxlint` clean, main chunk 248.37 kB (gzip 72.05 kB).

Not verified: any of this in a browser. Route changes, the loading state between pages, and a failed chunk load on a
non-Trader page were not exercised (the Playwright evidence from Task N covers only the Trader routes, on `ab5a9ab`).
