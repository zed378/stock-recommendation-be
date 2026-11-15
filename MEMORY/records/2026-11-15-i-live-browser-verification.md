# 2026-11-15 — Task I: Live Browser Verification on `https://aidss.zedth.my.id`

## Scope and Setup

- Target: `https://aidss.zedth.my.id` (deployed images `zed378/aidss-frontend:e410ab7`, `zed378/aidss-trader:e410ab7`).
- Tool: Playwright Chromium v1255 installed outside the repo in `%TEMP%\aidss-pw-verify`.
- Account: `test@mail.com` (verified `role: "admin"` via `GET /api/auth/me` with `localStorage.getItem("aidss.token")`).
- Evidence artifacts (screenshots + `full_report.json`) saved outside the repository in `%TEMP%\aidss-pw-verify\out\`.

## Observed Results

1. **Unauthenticated Security Headers (`GET /trader/v1/status`)**:
   - Status: `401`
   - `cache-control`: `no-store, no-store`
   - `content-security-policy`: `default-src 'none'; frame-ancestors 'none'`
   - `referrer-policy`: `no-referrer`
   - `x-content-type-options`: `nosniff`
   - `x-frame-options`: `DENY`
2. **Direct URL / Refresh Routing Defect (`page.goto`)**:
   - `GET https://aidss.zedth.my.id/trader` redirected to `http://aidss.zedth.my.id/trader/` and returned `404` `application/json` (`{"detail":"Not Found"}`).
   - `GET https://aidss.zedth.my.id/trader/approvals` returned `404` `application/json` (`{"detail":"Not Found"}`).
   - Cause: the VM reverse proxy routes `/trader*` to `aidss-trader` FastAPI instead of scoping backend proxy rules to `/trader/v1/*` and `/trader/health`, preventing the React SPA `index.html` from serving direct URLs or browser refreshes under `/trader*`.
3. **All 7 Trader Pages via SPA Navigation**:
   - `/trader` (`Trader`), `/trader/approvals` (`Approval queue`), `/trader/strategies` (`Strategies and modes`), `/trader/parameters` (`Strategy parameters`), `/trader/paper` (`Paper simulation assumptions`), `/trader/credentials` (`Credentials`), `/trader/limits` (`Risk limits and allowlist`).
   - Every page rendered its `<h1>`, displayed `HALTED` and `PAPER`, had `0` console errors, `0` page errors, `0` failed requests, and `0` leaked secret patterns in `/trader/v1/` responses.
4. **Responsive Layout (`1280`, `768`, `375` px)**:
   - `scrollWidth === innerWidth` (`overflowPx: 0`) at all three widths on `/trader`.
5. **ID/EN Locale Toggle & Keyboard Focus**:
   - Locale button toggled `aidss.locale` from `en` to `id` and switched navigation labels to Indonesian (`RISET`, `Persetujuan`, `Strategi & mode`, `Batas risiko`, etc.).
   - `Tab` navigation focused `<a>` with `outlineStyle: auto`, `outlineWidth: 1px`.
6. **Simulated Trader Outage (`502` on `/trader/v1/**`)**:
   - Navigating to `/trader/limits` under `page.route('**/trader/v1/**', 502)` rendered without a white-screen crash (`notBlank: true`).

## What Was Not Determined

- Sidebar collapse toggle selector (`button[aria-label*="sidebar" i]`, etc.) did not match on `/trader` during the automated check; manual/selector inspection of the sidebar collapse button was not re-run.
- Reverse-proxy configuration on `10.1.200.13` was not inspected directly (awaits SSH access).
