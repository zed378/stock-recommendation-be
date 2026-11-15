# Task R: Production Header & Ticker-Link Tap-Target Measurement (`db57068`)

**Date:** 2026-11-15  
**Target:** `https://aidss.zedth.my.id` (`zed378/aidss-frontend:db57068`)  
**Scope:** Read-only Playwright Chromium verification; zero code changes made.

---

## 1. Version & Chunks

- Main chunk: `200 index-BR0mddld.js`
- On `/picks`: `primitives-DAGn815L.js`, `StockPicks-ClbpKwXA.js`, `MarketScan-rr0IDVPM.js`, `MultiSelect-BoE7iL62.js`, `mutations-BG00ANMl.js` (all HTTP 200).

---

## 2. Header at `375`, `360`, `320` px

- **`/watchlist` (`en` & `id`):**
  - `under44Count: 0` at `375`, `360`, and `320` px in both `en` and `id`:
    - `Open menu` / `Buka menu`: `44×44`
    - `AIDSS` brand link (`375px` only): `69×44` (visible at `375px` with logo + `"AIDSS"`, hidden at `360px` and `320px` via `max-[23rem]:hidden`)
    - `Open notifications` / `Buka notifikasi`: `44×44`
    - `ID`: `44×44`; `EN`: `44×44`
    - `Sign out`: `67×44` (1 visual line); `Keluar`: `56×44` (1 visual line)
    - `All controls`: `79×44` (`Kontrol lengkap`: `105×44`)
    - `HALT`: `53×44`
  - `overflowPx: 0` at `375`, `360`, and `320` px (`en` & `id`).
  - `haltAllOverlap: false` across all tested widths/routes.
  - Header height: `192px` (`en` at `375/360/320`, `id` at `375/360`), `212px` (`id` at `320` where the Indonesian `Halted` message wraps onto 3 lines).
- **`/picks`, `/monitoring`, `/assets/BBCA`, `/trader`, `/admin` (`375` & `320` px, `en`):** `under44Count: 0`, `overflowPx: 0`, `haltAllOverlap: false` on every route.

---

## 3. Bell, Notification Panel, & Mobile Drawer (`375px`)

- **Bell (`150..194`) vs `ID` (`199..243`):** no unread notifications (`unreadBadgePresent: false`) on the test account; opening the bell panel kept `panelOverflowPx: 0`, closed cleanly via `Escape`.
- **Drawer menu:** menu button (`16..60`, `44×44`) and bell (`150..194`, `44×44`) have `90px` separation (`overlap: false`); drawer opens on click and closes cleanly via `Escape` and outside backdrop click.

---

## 4. Ticker Links (`375px`)

- **`/picks`:** `55` `a[href^="/assets/"]` links, `under44Count: 0`, sample sizes `47×44`, `gapPx: 110` between adjacent MarketScan rows (`overlapRects: false`, midpoint element `SPAN`), `scrollHeight: 17899`, first card heights `[3685, 447, 427, 427]`; clicking `AREA` navigated to `/assets/AREA`.
- **`/monitoring` (Whole exchange tab):** `25` `a[href^="/assets/"]` links, `under44Count: 0`, sample sizes `47×44`, `gapPx: 110` (`overlapRects: false`).

---

## 5. Desktop (`1280px`) & Tablet (`768px`)

- **Desktop `1280px`:** header height `96px`; bell `32×28`, `ID` `28×24`, `EN` `32×24`, `Sign out` `67×24`, `All controls` `79×24`, `HALT` `53×26`; `/picks` sample ticker links `31×20` — unchanged.
- **Tablet `768px` (recorded as-is for owner decision):** header height `98px`, `overflowPx: 0`, compact controls kept (`Open menu` `30×30`, `AIDSS` `69×20`, bell `32×28`, `ID` `28×24`, `EN` `32×24`, `Sign out` `67×24`, `All controls` `79×24`, `HALT` `53×26`).
- **Screenshots (`%TEMP%\aidss-pw-verify\out-stage9\`):** `header_375_en.png`, `header_375_id.png`, `header_320_en.png`, `header_320_id.png`, `picks_card_375.png` — no clipped or overlapping text.
