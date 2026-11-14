# 02 — Credentials and Authentication

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Security Engineer |
| **Decided by** | ADR-013, ADR-014 |
| **Open items** | OQ-3, OQ-17 (custody decided, ADR-029) |

## Credentials the Trader Holds

| Credential | For | Stored |
|---|---|---|
| Indodax TAPIv2 key and secret (Read plus Trade) | Private endpoints | Encrypted in `trading.credential` (`05/13`) |
| Notification channel token | Mobile alerts | Encrypted, same mechanism (ADR-031) |
| Analysis platform service credential | Context reads | Encrypted, same mechanism, post-MVP (ADR-032) |
| Master key | Decrypting the above | A **file secret** on the host, mounted read-only into the container. The environment holds only its path, `AIDSS_TRADER_MASTER_KEY_FILE` (ADR-029) |
| Database password for `trader_rw` | The Trader's DB role | Container environment |

None of these is ever in source, documentation, a fixture, a log, an API response, or a commit message.

## Indodax Key Requirements

- Generated at `https://indodax.com/trade_api` as a **dedicated TAPIv2 key**; an old key cannot be reused.
- Permissions: **Reading** and **Spot Trading** only. **Not** IDR and Crypto Withdrawal.
- Because Withdrawal is not selected, **IP Permission is not available** and the key works from any IP
  (ADR-013). This is the principal residual risk of the credential, treated in
  `09-SECURITY-PRIVACY/00-THREAT-MODEL.md`.

## Verification of the Key at Runtime

At start and at each reconciliation: `GET /api/v2/account` must show `canTrade` true, `canWithdraw` false,
and `canWithdrawFiat` false. Otherwise the Trader refuses to trade (FR-T04).

## Unresolved: Compatibility With Legacy-Auth Features (OQ-3)

The Deadman Switch (`/countdownCancelAll`) and the Private WebSocket token request are documented with the
**legacy** scheme (`Key` header, HMAC-SHA512, `tapi_key`). TAPIv2 states a TAPIv2 key cannot be an older
key. Whether a TAPIv2 key authenticates those two features is not stated anywhere. It can only be learned
by trying with a real key, read-only first, with the owner's instruction. Until then both are treated as
unavailable (ADR-007, ADR-011).

## Signing

See `04-INDODAX-AUTH-AND-SIGNING.md`. Signing happens inside the connector. The decrypted secret exists
only for the duration of computing one signature and is never placed in a log, an exception message, or a
stored raw response.

## Rotation

`05-MODULE-SPECIFICATIONS/13-CREDENTIAL-ADMINISTRATION.md`. Rotation tests the new key read-only before
swapping, and the owner revokes the old key at Indodax.

## Sample Keys in Indodax Documentation

Indodax's pages include example API keys and secrets for illustration. They are not real, and they are
**never copied** into this repository, a fixture, or a test, because a placeholder that looks like a real
key invites a real one to be pasted next to it, and secret scanners flag it.
