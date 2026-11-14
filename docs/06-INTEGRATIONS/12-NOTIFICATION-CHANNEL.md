# 12 — Notification Channel

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Integration Engineer |
| **Decided by** | ADR-016 |
| **Open items** | OQ-2 (resolved, ADR-031) |

## Decision State

Telegram, outbound only (ADR-031). WhatsApp is not planned. The notifier stays behind a small interface so a second
channel could be added later. Facts about Telegram's Bot API are **not yet researched in this repository** and
are verified in task T5-02 before it is built.

## Interface the Notifier Needs

| Need | Detail |
|---|---|
| Send a text message to one recipient | Plain text with a link to the UI |
| Delivery result | Success or failure, recorded |
| Authentication | A token held in the credential store (`02`) |
| Outbound only | The Trader sends; it does not accept commands through this channel |
| Rate limiting and retry | Retry `CRITICAL` with backoff |
| No sensitive content | Per `12-NOTIFICATIONS.md` and `09-SECURITY-PRIVACY/05` |

**The channel is never a control surface.** A message cannot approve, deny, or kill. Those happen only in the
authenticated UI or API. Otherwise a compromised chat account would control a trading system.

## To Verify for Telegram (T5-02; not yet researched here)

| Question | Why it matters |
|---|---|
| Can a service send to one person without that person messaging first? | The Trader must alert unprompted |
| Account and business-verification requirements and cost | Operational overhead |
| Message content retention and who can read it | Messages mention positions |
| Reliability and delivery confirmation | `CRITICAL` alerts must arrive |
| Behavior when the phone is offline or the app is muted | A muted alert is a missed alert |

## Operational Notes

- Whichever channel is chosen, an alert that fails to send must still be visible in the app (`02-ARCHITECTURE/06`).
- The channel token is a credential: encrypted, never logged, rotatable (`05/13` pattern).
- A second independent channel for `CRITICAL` only (for example email) is a possible later addition; the
  owner declined email in this round (ADR-016).

## Test Mode

Tests use a fake channel that records messages; no test sends a real message.
