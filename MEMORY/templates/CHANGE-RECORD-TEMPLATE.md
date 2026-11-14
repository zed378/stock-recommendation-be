# <Task ID> — <Title>

**Date:** YYYY-MM-DD
**Task:** <ID from TASKS/, or "—" if this is not task work>
**Author:** <who>
**Spec refs:** <docs/ documents this implements>

---

## Hook

*One or two sentences that tell a future reader whether this is the record they need. Not a summary: the
surprising part.*

---

## What Changed

*Files, endpoints, schema, configuration. Enough for someone to find it. Not a diff; git has the diff.*

---

## Why

*The reasoning. If `docs/` already decided this, link to it and say nothing more. If `docs/` left it open,
this is where the decision goes, and it probably needs an ADR too.*

---

## Alternatives Considered

*What was rejected, and why. "None" is valid only when there genuinely was one obvious way.*

---

## What Surprised Me

*The part that cost the most time. A trap, a wrong assumption, an exchange behavior that did not match its
documentation.*

---

## Tests

*Name them. An assertion that something was tested is not evidence. State what ran against the mock and what
ran against the live exchange, if anything.*

- Unit:
- Integration:
- Connector contract (success / malformed / timeout / auth / clock skew / rate limit / rejection / window):
- Acceptance scenario(s):
- Guard tests:
- Live (read-only, owner-led), if any:

---

## Definition of Done

*Per `TASKS/00-TASK-CONVENTIONS.md`. Tick what passed. **Name what was waived and who agreed.***

- [ ] Code implements the spec
- [ ] Lint / typecheck pass
- [ ] Tests pass (named above)
- [ ] The analysis platform's architecture test passes unmodified
- [ ] No path skips the Risk Engine; no withdrawal code; no model text reaches an order
- [ ] Money is `Decimal`
- [ ] Uncertain states halt
- [ ] A control that limits loss has a test that fails when the control is removed
- [ ] No secret committed; credentials referenced, not literal
- [ ] Paper, backtest, and live are labelled correctly
- [ ] Documentation updated
- [ ] This record written

**Waived:** <which item, by whom, why, or "none">

---

## Security and Compliance

*Anything touching credentials, permissions, audit, redaction, or the exchange. If nothing, say "no
security-relevant change"; do not leave it blank.*

---

## What to Watch

*What might break because of this: a new polling interval, a rate-limit headroom, a fail-open default, a
limit that could be mis-set.*

---

## What Was Not Determined

*Stated plainly: an exchange behavior not observed live, a test that could not run, a number the owner has not
set.*

---

## Follow-Ups

*Add each to `TASKS/BACKLOG.md` so it has a consequence, and link it here.*

---

## Links

- ADR:
- Changelog:
- Backlog:
- Related records:
