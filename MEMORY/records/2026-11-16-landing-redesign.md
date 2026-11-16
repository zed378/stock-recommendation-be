# 2026-11-16 — Landing page redesign (`/`)

Requested by the owner with two Dribbble references. Repository only: **not built into an image and not deployed**.

## Audit of the page it replaces (committed by the owner in `b4169b9`)

- Dark, low-chroma, Inter declared but never loaded (the app's `--font-sans` names Inter; no font file ships), mono uppercase micro-labels, a card-in-card hero,
  a row of four stat cards, and tabs. It showed **specimen numbers on real tickers** (BBCA close 9,850, "BUY 74%", a Kronos band), labelled as specimen.
- Claims it made that the repository does not support: "IDR spot execution" and a spot-crypto "oversight cockpit" next to the equity analysis, "mandatory counter-evidence on every decision card"
  (the code only gives a list with no conflicting factor a balance score of 0), a 5-day Kronos horizon (not in the code), and "13 indicators" listed with ten names.

## What the product is (from README, `RecommendationResponse`, `calibration.py`, `domain/types.py`, `CLAUDE.md`)

Decision support for IDX equities; no execution engine, broker adapter, order endpoint or order table, enforced by `tests/test_architecture_constraints.py`; the stance vocabulary
(`strong_buy, buy, watchlist, hold, reduce, sell`) has no order verb by design. A card holds a stance, a deterministic calibrated confidence beside the model's own, three factor lists, two scenarios,
support/resistance, target and stop with methods, a horizon, and the prompt version and model. Five layers: market data, 13 indicators, an optional Kronos-base forecast, a bull/bear debate with a risk
committee, calibration. The separate AIDSS Trader (Indodax, crypto) is built but has never been connected to an exchange and starts HALTED.

## Direction (decisions and reasons)

- Design Read: a landing for an Indonesian-stock decision-support tool, for individual and semi-professional investors, Indonesian first; research-print editorial; ENERGY 3 / RHYTHM 3 / MOTION 2.
- **Headline**: "Rekomendasi saham yang menyertakan bukti sebaliknya" ("Stock recommendations that include the evidence against them"), because the calibrated confidence rewards a list that argues against itself.
- **Surfaces**: the app's own ink for the hero and the working sections, warm paper for the two sections that are read. Each of the five sections has its own composition (asymmetric hero, annotated card with a text column,
  sticky stack beside five steps, a typographic ledger, an index list), so the alternation is not the only variation.
- **Accent**: one teal (the app's rise colour); no indigo or violet (the logo mark keeps its own gradient, which is the owner's brand).
- **Type**: Newsreader (display cut, optical size fixed at 72) for headings, since the output is a research note; Inter for interface. Both self-hosted, latin subset, 168 KB in three files (`public/fonts/README.md`); only the two roman faces are preloaded, and only from this page.
  Registered as `AIDSS Display` / `AIDSS Sans`, so no other screen changes typeface.
- **3D**: CSS 3D, no WebGL and no library. The five planes are flat drawings, so a 3D engine (Three.js is several hundred KB and a GPU cost on phones) would add weight without adding anything. The planes are translucent so the
  drawings beneath show through; there is no blur (R-10). Scroll pulls the planes apart (`--p`), the pointer tilts the scene on devices with a fine pointer, and beside the five steps the plane of the step in view comes forward.
  No loop anywhere; under `prefers-reduced-motion` nothing moves and the page shows one resting state.
- **No figures**: the drawings have no axis, scale, number or ticker. The only numbers on the page are facts about the product (13 indicators; the 1, 7, 14 and 30 day horizons) and the year. A test enforces it.
- Not used: the three JPEGs in `public/landing/` (stock-style imagery the owner added); the page is drawn. They are left in place.

## Verified (local browser, API stubbed to 401, no production call)

- Overflow: document width equals the viewport at 1280, 1024, 768, 375, 320 px in both languages. The hero's headline was clipping at 320 px in English ("recommendations"); fixed with a smaller floor and re-measured.
- Scroll: `--p` goes 0.3 to 1.0 over the first 40% of the hero; the highlighted plane follows steps 1 to 5. Reduced motion: `--p` stays 0.62 after scrolling, transitions about 0, content visible.
- Keyboard: first Tab stop is the skip link; focusing a part of the card lights its field(s), 2px focus ring; the phone menu opens and Escape closes it; every anchor has a target; every internal route linked exists.
- At 375 px no control in the header, main or footer is under 44px. No em dash. No console error, page error or failed request in any run.
- Contrast, computed with the project's checker: muted text on ink 7.86:1, accent on ink 8.88:1, ink on the accent button 6.41:1, text on paper 14.44:1, muted on paper 6.14:1, accent on paper 5.11:1.
- Checks: `tsc` 5.9.3 and `oxlint` clean; Vitest 93 passed with `--pool=vmThreads` (the landing test went from 2 tests to 10); build 0.6 s; main JS 248.9 kB to 225.5 kB (the old page was heavier).

## Follow-up, same day: the hero at 1920px (owner's screenshot)

The first QA stopped at 1536px. At 1920px in English the headline ("recommendations", 105px) ran under the 3D stack, the caption sat far from the drawing, and the hero was taller than needed.
Fixed in `Landing.tsx`: the headline is capped at 4.3rem (`clamp(2.75rem,5vw,4.3rem)`) with `lg:pr-12`, the stack is vertically centred against it (`lg:self-center`, aspect 5/4) and its caption pulled up.
Measured as the distance between the right end of the headline text and the left edge of the leftmost plane, at 1024, 1280, 1440, 1680, 1920 and 2560px in both languages: 65 to 147px, never negative; overflow 0.
An attempt to cap the size with an arbitrary `min-[1500px]` variant did not take effect in the dev build (computed size stayed 78.4px); the cap went into the `clamp` instead.
Lesson recorded here: the page is now checked up to 2560px, not 1536px.

## Not verified / limits

- **Not seen on a real device, and the references were not seen at all**: the two Dribbble shots are images and this session cannot view them, so the "study" of them rests on the owner's written description of their traits. The result is
  not compared with them.
- Not measured: LCP, INP, CLS or any Lighthouse score (no field data). The LCP element is the headline text; fonts use `font-display: swap`.
- Not run in production or on iOS Safari; `perspective` and `preserve-3d` were exercised only in Chromium.
- Hover on the stack is for pointer devices only; touch users get the scroll and step behaviour.
- The hero stack's "pull apart" is partly out of view by the time it completes, because the hero fills the first screen; it is a gesture more than a reveal.
- Side finding, not touched: the app's `rec.label.*` strings have `strong_sell` but no `reduce`, while the backend enum has `reduce` and no `strong_sell`, so a "reduce" recommendation would show a raw key on the asset page.
