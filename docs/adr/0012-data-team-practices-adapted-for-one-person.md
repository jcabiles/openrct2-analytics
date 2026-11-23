# ADR 0012: data-team practices, adapted for a one-person build

- Date: 2026-10-02
- Status: Accepted; amended by ADR 0016: 'wide views only for the site' reads as wide tables (`obt_`). Amended 2026-10-08: MetricFlow is approved (see the dated note under the MetricFlow rejection).

## Bottom line

The project runs the practices real data teams and consultancies use, each in
the lightest form that is still honest for one person directing AI agents on a
local DuckDB stack. None needs a cloud-only tool. Ceremonies shrink to a few
documents tied to real changes: one requirements brief, one v1 acceptance
walkthrough, release notes on each promotion to `main`, runbooks, and incident
records for real failures only. Metric definitions start as a standalone
catalog file, because dbt's metric validator crashes inside the agents'
sandbox. The evidence is in
`docs/ai-dlc/reports/data-team-practices--findings.md`.

## Context

The project must read as if a real data team or consultancy built it
(roadmap north star), but its plan was written without checking how such
teams work. Six research lanes and one local test on 2026-10-02 checked the
lifecycle and ceremonies, metric and model design, environments and data
quality, theme-park operators' own metrics, metric trees, and how hiring
reviewers judge solo, AI-assisted projects. The project owner's standing rule
for conflicts applies: real-world practice wins, and the showcase documents
the choice.

## Decision

| Area | Choice |
|---|---|
| Requirements | One brief, drafted by agents from the written rulings; the requirements workshop is one review session in which the project owner, as the company's sole decision-maker, confirms or corrects it. No invented stakeholders. |
| Design review | Spec and blind review before each build, as already practiced; a per-mart design note (process, grain, dimensions, facts) reviewed in the dbt design session. |
| Acceptance | One v1 walkthrough: scenarios from the brief and metric catalog, answered from the site alone, ending in a dated go/no-go note. |
| Releases | Each promotion of `develop` to `main` gets a tag and release notes; contracts stay versioned; after v1, breaking mart changes use dbt model versions with a deprecation note. |
| Looking back | One retrospective at v1; an incident record only for a real failure that reached a published number or broke a run. |
| Metric definitions | One governed definition per metric: name, plain definition, formula, grain, unit, clock, owner role, status, source model. A standalone catalog file in dbt 1.11's metric YAML shape, outside dbt's model folders. |
| Metric names | The industry's terms: guest visits, ride revenue (never admissions), revenue per visit by category, operating days, same-park year-over-year, operating profit. Closed months never appear as zero months. |
| Metric tree | Root: company operating profit. Every link is an identity (reconciled exactly by a dbt test) or a hypothesis (claim, lag, evidence, rival explanations, "observational"). Reviewed at each company year-end close. |
| Model design | Kimball bus matrix and four-step design, grain first; star schemas as the core, wide views only for the site. |
| Environments | One DuckDB file each for development, CI (built only from the committed sample) and production; rehearsal data in its own path and file. |
| CI/CD | A full `dbt build` on every pull request inside `make check`; production builds are local `make` runs; publishing uses write-audit-publish, to be tested. |
| Data quality | dbt unit tests for complex logic, data tests for keys and relationships, contracts on marts, reconciliation to game totals, stated severity; hand-built mutation tests. |
| Service levels | A short note per published table: owner, refresh trigger, currency (raw captures not yet built, and time since the last successful build), completeness and accuracy indicators, response steps. Required reconciliations block publication; only operational indicators get targets below 100%. |
| Observability | dbt run artifacts kept in a local run-history table; CI keeps its artifacts. |
| Presentation | A few linked process documents, simulated roles labeled, and a "How this was built" section disclosing AI agents' share with real examples of rejected agent output. |

## Rejected alternatives

- **Role-played stakeholder interviews and persona sign-offs.** Reviewers
  read simulated stakeholders presented as real as theater; one real
  decision-maker, labeled as such, is honest.
- **Slim CI (`state:modified+` with `--defer`).** The committed sample builds
  in minutes; a stale saved manifest would add a silent failure mode for no
  gain.
- **A self-hosted CI runner for production builds.** It would expose the
  project owner's machine to CI jobs; local `make` runs reach the same data.
- **Contractual SLAs, recurring retrospectives, a pull-request label
  taxonomy, a separate project board.** Each assumes a team or consumers the
  project does not have.
- **Elementary, Great Expectations, and MetricFlow now.** Each is a new
  dependency; dbt tests cover the checks, and MetricFlow stays the LATER bet
  until its sandbox crash has a fix.

  **Note (2026-10-08):** this no longer holds for MetricFlow. The project
  owner approved MetricFlow, the dbt semantic-layer tool, as roadmap item NEXT
  23. It runs after the dbt 1.12 upgrade (roadmap item NEXT 21), so the dbt
  upgrade comes first and MetricFlow follows. The sentence above is kept as
  the original decision; Elementary and Great Expectations stay rejected.

  **Note (2026-10-29):** MetricFlow no longer waits for the dbt 1.12 upgrade.
  The current `dbt-metricflow` release accepts dbt-core 1.11, and the
  2026-10-02 spike ran it beside the pinned dbt-core 1.11.15 with
  `mf validate-configs` passing (`docs/FINDINGS.md`). NEXT 23 can start on
  dbt 1.11; moving the catalog to the dbt 1.12 semantic YAML spec stays with
  NEXT 21. The 2026-10-08 note above is kept as the earlier ordering.

## Consequences

- The metric catalog (roadmap NEXT 13) can start; the dbt design session
  (NEXT 3·0) decides when the catalog moves into dbt and how agents' gate
  survives it.
- Two slices join the roadmap: a v1 acceptance walkthrough (NEXT 19) and
  operating documents (NEXT 20). Two checks wait on the project owner and are
  marked owner-later: confirming the requirements brief and running the
  acceptance walkthrough.
- **How we would know this is wrong:** the cold-read reader calls the process
  documents noise or the simulation unconvincing, or a governed metric cannot
  be defined without a cloud service. Either reopens this record.
