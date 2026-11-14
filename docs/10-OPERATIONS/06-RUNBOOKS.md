# 06 — Runbooks

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | DevOps Engineer, Risk Engineer |
| **Decided by** | ADR-007, ADR-010, ADR-022 |
| **Open items** | OQ-26 (decided, ADR-039) |

Written for the Owner, who is the only operator. Each is a procedure to follow while stressed, so each
starts with what to do **first**. Procedures are verified in drills before live use
(`12-DELIVERY-PLAN/05`). Until then they are drafts.

Manual steps on the exchange use the Indodax website or app. These documents do not describe Indodax's
screens because they were not reviewed here.

---

## R1 — The Trader is down and positions are open

**Why it matters:** no stop is monitored (ADR-007).

1. Treat it as urgent. Check whether any pair is moving sharply.
2. If you cannot restore the Trader quickly, **act at the exchange manually**: close or protect positions on
   the Indodax app or website. Do not wait for the Trader.
3. In parallel, check the host and container (`docker ps`, logs) and why it stopped.
4. When it restarts it will evaluate stops first and reconcile. Expect `HALTED` if anything differs.
5. Do not resume until you have read the reconciliation result.

## R2 — Using the kill switch

| Situation | Action |
|---|---|
| Something looks wrong but nothing is urgent | `HALT` |
| Orders may be wrong or duplicated | `CANCEL` |
| You must exit everything now | `FLATTEN` (confirmation required; it sells at market) |
| UI or API unreachable | The command-line kill tool on the host (`05/08`) |
| Trader itself unreachable | The Indodax app or website directly |

After any tier, check the step results, then reconcile. Resume only with a note and an understanding of why.

## R3 — Reconciliation difference

1. Read the difference kind and both values.
2. Check Indodax: was an order placed or cancelled outside the Trader? A deposit, a fee, a manual trade?
3. If an order you did not place exists, suspect the key: **go to R7**.
4. Record the cause. If the ledger is wrong, add an `ADJUSTMENT` with a reason. Never edit rows.
5. Reconcile again; resume only when clean.

## R4 — An order is `UNKNOWN`

1. The Trader is already querying by `clientOrderId`. Wait for its attempts.
2. If it is not found, **check Indodax yourself** (open orders, history). Do not assume.
3. Record the finding. Only you can confirm "not found". The pair stays held until you do.
4. Never re-send the order by hand from the Trader; there is no such control.

## R5 — Clock skew (`-1021`)

1. Check the host's time and NTP. Fix the clock.
2. The Trader halts until skew is within tolerance. Resume after reconciling.

## R6 — `-2015` Access denied

Possible causes: Trade API disabled, account locked, key permission changed, an IP rule, or a wrong key
version.

1. Check the key's permissions and status at Indodax.
2. Test the credential from the credential screen (read-only).
3. If the key was regenerated, store the new one. The Trader stays `DISABLED` meanwhile.

## R7 — Suspected key compromise

1. `CANCEL` (or `FLATTEN` if you judge it necessary).
2. **Revoke the key at Indodax immediately**, then generate a new TAPIv2 key (Read plus Trade only).
3. Review the order and trade history at Indodax for activity you did not make.
4. Rotate the master key if the host may be compromised (`09/02`).
5. Reconcile, record an incident (`07`), and resume only when satisfied.

## R8 — Exchange maintenance or a suspended pair

`-1016` or a maintenance flag suspends the pair automatically. Open positions on it cannot be sold until it
reopens; `FLATTEN` reports it. Decide whether to reduce exposure elsewhere.

## R9 — Restore from backup

`04-BACKUP-RESTORE-AND-RECOVERY.md`. Reconcile before resuming.

## R10 — Credential unreadable

The master key changed or is missing. The Trader stays `DISABLED`. Restore the key from its custody (OQ-17)
or re-enter the credential.

## R11 — Notification channel down

In-app alerts still exist. Check the app. Fix the channel token or provider issue.

## R12 — Breaker tripped

Read which limit and the values. Decide whether the cause is market behavior or a defect. Leave it halted
until you understand it; resume is explicit and needs a note.
