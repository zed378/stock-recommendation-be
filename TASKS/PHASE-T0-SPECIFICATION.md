# Phase T0 — Specification

| | |
|---|---|
| **Status** | 🔎 in review (2026-11-14), awaiting the owner |
| **Depends on** | none |
| **Exit criteria** | The owner has reviewed `docs/`, `MEMORY/DECISIONS.md`, and `TASKS/BACKLOG.md`; corrections are applied; open questions are accepted as the plan for what is not yet decided |

Records: `MEMORY/records/2026-11-14-trader-docs-scaffolding.md`.

---

### T0-01 — Design interview and ADRs

| | |
|---|---|
| **Status** | REVIEW |
| **Depends on** | none |
| **Spec refs** | `../MEMORY/DECISIONS.md` |
| **Spec required** | no |
| **Owner-led** | yes (the owner answered) |

**Definition of Done**
- [x] Six batches of multiple-choice questions answered
- [x] Answers recorded as ADR-001 to ADR-023 (`accepted`)
- [x] Author-derived decisions recorded as ADR-024 to ADR-027 (`proposed`)
- [ ] The owner confirms the `proposed` ADRs or replaces them

**Abuse cases**
- A `proposed` ADR treated as accepted. They are marked, and `BACKLOG.md` names which are safe to build on.

### T0-02 — The `docs/` tree

| | |
|---|---|
| **Status** | REVIEW |
| **Depends on** | T0-01 |
| **Spec refs** | `../trader-document-catalog.md` |
| **Spec required** | no |

**Definition of Done**
- [x] 13 categories, 104 files, in English
- [x] Every undecided number or choice points to an open question; none is invented
- [x] Indodax details cite the documentation commit and are marked "documented, not yet observed"
- [x] Documentation discrepancies listed (`06/11`)
- [ ] The owner has reviewed

**Abuse cases**
- Filling a "mirror" file with plausible content to look complete. Short files that say "not decided" are
  correct.

### T0-03 — `MEMORY/` and `TASKS/`

| | |
|---|---|
| **Status** | REVIEW |
| **Depends on** | T0-01 |
| **Spec refs** | reference conventions |
| **Spec required** | no |

**Definition of Done**
- [x] README, index, changelog, ADRs, templates, and a record
- [x] Task conventions, progress board, backlog with OQ-1 to OQ-26, phases T0 to T6

### T0-04 — `CLAUDE.md`, `AGENTS.md`, and the catalog

| | |
|---|---|
| **Status** | REVIEW |
| **Depends on** | T0-02 |
| **Spec refs** | `../CLAUDE.md`, `../AGENTS.md`, `../trader-document-catalog.md` |
| **Spec required** | no |

**Definition of Done**
- [x] Commands in `CLAUDE.md` taken from `README.md` and `pyproject.toml`
- [x] The Trader is described as **not built**
- [x] Non-negotiables and traps stated

### T0-05 — Archive the planning document

| | |
|---|---|
| **Status** | REVIEW |
| **Depends on** | T0-01 |
| **Spec refs** | ADR-018 |
| **Spec required** | no |

**Definition of Done**
- [x] `git mv` to `docs/archive/`
- [x] The one README reference updated; a note added that the "no execution" statement describes the analysis
      platform
- [ ] Verified that no source or test cites the file path (done: only `README.md` named it)

**Abuse cases**
- Editing 494 "Section N" comments to a new path. They cite section numbers, not the path; no change was
  needed.

### T0-06 — Owner fills the numbers worksheet

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T0-02 |
| **Spec refs** | `docs/01-PRODUCT-REQUIREMENTS/08-OWNER-NUMBERS-WORKSHEET.md` · `docs/03-DATA-MODEL/08-SETTINGS-REGISTRY.md` |
| **Spec required** | no |
| **Owner-led** | **yes** |

**Definition of Done**
- [ ] The owner fills as much of the worksheet as they are ready to; blanks stay blank
- [ ] The filled copy is recorded with its date in `MEMORY/records/`
- [ ] The matching open questions in `BACKLOG.md` are answered or left open on purpose
- [ ] The promotion thresholds (section H) are written **before** any evidence exists

**Abuse cases**
- An agent filling the worksheet "to be helpful". It must not; every value is the owner's.
