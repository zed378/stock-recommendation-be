# 2026-11-15 — Phone tap targets, part 2: the header and the ticker links

Follows `2026-11-15-phone-tap-targets.md` and Task Q's production measurement, which found what the shared-component change had not reached:
the header (on every page) and the inline ticker links on `/picks`. Repository only: **not built or deployed**.

## Measured before (375px, local browser, mocked API; Task Q's production numbers agree)

Header: menu button 30x30, brand link 69x20, bell 32x28, `ID` 28x24, `EN` 32x24, `Sign out` 67x24, `All controls` 79x24 (the `HALT` button was already 44 tall).
`/picks`: 12 ticker links in the mock, 31x20 and 35x24 (55 in Task Q's production data).

## Changes (all below the `sm` breakpoint; nothing applies from `sm` up)

- `Layout.tsx`: menu button `max-sm:size-11 max-sm:shrink-0`; brand link `max-sm:min-h-11`; `ID`/`EN` buttons `max-sm:min-h-11 max-sm:min-w-11`; `Sign out`
  `max-sm:min-h-11 max-sm:whitespace-nowrap`; row padding `py-3` to `py-1.5` and gaps `gap-3` to `gap-1` on phones, so the sticky header does not grow;
  the brand text is hidden under 23rem (368px) so the larger controls still fit at 360 and 320px.
- `Notifications.tsx`: bell `max-sm:min-h-11 max-sm:min-w-11`, centred, and the unread badge moved in (`max-sm:right-1 max-sm:top-1`) so it stays next to the glyph.
- `StateBar.tsx`: the `All controls` link `max-sm:min-h-11`.
- Ticker links: new `tickerLinkHitArea` in `primitives.tsx` (`max-sm:-mx-2 max-sm:-my-3 max-sm:px-2 max-sm:py-3`), used by `StockPicks.tsx` and `MarketScan.tsx`.
  Padding grows the link; the equal negative margin gives the space back.

## Measured after

- Header at 375, 360 and 320px: every control 44px tall (menu 44x44, bell 44x44, `id`/`en` 44x44, `Sign out` 67x44, `All controls` 79x44, `HALT` 53x44); no
  `Sign out` wrap; document width equals the viewport on `/watchlist`, `/portfolio`, `/journal`, `/monitoring`, `/picks`, `/admin` at 375 and on `/picks`, `/monitoring` at 320.
  Header height 184px to 188px (+4px, from the taller `All controls` link). At 1280px the header controls are unchanged.
- `/picks` ticker links at 375: 47x44 and 51x48; page height (2344) and every card and row height identical before and after (compared with `git stash`); at 1280 still 31x20.
- `tsc` 5.9.3 and `oxlint` clean; Vitest 85 passed with `--pool=vmThreads` (3 new); build 0.7 s.

## Not verified / left alone

- Not run in production; the API was mocked. The brand text disappearing under 368px is a visible change on small phones (the menu button and the drawer still lead home).
- Tablets between 640px and 1023px keep the compact header controls; `max-sm` only covers phones. The menu button is shown up to `lg`, so on a tablet it is still 30x30.
- Not changed: Admin's period buttons and `Filter entity`, the native 13px checkboxes (Monitoring, StockPicks, Users), and other hand-made small controls (`Strategy.tsx`, `TranslateToggle.tsx`,
  `MultiSelect.tsx`, `components/admin/*`).
- The sticky header plus the Trader state bar takes 188px of a phone screen. That was already so (184px), is by design (the HALT control must stay on screen), and was not reduced.
