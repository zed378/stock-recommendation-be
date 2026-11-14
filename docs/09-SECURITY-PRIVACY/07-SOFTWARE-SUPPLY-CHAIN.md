# 07 — Software Supply Chain

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Security Engineer, DevOps Engineer |
| **Open items** | OQ-24 (resolved, ADR-030) |

A dependency that runs in the Trader runs next to an exchange key. The bar is higher than for the analysis
platform.

## Dependencies

| Rule | Detail |
|---|---|
| Minimal | Prefer the standard library and existing platform choices (`httpx`, SQLAlchemy, Alembic, `cryptography`). A new dependency needs a stated reason |
| Pinned | Exact versions with hashes in a lockfile for the Trader image |
| No unofficial Indodax SDKs | The connector is written against the official documentation. A third-party client library would hold the key and signing logic |
| No model runtimes in the Trader | No torch, no Hugging Face (ADR-001, `08-AI-AGENT/03`) |
| Review | Dependency changes are reviewed like code |
| Updates | Security updates applied on a schedule; each is tested against the mock exchange |

## Images

| Rule | Detail |
|---|---|
| Separate Dockerfile | `Dockerfile.trader`, minimal base, non-root, no test suite and no dev tools in the runtime image |
| **Visibility** | **Public during development, private before production (ADR-030).** While public, assume everything pushed is copied: no secret, no configuration value, no owner number, no real strategy parameter in the image. Move to a private repository before the first live-money stage (T5-06). The analysis images `zed378/aidss-api` and `zed378/aidss-frontend` were pushed as public at the owner's choice on 2026-11-14 |
| Tags | Immutable commit-based tags; `latest` is not used for deploys |
| Scan | Image vulnerability scan in CI; high findings block release |
| SBOM | Generated with each release and stored |
| Secrets | None baked in; a secret scan of the image layers |

## Source

| Rule | Detail |
|---|---|
| Branch protection | One task, one branch, one pull request; review before merge |
| Commit hygiene | No secrets, including Indodax's sample keys |
| Docs as untrusted input | Indodax's repository is cloned into an isolated directory and read as data; nothing from it is executed |
| Reproducible builds | The same commit builds the same image |

## Deploys

By immutable tag. The deployed Compose file builds the analysis services from source, so an `up --build`
on the host can silently replace an image; the Trader's service is defined by `image:` only, and a deploy
check verifies the running image digest matches the intended tag.

## Provenance of Documentation

Indodax details in `06-INTEGRATIONS/` cite the repository commit they were read from. A change to those
pages is a change to the contract and is reviewed.

## Tests (planned)

CI fails on a floating dependency version, on a secret in the repository or image, on a high-severity
finding, and on a Trader image that includes torch or the test suite.
