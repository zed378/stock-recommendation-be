# 00 — UX Principles

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer (frontend) |
| **Open items** | OQ-14 (resolved, ADR-028) |

The operator surface exists to **approve, observe, and stop**. It is not a trading terminal.

## Principles

1. **State first.** The first thing on every screen is the Trader's state: running, halted, or disabled; the
   mode of each strategy; whether data is fresh. A halted Trader must never look like a quiet one.
2. **Nothing looks live that is not.** Paper and backtest figures carry a persistent `PAPER` or `BACKTEST`
   label on the figure itself, not only in a page heading. They are never added to live figures.
3. **Freshness is visible.** Every price, balance, position, and PnL shows its source and age. Stale data is
   visibly stale, not silently shown.
4. **Destructive actions are deliberate.** `CANCEL` and `FLATTEN` need a confirmation that restates what will
   happen ("close 3 positions with market orders"). `FLATTEN` requires typing the word. `HALT` is one
   confirmed click, because stopping should be easy.
5. **The kill switch is always reachable.** On every page, in the same place, including when other panels
   have failed to load.
6. **Explain a refusal.** A rejected intent shows the limit that rejected it and the numbers. A disabled
   strategy says which setting is missing.
7. **No dark patterns.** No countdown pressure on approvals beyond the real expiry, no celebratory states on
   a profit, no red/green alone to carry meaning.
8. **The UI is never the control.** Permissions and limits are enforced by the Trader API; hiding a button
   is a convenience, not a guard.
9. **Mobile is a first-class case for three tasks:** see state, approve or deny, press the kill switch.
10. **Existing conventions.** The operator screens reuse the platform's frontend stack, i18n mechanism, and
    accessibility baseline (React, Vite, `openapi-typescript` types). User-facing strings go through the
    existing i18n.

## Language

Operator UI text follows the platform's i18n (English and Indonesian). Documentation is English
(ADR-017). Amounts are shown in IDR with the pair's own precision; the UI never rounds a quantity in a way
that differs from what will be sent.

## Accessibility

Meets the platform baseline: keyboard operable, visible focus, contrast, meaning not carried by color alone,
form errors announced. The kill switch and approval controls are reachable by keyboard and have clear
accessible names.

## Antislop Note

For UI, copy, and layout work, the project owner's `antislop` skills apply: no decorative metrics, no
unexplained badges, copy that says what the control does.
