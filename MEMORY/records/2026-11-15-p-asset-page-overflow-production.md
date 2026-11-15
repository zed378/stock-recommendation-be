# Task P: Production Overflow Measurement on `/assets/:ticker` (`dd2d776`) & Follow-up Mobile Fixes (`0f28c83`)

**Date:** 2026-11-15  
**Target:** `https://aidss.zedth.my.id` (`zed378/aidss-frontend:dd2d776`, chunks `index-B1brQ7pV.js` + `AssetDetail-u7eMYfpv.js`)  
**Fix commit:** `0f28c83` (built & unit-tested locally; **not** built/pushed/deployed to VM)

---

## 1. Production Measurement on `dd2d776` (Playwright Chromium, Read-Only)

1. **Chunks confirmed:** `200 index-B1brQ7pV.js`, `200 AssetDetail-u7eMYfpv.js`.
2. **`/assets/BBCA` across widths (`en` & `id`):**
   - `375`, `360`, `320`, `768`, `1280`: `overflowPx: 0` on initial tab (`Chart`/`Grafik`).
   - **All 6 tabs at `375px` (`en` & `id`):** `overflowPx: 0` on every tab (`Chart`/`Grafik`, `Indicators`/`Indikator`, `Fundamentals`/`Fundamental`, `Analysis`/`Analisis`, `Strategy`/`Strategi`, `News`/`Berita`).
   - **All 6 tabs at `320px`:** `0` overflow on 5 of 6 tabs in both `en` and `id`, and `0` on `Analysis` (`en`), **but `overflowPx: 17` (`scrollWidth: 337`) on `Analisis` (`id`) at `320px`**:
     - Culprit: `<div className="flex items-center gap-2">` (`width: 321`, `left: 16`, `right: 337`) in `AssetDetail.tsx` (`runButton`: `Standard` / `TradingAgents Debate` select + `Jalankan analisis` button) lacked `flex-wrap`.
3. **`TabStrip` behaviour on `/assets/BBCA`:**
   - At `375px`: `clientWidth: 343`, `scrollWidth: 507`, all 6 tab buttons `46px` tall (`>= 44px`). Clicking `News` scrolled `scrollLeft` to `164` (`News` rect `left: 298..359` inside `nav` `16..359`, `aria-current="page"` = `"News"`); clicking `Chart` returned `scrollLeft` to `0`.
   - At `1280px`: `clientWidth: 1024`, `scrollWidth: 1024` (no scroll), all 6 tab buttons `38px` tall.
   - Keyboard (`375px`): `Tab` 5 times from `Chart` reached `News` (`scrolledIntoView: true`, `outlineStyle: auto`, `outlineWidth: 1px`), and `Enter` activated `aria-current="page"` = `"News"`.
   - Screenshots (`tabstrip_375_chart.png`, `tabstrip_375_news.png` in `%TEMP%\aidss-pw-verify\out-stage7\`): active bottom border is clearly visible and `"Analysis"` is clipped at the right edge on `Chart` to signal scrollability.
4. **Comparison 375px check across 7 signed-in routes:**
   - `/watchlist`, `/portfolio`, `/journal`, `/monitoring`, `/trader`, `/admin`: `overflowPx: 0`.
   - **`/picks` (`StockPicks.tsx`):** `overflowPx: 5` (`scrollWidth: 380` on `375px` viewport). Culprit: `SECTION.rounded-lg.border.border-line.bg-raised` (`width: 364`, `left: 16`, `right: 380`) inside `<div className="grid gap-3 lg:grid-cols-2 lg:items-start">` which omitted `grid-cols-1` (implicit `auto` track below `lg` instead of `minmax(0, 1fr)`).
5. **Non-overflow finding (left untouched per prompt):** `1d / 1w / 1M` timeframe buttons on `/assets/BBCA` remain ~28px tall (`< 44px`).

---

## 2. Fixes & Local Verification (`0f28c83`)

- `frontend/src/pages/AssetDetail.tsx`: added `flex-wrap` to `runButton` (`flex flex-wrap items-center gap-2`).
- `frontend/src/pages/StockPicks.tsx`: added `grid-cols-1` to the picks grid (`grid grid-cols-1 gap-3 lg:grid-cols-2 lg:items-start`).
- `frontend/src/pages/__tests__/MobileOverflowGuards.test.tsx`: 2 Vitest tests pinning both classes.
- **Checks after edit (`0f28c83`):**
  - `.\node_modules\.bin\tsc.cmd -b --noEmit`: clean (0 errors).
  - `npx.cmd oxlint .`: `0 warnings and 0 errors` (89 files).
  - `npx.cmd vitest run --pool=vmThreads`: `11 passed (11)`, `80 passed (80)`.
  - `npm.cmd run build`: succeeded (`645ms`, main `index-Bnemom8D.js`, `AssetDetail-DYrC46ri.js`, `StockPicks-DxQ7mxql.js`).
  - `.venv\Scripts\ruff.exe check src tests alembic_trader deploy`: `All checks passed!`.
  - `.venv\Scripts\python.exe -m pytest tests/trader tests/test_architecture_constraints.py tests/test_frontend_routing.py -q`: `512 passed, 7 deselected`, **1 pre-existing failure** (`test_s13_the_lock_still_satisfies_pyproject`: `email-validator is in pyproject.toml but not in the lock`, unrelated to frontend changes).
- **Not verified:** live browser re-test of `0f28c83` (requires frontend image rebuild and deploy by the primary agent).
