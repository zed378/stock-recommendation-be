# Task T: Frontend Cleanup (Unused Landing JPEGs & `rec.label.reduce`)

**Date:** 2026-11-16
**Task:** T (Stage 10)

## Changes

1. **Removed unused landing JPEGs (`git rm`, total 713,149 bytes):**
   - `frontend/public/landing/exchange-architecture.jpg` (266,888 bytes)
   - `frontend/public/landing/hero-jakarta-skyline.jpg` (377,846 bytes)
   - `frontend/public/landing/quant-desk-editorial.jpg` (68,415 bytes)
   - Verified zero references across source, HTML, nginx, docs, tests, and `frontend/dist/` after `npm run build`. `frontend/public/fonts/README.md` does not mention them.

2. **Added missing `rec.label.reduce` i18n key:**
   - Traced `rec.label.${label}` in `frontend/src/components/Recommendation.tsx` and `frontend/src/components/Strategy.tsx` against `RecommendationLabel` in `src/aidss/domain/types.py` (`strong_buy`, `buy`, `watchlist`, `hold`, `reduce`, `sell`).
   - Added `"rec.label.reduce": "Kurangi"` (`id`) and `"rec.label.reduce": "Reduce"` (`en`) in `frontend/src/i18n/messages.ts` (no em dash).
   - Added `frontend/src/components/__tests__/RecommendationLabels.test.ts` verifying every backend `RecommendationLabel` value resolves to a non-empty, non-raw-key label in both `id` and `en`.

## Verification

- `frontend/`: `./node_modules/.bin/tsc.cmd -b --noEmit` (0 errors), `npx oxlint .` (0 warnings, 0 errors), `npx vitest run --pool=vmThreads` (**13 test files, 94 passed**), `npm run build` (`built in 1.15s`, `frontend/dist` grep empty).
- Backend: `.venv\Scripts\ruff.exe check src tests alembic_trader deploy` (`All checks passed!`), `.venv\Scripts\python.exe -m pytest tests/trader tests/test_architecture_constraints.py tests/test_frontend_routing.py -q` (**518 passed, 7 deselected**).

## Note

Frontend changes require rebuilding and deploying `aidss-frontend` by the main agent to take effect in production.
