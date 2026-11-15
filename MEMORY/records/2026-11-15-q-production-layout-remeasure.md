# Task Q: Production Overflow & Tap-Target Re-measurement (`2fc6c0b`)

**Date:** 2026-11-15  
**Target:** `https://aidss.zedth.my.id` (`zed378/aidss-frontend:2fc6c0b`)  
**Scope:** Read-only Playwright Chromium verification; zero code changes made.

---

## 1. Version & Chunk Verification

- Main chunk: `200 index-HvlgnJp2.js`
- Route chunks observed (HTTP 200): `primitives-CpTPs67F.js`, `Watchlist-pU6X2YRY.js`, `Portfolio-DNCbbkam.js`, `Journal-DFp8rkzM.js`, `StockPicks-CyBa0p3U.js`, `MarketScan-BOAwSuRI.js`, `MultiSelect-Dctewbpp.js`, `Monitoring-CFlTyQIG.js`, `TabStrip-qKVUDWzp.js`, `Trader-UQDXmXZr.js`, `components-6B__uajv.js`, `Admin-DSC8ADZD.js`, `CronPicker-BIfiIhG-.js`, `AssetDetail-DsVQA76H.js`, `charts-BfLdQ4qD.js`.

---

## 2. Document Overflow (`en` & `id`)

- **Previously failing routes:**
  - `/assets/BBCA` tab `Analisis` (`id`) at `320px`: **`overflowPx: 0`** (`clientWidth: 320`, `scrollWidth: 320`; was `17px` in `dd2d776`).
  - `/picks` at `375px` (`en` & `id`): **`overflowPx: 0`** (`clientWidth: 375`, `scrollWidth: 375`; was `5px` in `dd2d776`).
- **Widths `360`, `375`, `768`, `1280` on `/assets/BBCA` and `/picks` (`en` & `id`):** `overflowPx: 0` across all widths.
- **Widths `375` and `320` across all 8 routes & all 6 `/assets/BBCA` tabs (`en` & `id`):**
  - `/watchlist`, `/portfolio`, `/journal`, `/picks`, `/monitoring`, `/trader`, `/admin`, and all 6 tabs of `/assets/BBCA` (`Chart`/`Grafik`, `Indicators`/`Indikator`, `Fundamentals`/`Fundamental`, `Analysis`/`Analisis`, `Strategy`/`Strategi`, `News`/`Berita`): **`overflowPx: 0`** everywhere.

---

## 3. Control Sizes at `375px` & `1280px` (`en`)

- **Desktop `1280px` (`/assets/BBCA`):** `1d` (`33×24`), `1w` (`33×24`), `1M` (`33×24`), `Fetch price data` (`138×38`), `TabStrip` tabs (`38px` high) — unchanged.
- **Phone `375px` inside `<main>` (controls with `w < 44 || h < 44`):**
  - `/watchlist`: `0`
  - `/portfolio`: `0` (matches primary agent's `0`)
  - `/journal`: `0` (matches primary agent's `0`)
  - `/monitoring`: `1` (`input[type="checkbox"]` `13×13` — matches primary agent's `1`)
  - `/trader`: `0`
  - `/assets/BBCA`: `1` (TradingView attribution `<a>` `35×19` — matches primary agent's `1`)
  - `/picks`: `57` total (`2` native `13×13` checkboxes matching primary agent's `2`, plus `55` inline ticker `<a>` links `31×20` / `35×24` in `MarketScan.tsx` & `StockPicks.tsx`)
  - `/admin`: `3` (`1 days` `60×24`, `7 days` `60×24`, `30 days` `66×24` in `Admin.tsx`)
  - `/admin/users`: `4` (`h-3.5 w-3.5` `14×14` checkboxes in `components/admin/Users.tsx`)
  - `/admin/audit`: `1` (`Filter entity` input `191×26` in `Admin.tsx`)
  - `modal_create_user` (`+ Create account` dialog), `notifications_panel`, `sidebar_mobile` (`#app-sidebar`): `0`
  - `header` (`Layout.tsx`, `Notifications.tsx`, `TranslateToggle.tsx`): `7` (`Open menu` `30×30`, `AIDSS` `69×20`, `Open notifications` `32×28`, `ID` `28×24`, `EN` `32×24`, `Sign out` `67×24`, `All controls` `79×24`)

---

## 4. Phone Density & `Monitoring` `TabStrip` (`375px`)

- Screenshots (`asset_bbca_375.png`, `picks_375.png`, `monitoring_watchlist_375.png`, `monitoring_global_375.png` in `%TEMP%\aidss-pw-verify\out-stage8\`): no text clipping, no overlapping rows; `Monitoring` `Alerts` toolbar wraps cleanly onto two rows.
- `Monitoring` `TabStrip`: `clientWidth: 309`, `scrollWidth: 309` (`fitsWithoutScroll: true`), both tabs `46px` tall; clicking `Whole exchange` and `My watchlist` switches `aria-current="page"`, and keyboard `Tab` + `Enter` activates `Whole exchange`.
