# 2026-11-15 — Phone tap targets: 44px minimum below `sm` on shared controls

Prompted by Task P noting the asset page's `1d / 1w / 1M` buttons at about 28px, then measured across the app. Repository only: **not built
or deployed**.

## Measurement (local browser, mocked API, 375px)

Before: in `<main>`, `/assets/BBCA` 5 controls under 44px (timeframe buttons 33x24, "Fetch price data" 138x38, a 35x19 link); `/monitoring` 7
(tab buttons, "Mark all read" and "Delete all" 26px, inputs 38px); `/picks` 10 (period buttons 24px, Previous/Next 26px, page-size select 31px, two
13px checkboxes); `/journal` 3 and `/portfolio` 4 (inputs and buttons 38px). So the compact 38px `Button`/input size, and several hand-made 24 to 26px
controls, are the app's norm on phones, not one-off misses.

## Change

Applied only below the `sm` breakpoint (`max-sm:min-h-11` = 44px); from `sm` up nothing changes.
- `primitives.tsx`: both `Button` sizes, `inputClass` and `inlineControlClass` (used by selects and toolbar controls).
- Hand-made segmented buttons: the timeframe selector in `AssetDetail.tsx` and the horizon selector in `StockPicks.tsx` (`max-sm:min-h-11 max-sm:min-w-11`).
- `Monitoring.tsx`: its two-tab row now uses `TabStrip`, which already has the 44px phone height and scrolls inside itself.
- `PhoneTapTargets.test.tsx` pins the classes (jsdom has no layout).

## Measured after

At 375px the controls under 44px in `<main>` fall to: `/assets/BBCA` 1, `/monitoring` 1, `/picks` 2, `/journal` 0, `/portfolio` 0. The remainder is the
TradingView attribution link that `lightweight-charts` requires (35x19) and the native 13px checkboxes. At 1280px the heights are unchanged (timeframe 33x24,
buttons 38px). Overflow check at 375, 320 and 1280px: document width equals the viewport. `tsc` 5.9.3 and `oxlint` clean; Vitest 82 passed with
`--pool=vmThreads`; build 0.8 s.

## Not verified / left alone

- Not run in production; the API was mocked. Other screens with small controls that were not measured: the admin pages, the notifications panel, dialogs.
  Controls built by hand with `py-0.5` or `py-1` outside the shared primitives (several in `components/admin/*`, `Layout.tsx`, `Strategy.tsx`,
  `TranslateToggle.tsx`, `MultiSelect.tsx`) were not changed.
- The native checkboxes stay 13px; making them 44px needs a larger hit area around the label, which is a per-screen markup change.
- Taller controls on phones change density: toolbars with several `sm` buttons take more vertical space below 640px. Not reviewed screen by screen.
