# 03 — Loading, Empty, Error, and Stale States

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer (frontend) |

Every panel has these states in addition to success. The distinction between them is the point: **"no data",
"no response", and "old data" are different facts**, and in a trading UI confusing them is dangerous.

| State | Meaning | Shown as |
|---|---|---|
| **Loading** | A request is in flight | A placeholder that does not look like a zero value |
| **Empty** | The system answered and there is nothing (no open orders) | An explicit "No open orders", with the time it was checked |
| **Unavailable** | The Trader API or its source did not answer | "Could not load", the cause class (network, auth, server), and a retry. Never a blank or a zero |
| **Stale** | Data exists but is older than the freshness limit | The value is shown greyed, with its age. It is not shown as current |
| **Degraded** | A dependency is impaired (connector breaker open, feed stale) | A banner naming the dependency and what the Trader is doing about it (no new entries, still watching exits) |
| **Unauthorized** | The user lacks the permission | The control is absent or disabled, with the reason |
| **Halted** | Trading stopped | A persistent banner with the reason, time, and the resume rule |
| **Disabled** | A required setting or credential is missing | A banner naming the missing item and linking to where to set it |
| **Paper / Backtest** | Figures are not real fills | A persistent label on each figure and block |

## Rules

- A missing value is **never rendered as zero**. An unset limit is "unset", an unavailable balance is
  "unavailable".
- Errors from the Trader show the normalized error class and a correlation id, not a raw stack trace or an
  exchange payload.
- On a lost connection the page shows how long since the last update. It does not continue to display the
  last value as live.
- A mutation (approve, promote, kill, save limit) shows pending, success, and failure states and never
  optimistically assumes success; the UI reflects the state the Trader reports.
- Confirm dialogs for destructive actions work with the keyboard and are announced to assistive technology.
