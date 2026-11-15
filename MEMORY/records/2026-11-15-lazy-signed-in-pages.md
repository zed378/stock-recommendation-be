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

Not verified: any of this in a browser. Route changes, the loading state between pages, and a chunk that fails to load
were not exercised (Task N, the Playwright pass on lazy loading, is the owner of the last two). The error boundary
Task N may add to `App.tsx` will overlap with this branch's edit to the same file; merge after that handoff.
