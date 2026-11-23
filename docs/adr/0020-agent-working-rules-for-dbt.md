# ADR 0020: agent working rules for dbt — safe commands, enforced patterns, AI output never gates a build

- Date: 2026-10-07
- Status: Accepted, provisional until the project owner's review (verify: owner-later). The evidence is emerging
  practice; see "Revisit point".

## Bottom line

AI coding agents write most of this dbt project, so they work under four rules. They run only a short list of
safe dbt commands, never against a published warehouse file. A tested gate check turns the most important dbt
rules into failures (money read outside staging, `select *` from a source, any dbt package). AI output is
always a proposal that `make check` and a reviewer judge; it never passes or fails a build itself. Whether
agents follow the rules is measured by a fixed task suite graded without AI judgment. The dbt MCP server (a tool
server that lets agents call dbt directly), dbt Labs' agent skills and a question-answering evaluation set for
the future chat wait for the governed-metrics bet. These rules rest on emerging practice and are revisited when
the agent suite's first results land.

## Context

The project owner asked for the dbt part of the repo to be AI-first. The research report
(`docs/ai-dlc/reports/dbt-practices--findings.md`, the "report" below; section 14) separates two questions:
whether an AI can answer business questions correctly, which is the governed-metrics bet, and whether AI agents
can safely build and change this project, which is how most of it is written. On the second, the report found a
clear direction but no measurement: keep agent instructions short, list safe commands, turn rules into
deterministic checks, and measure agents on fixed tasks with known answers. No source measures which
instructions improve change safety (report, section 16, Gaps). Hosted dbt agents need the paid platform, and AI
judgments that pass or fail a build are not trustworthy yet.

The project owner ruled on 2026-10-06 that these agent rules get their own record, separate from the modeling
record ADR 0019 (`docs/adr/0019-dbt-practices.md`), labeled as emerging practice with a revisit point (report,
section 19, D12). This record holds D10, D11, D16, D17 and the rule that AI output never passes or fails a build.
Roadmap names: NEXT 3a is the staging slice, 3c and 3d the marts and their trust tests; R7 is the coding-agent
evaluation suite added by the report (NEXT 25). "DP-n" is a row of the report's adoption matrix
(`docs/ai-dlc/reports/dbt-practices--findings.md`, section 18).

## Decision

### 1. Agent-safe dbt commands

`.claude/rules/dbt.md` gains a section of about 20 lines, built in NEXT 3a, that lists what an agent may run
(D16; DP-93; report, section 14):

- `dbt parse`, which writes `target/manifest.json` for inspection, and `dbt ls --select <selector> --output json`.
- A selected build against the development file or a scratch copy of a DuckDB file.
- Never a command against a published warehouse file; never an edit to raw captures (`CLAUDE.md` "Never break"
  2); never a change that weakens or removes a test to make a build pass.

No root `AGENTS.md` is added; `CLAUDE.md` and the rule files stay the only agent instructions (DP-101).

Gain: one short, auditable list that every agent loads with the dbt rules. Cost: about 20 lines to keep true;
agent tools that do not read `.claude/rules/` do not see it. The list is a synthesis with no primary dbt source
(report, section 14; weak).

### 2. The forbidden-pattern gate check

A tested script in `make check`, built in NEXT 3a, fails on (D16; DP-94):

- a `_tenths` column read outside `models/staging/` (`CLAUDE.md` "Never break" 3);
- `select *` from a `source()`; `select * from final` and other CTE selects stay legal;
- any `packages.yml`, until the project owner approves a package (ADR 0019, section 10).

Gain: three rules that agents could break silently become gate failures. Cost: a small script and its tests.

### 3. AI output never passes or fails a build

Documentation or tests an AI drafts are proposals; `make check` validates them and a reviewer reads them before
they merge. No automated AI review step runs in CI, and no AI-written model or column description merges
unreviewed (DP-99, DP-56; report, section 14). The repo's independent reviewers stay advisory: their findings are
adjudicated, never folded in automatically.

Gain: no AI judgment replaces the deterministic gate, which must be green on the pull request head before any merge
(agents may merge after a reviewer passes, `CLAUDE.md`, so a reviewer's pass alone is not the guarantee); one LLM code-review study found inaccurate approvals in up to 44.4% of
cases (report, section 14; background only, dated before the report's evidence window). Cost: slower
documentation, and review time for every AI draft.

### 4. The dbt MCP server and dbt Labs' agent skills: deferred

Both wait for the governed-metrics bet (D11; DP-53, DP-54, DP-96, DP-97; report, section 14). When that bet is
promoted, the local server (`uvx dbt-mcp`) needs the project owner's dependency approval and runs with the
settings the report confirmed:

- allowlist mode, through `DBT_MCP_ENABLE_DBT_CLI` and `DBT_MCP_ENABLE_TOOLS`, with the CLI tools only;
- `DBT_CLI_TIMEOUT` raised above its 60-second default, because a full rebuild may take longer;
- a scratch copy of the DuckDB file, because DuckDB has no read-only roles and the server's "read-only mode" is
  unconfirmed in scope.

dbt Labs' agent skills (Apache 2.0) are read, and the useful parts are copied into `.claude/rules/dbt.md`; the
collection is never installed, because parts of it contradict `docs/CONVENTIONS.md` (incremental models,
packages).

Gain: typed dbt tools and vendor patterns when there is a consumer for them, without an unapproved dependency
now. Cost: agents keep calling dbt through the shell until then; reading the skills takes review time.

### 5. The coding-agent evaluation suite (R7)

Roadmap item R7, after NEXT 3c and 3d, measures whether a change to agent instructions or to the model in use
helps (D17; DP-98; report, section 14):

- Tasks come from the acceptance scenarios; traps come from the mutation tests (do not weaken a test, notice a
  missing tenths conversion, refuse an out-of-scope request).
- A run passes when `make check` is green, only the expected files changed, no forbidden pattern appears, and
  the result values equal the expected ones on the committed sample. No AI grades a run.
- Each task runs three times; the pass rate per model and per instruction version goes into a run log that the
  chat's evaluation set can reuse. The project owner reviews the first results.

Gain: rule and model changes are measured instead of assumed. Cost: a few days to build, plus model spend per
run, which is not yet measured; agents are not deterministic, so one run proves nothing.

### 6. The chat evaluation set: deferred

The set of verified questions for the future chat is built inside the governed-metrics bet once MetricFlow
exists (D10; DP-51): a small DuckDB table of question, expected metric call, expected value and sample, plus
refusal cases, scored by exact match and logged in R7's run log. The chat answers only through metric calls,
never free SQL (DP-52).

Gain: a regression test for the chat from its first day. Cost: a few hours to build and the upkeep of expected
values.

## Revisit point

The evidence behind sections 1, 2 and 5 is emerging practice (weak to moderate in the report's confidence
marks). This record is revisited when R7's first results land, or when the governed-metrics bet is promoted,
whichever comes first. A pass rate that does not improve when the rules change is a reason to cut rules, not to
add them.

## Rejected alternatives

- **A root `AGENTS.md`** (DP-101). A second instruction file drifts from `CLAUDE.md`.
- **Installing dbt-agent-skills wholesale** (DP-96). An unapproved dependency whose advice contradicts the repo's
  conventions.
- **An automated AI review step in CI** (DP-99). A false approval is worse than a false alarm.
- **dbt-llm-evals for scoring** (DP-70). It needs warehouse AI functions and does not run on DuckDB.
- **Hosted dbt agents, dbt Copilot, dbt Wizard and the remote MCP server** (DP-55). They need the paid platform;
  ADR 0019, section 12, names what the repo shows instead.

## Consequences

- NEXT 3a builds the safe-commands section in `.claude/rules/dbt.md` and the forbidden-pattern gate check.
- R7 is written on the roadmap and not yet built; the governed-metrics bet carries the MCP settings, the skills
  rule and the chat evaluation set.
- **How we would know this is wrong:** an agent change that breaks a rule passes the gate; R7 shows the rules do
  not change pass rates; or a primary source measures which agent instructions help. Any of these reopens this
  record.
