# ADR 0001: Standardize new Python repos on this template

- Date: 2026-08-25
- Status: Accepted

## Context

Each new Python project was being scaffolded from scratch or by copying an
existing project, which propagated that project's accumulated flaws
(inconsistent lint config, missing gates, ad-hoc dependency lists, no ADR or
findings log). There was no single source of truth for what a new repo
should look like on day one.

## Decision

All new Python service repos are cloned from the project owner's private
`template-python-service` template repository instead of being scaffolded by
hand or copied from a prior project. The template fixes, up front: the
`ruff`/`mypy`/`pytest` toolchain and config, a `Makefile` gate (`make
check`) that must pass before work is declared done, a `pre-commit` hook
set, a GitHub Actions CI workflow, and the three durable doc homes (`docs/adr/`,
`ARCHITECTURE.md`, `docs/FINDINGS.md`).

## Consequences

- New repos start with a working gate and CI on day one instead of
  accumulating one ad hoc.
- Template changes (e.g. a ruff rule bump) do not retroactively apply to
  already-cloned repos; each repo owns its own copy after cloning.
- Contributors must learn one config surface instead of a different one per
  repo, which lowers onboarding cost but requires template changes to be
  reviewed carefully since they set precedent for every future clone.
