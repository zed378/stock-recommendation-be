# Feature Spec — <Task ID> <Title>

**Written:** YYYY-MM-DD, **before** implementation
**Task:** <ID>
**Author:** <who>
**Spec refs:** <docs/ documents this implements>

> Save to `MEMORY/specs/<task-id>-<slug>.md`.
>
> Required for any task marked `Spec required`. Written **before** code: its purpose is to surface
> decisions and traps while they are still cheap.

---

## Problem

*What is not possible today, and for whom (the Owner, an agent, an operator).*

---

## What `docs/` Already Decides

| Decision | Source |
|---|---|
| | |

**If `docs/` is silent, contradictory, or wrong about something you need: stop and say so here.** That is a
specification gap: it belongs in `TASKS/BACKLOG.md` and likely needs an ADR before any code.

---

## Open Numbers

*Every limit, threshold, interval, or amount this task touches. For each: is it owner-set (and set), or
open? An open number is not defaulted here; the task is `BLOCKED` or implements the mechanism only.*

| Number | Owner-set? | Open question |
|---|---|---|
| | | |

---

## Data Model

- [ ] New tables or columns, and their privileges (`trader_rw` may do what?).
- [ ] Append-only where it should be.
- [ ] `origin` on every row; `Decimal` money.
- [ ] Idempotency key.
- [ ] Retention.

---

## API (operator or exchange)

| Method | Path | Permission | Purpose |
|---|---|---|---|

- [ ] Every route has a permission.
- [ ] No route creates an order directly; none touches withdrawal.
- [ ] Idempotency-Key on mutations; audit on every mutation.

---

## Exchange Interaction (if any)

- [ ] Endpoint and fields taken from the official documentation (commit cited); marked "not yet verified
      against the live exchange" if so.
- [ ] Retry class (safe, verify-then-act, never blind).
- [ ] Failure behavior: unknown outcome for a write is resolved by query.
- [ ] Rate-limit scope and throttle.
- [ ] Mock behavior added.

---

## Risk and Safety

- [ ] Which limit or guard does this interact with?
- [ ] What happens on uncertainty? (It must halt.)
- [ ] A test that fails when the control is removed.
- [ ] Can this path skip the Risk Engine? (It must not.)
- [ ] Can model output reach an order here? (It must not.)

---

## Security

- [ ] Secrets referenced, never literal; nothing logged.
- [ ] Redaction in logs, responses, notifications.
- [ ] Any new outbound destination (egress allowlist)?

---

## Tests

*Name them, before writing them.*

- Unit:
- Connector contract:
- Integration:
- Acceptance:
- Negative authorization:
- Guard:

---

## Open Questions

*Anything needing an owner decision. Raise before coding, not after.*

---

## Rollout

- [ ] Deployable without a coordinated cutover?
- [ ] Rollback, and what happens to open positions during it?
- [ ] Behind a setting, disabled by default if it touches orders?
