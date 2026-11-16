# Task U: Production Landing Page (`/`) Read-Only Measurement (`220f1cb`)

**Date:** 2026-11-16
**Task:** U (Stage 10)
**Target:** `https://aidss.zedth.my.id/` (`aidss-frontend:220f1cb`, main chunk `/static/index-DUOgi8mR.js`)
**Environment:** Headless Playwright Chromium on Windows; screenshots and JSON report stored in `%TEMP%\aidss-pw-verify\out-stage10\` (`hero-1920.png`, `hero-2560.png`, `hero-375.png`, `report.json`). Zero code changes.

## 1. Version & Console/Network Cleanliness

- Main chunk observed: `/static/index-DUOgi8mR.js`.
- Console errors: `0`; page errors: `0`; CSP violations: `0`; unexpected failed requests (excluding `/api/` 401): `0`.

## 2. Hero Layout, Fonts & CLS Across 7 Viewports x 2 Languages

All 14 runs had `overflowPx: 0` (`document.documentElement.scrollWidth === window.innerWidth`), `intersects: false` (headline box and `.lp-stack` box never intersect), and `fontsLoaded: 3/3`.

| Viewport | Lang | `h1` font-size | `hGapPx` | `vGapPx` | Hero height | `/fonts/*` reqs | CLS (`layout-shift`) | `h1.scrollWidth > clientWidth` |
|---|---|---|---|---|---|---|---|---|
| `1920x1080` | `id` | `68.8px` | `64` | `-212` | `704px` | `3` | `0.001817` | `false` |
| `1920x1080` | `en` | `68.8px` | `64` | `-198` | `708px` | `5` | `0.016991` | `false` |
| `2560x1440` | `id` | `68.8px` | `64` | `-212` | `704px` | `5` | `0.000538` | `false` |
| `2560x1440` | `en` | `68.8px` | `64` | `-198` | `708px` | `3` | `0.081512` | `false` |
| `1440x900` | `id` | `68.8px` | `64` | `-212` | `704px` | `5` | `0.002865` | `false` |
| `1440x900` | `en` | `68.8px` | `64` | `-198` | `708px` | `5` | `0.136979` | `false` |
| `1024x768` | `id` | `51.2px` | `64` | `-108` | `657px` | `5` | `0.003370` | `false` |
| `1024x768` | `en` | `51.2px` | `64` | `-133` | `706px` | `5` | `0.003949` | `false` |
| `768x1024` | `id` | `44px` | `-624` | `304` | `959px` | `3` | `0.002137` | `false` |
| `768x1024` | `en` | `44px` | `-624` | `332` | `987px` | `5` | `0.003982` | `false` |
| `375x812` | `id` | `43.5px` | `-335` | `408` | `979px` | `5` | `0.006977` | `false` |
| `375x812` | `en` | `43.5px` | `-335` | `472` | `1086px` | `3` | `0.002628` | `true` (`342` vs `335` px) |
| `320x640` | `id` | `37.12px` | `-280` | `492` | `1014px` | `5` | `0.002105` | `false` |
| `320x640` | `en` | `37.12px` | `-280` | `548` | `1106px` | `3` | `0.000655` | `true` (`292` vs `280` px) |

**Observations (not edited):**
- At `375x812` (`en`) and `320x640` (`en`), the word `"recommendations"` extends `+7 px` (`342` vs `335 px`) and `+12 px` (`292` vs `280 px`) past the `h1` box's `clientWidth`, while remaining inside the viewport (`overflowPx: 0`).
- On `1440x900` (`en`) and `2560x1440` (`en`), `font-display: swap` produced CLS of `0.136979` and `0.081512` (vs `0.0005`–`0.0069` in `id`).
- Fresh uncached Playwright contexts observed either `3` or `5` `/fonts/*` requests (`inter-latin.woff2` and `newsreader-display.woff2` appeared twice in `5`-request runs).

## 3. Emulated Performance (CPU 4x slowdown + Fast 3G, 3 runs each)

> **Note:** Measured via CDP `Emulation.setCPUThrottlingRate(4)` and `Network.emulateNetworkConditions` (1.6 Mbps down / 750 kbps up / 150 ms RTT) on a single desktop machine; this is an emulation, not real mobile hardware or field Core Web Vitals.

- **`1440x900`:**
  - LCP (`h1#lp-hero-title.lp-display`): median **`2828 ms`**, range **`2456–2884 ms`**
  - CLS: median **`0.136979`**, range **`0.025374–0.136979`**
  - Transfer bytes: median **`383,100 B`**, range **`383,085–383,124 B`**
- **`375x812`:**
  - LCP (`h1#lp-hero-title.lp-display`): median **`2884 ms`**, range **`2316–3060 ms`**
  - CLS: median **`0.026922`**, range **`0.026922–0.026922`**
  - Transfer bytes: median **`383,132 B`**, range **`383,126–383,439 B`**
- **Interaction duration estimates (not INP, unthrottled Chromium):**
  - Open mobile menu (`375x812`): **`205 ms`**
  - Toggle `ID`/`EN` (`1440x900`): **`156 ms`**
  - Click `#lapisan` anchor (`1440x900`): **`115 ms`**

## 4. Reduced Motion & Keyboard Navigation

- **`reducedMotion: "reduce"`:** `--p` stayed `0.62`, `--rx`/`--ry` stayed `0` after scrolling hero and `#lapisan`; computed `transitionDuration` was `1e-05s` (~0 s) on `.lp-plane`, `.lp-stack-scene`, `.lp-reveal`; `hiddenReveals` (`opacity: 0`) = **`0`**.
- **`reducedMotion: "no-preference"`:** `--p` changed from `0.3` to `1.0` on scroll (`transitionDuration`: `0.35s, 0.35s` / `0.25s` / `0.6s, 0.6s`).
- **Keyboard:** `20/20` Tab stops at `1440x900` and `375x812` had visible focus indicators (`allVisibleFocus: true`). At `375x812`, mobile menu toggled `aria-expanded="true"`, closed on `Escape` (`aria-expanded="false"`), and returned focus to the menu button (`returnedFocus: true`).
