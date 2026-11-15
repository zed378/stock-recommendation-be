# 2026-11-15 — Task K: Live Browser Re-Verification (Nginx Fix, Sidebar, and Landing Page)

## Scope

- Target: `https://aidss.zedth.my.id` (`zed378/aidss-frontend:75bc905`).
- Tool: Playwright Chromium v1255 in `%TEMP%\aidss-pw-verify\stage4_verify.mjs`; screenshots and `stage4_report.json` saved outside the repo in `%TEMP%\aidss-pw-verify\out-stage4\`.
- Read-only checks only; no form submissions, no mutations, no new accounts.

## Observed Results

1. **Direct `page.goto` + `page.reload` on all 7 Trader routes**:
   - `/trader`, `/trader/approvals`, `/trader/strategies`, `/trader/parameters`, `/trader/paper`, `/trader/credentials`, `/trader/limits`.
   - All 7 returned HTTP `200`, `content-type: text/html`, `httpDowngrade: false`, visible `<h1>`, `HALTED` and `PAPER` badges, `0` console errors, `0` page errors, `0` failed requests.
2. **Collapsible sidebar (`Sidebar.tsx`, `Layout.tsx`)**:
   - All 6 nav groups expose `aria-expanded` and `aria-controls="nav-group-..."`.
   - Collapsing `RESEARCH` persisted `{"nav.group.research":true}` in `localStorage` (`aidss.nav.collapsed`) across `page.reload()`.
   - Collapsing `TRADING` on `/watchlist` and navigating to `/trader/limits` auto-expanded `TRADING` (`aria-expanded: "false"` -> `"true"`).
   - Sidebar visibility toggle (`button[aria-controls="app-sidebar"]`, `"Hide menu"` / `"Open menu"`) persisted `aidss.nav.sidebar = "hidden"` across `page.reload()`.
3. **Landing page (`/`, unauthenticated)**:
   - Widths `1280`, `768`, `375`: `overflowPx: 0` at all three widths.
   - Images (`/logo-symbol.svg`, `/landing/hero-jakarta-skyline.jpg`, `/landing/quant-desk-editorial.jpg`, `/landing/exchange-architecture.jpg`): all `complete: true` with `naturalWidth > 0`.
   - ID/EN toggle: switched `aidss.locale` (`en` <-> `id`) and `<h1>` text.
   - Keyboard focus (`Tab`): `outlineStyle: solid`, `outlineWidth: 2px`.
   - Contrast sample: `body` `rgb(11, 15, 20)`, `h1` `rgb(230, 237, 243)`, paragraph `rgb(38, 166, 154)`.
   - `0` console errors, `0` page errors, `0` failed requests.
4. **Security headers & outage simulation**:
   - Unauthenticated `GET /trader/v1/status`: `401` with `cache-control: no-store`, `content-security-policy: default-src 'none'; frame-ancestors 'none'`, `referrer-policy: no-referrer`, `x-content-type-options: nosniff`, `x-frame-options: DENY`.
   - Simulated `502` on `**/trader/v1/**`: `/trader/limits` rendered `"Could not load (UNAVAILABLE) — The Trader is having a problem."` cleanly.

## What Was Not Determined

- Interactive modals (opening and cancelling step-up dialogs) were not exercised in this pass; no defects were found requiring frontend edits.
