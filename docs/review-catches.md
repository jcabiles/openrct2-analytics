# Defects caught before merge

Independent review and the `make check` gate caught real defects in agent-written work before it reached `develop`. Five are recorded here. Each one names what was wrong, what it would have cost, how it was caught, and the fix. Read them as evidence that the review step earns its cost, not as a complete list.

This public repository starts from a single snapshot of the project's private development history, so the commits and pull requests named below are not in its history. Each case names the fixing commit's subject and the pull request number as they were recorded there.

## 1. A convert run could delete the company's raw captures

**What was wrong.** `landing_dirs` in `src/openrct2_analytics/config.py` refused two landing folders only when they resolved to the identical folder. A folder nested inside another data set's folder, or a link one level down (the `v1` child), passed. With such a layout, `convert --data-set rehearsal` removed files that belonged to the company data set. That breaks the rule that raw captures are append-only.

**How it was caught.** A whole-branch review that tried to break the new data-set separation by building the nested layout. The existing tests only covered the identical-folder case, so the gate was green.

**The fix.** `landing_dirs` now compares all four folders and each existing `v1` child pairwise and refuses any pair that is equal or nested. New tests build the nested and `v1` alias layouts and run the real `convert`; they fail on the old code.

- Fixing commit: "Refuse landing folders that nest inside another data set's folder", merged in pull request #49 of the private history.

## 2. A test that could not fail

**What was wrong.** The publish audit counts rows in every model before a warehouse file is published. The test for models outside the `main` schema only checked the passing case. An audit that silently skipped every non-`main` model would have passed the whole test file, so a published file with an empty table in such a model could have gone out unnoticed.

**How it was caught.** A review of the test file, which saw that no test made a non-`main` model fail the audit.

**The fix.** A new test, run against the publish tests' stand-in warehouse (not real dbt), empties a non-`main` model's table (`DELETE FROM reporting.fct_reporting`) and expects the audit to fail with reason `empty`, naming that model. An audit that skipped non-`main` models would now fail this test.

- Fixing commit: "Prove the publish audit counts rows in models outside the main schema", merged in pull request #49 of the private history.

## 3. The park registry named a park the rebuilt sample no longer held

**What was wrong.** `seeds/park_registry.csv` listed the old sample park. The rebuilt rehearsal sample holds a different park, so a rehearsal publish over the sample would have failed the `unregistered-park` check. No test tied the committed sample to the registry, so nothing had flagged the mismatch.

**How it was caught.** A review of the whole branch, which read the registry against the rebuilt sample.

**The fix.** The registry now lists the rebuilt sample's park, and a new test in `tests/test_sample.py` fails when any park in the committed sample is missing from the registry as a rehearsal park.

- Fixing commit: "Register the rebuilt sample's park for rehearsal publishes", merged in pull request #51 of the private history.

## 4. Test data with a hole in its sequence numbers

**What was wrong.** The shared contract test data in `tests/test_contracts.py` numbered its five guest events from `seq` 30, leaving `seq` 9 to 29 missing. The data looked fine until the branch met the publish flow, whose new sequence audit runs before the contract check. `test_main_reports_contract_failure` then failed with the audit's error instead of the contract error it was written to show. Real data with that gap would be rejected, because every session's `seq` must have no gaps.

**How it was caught.** The `make check` test step, when the branch was combined with the publish flow.

**The fix.** The guest events now follow the save at `seq` 9 to 13, so the session runs 1 to 13 with no gap.

- Fixing commit: "Number the fixture's guest events without a seq gap so publish's seq audit passes", merged in pull request #51 of the private history.

## 5. An assertion was loosened in place and the script missed it

**What was wrong.** While the autopilot run-and-land change was built, the test for a later run with an empty `READY` value was loosened in place. It no longer checked that the "READY was ignored" line is absent, and no full-run test used an empty value. A change that printed the line for an empty value would have passed. The case is realistic, because a make target that always passes `--ready "$(READY)"` sends an empty string.

**How it was caught.** An independent review of the change. The test-weakening checker flagged the moved and removed assertions, and the review judged those; it noted that the checker cannot see an assertion loosened in place. The reviewer then planted the break `if cleared.ready_ignored is not None:` in `autopilot_year.py`, and the four stand-in test files stayed green, so the gap was real. The review ledger records it as a blocker (row AY10R-1 of [the autopilot-year review ledger](ai-dlc/ledger/autopilot-year.md)); the full review is in [the review report](ai-dlc/reviews/autopilot-year-ay10-review.md).

**The fix.** A full run with `--ready ""` on a later run now asserts exit 0 and no "READY was ignored" line, and the old data test was renamed so that it no longer claims the line. A separate fix check re-ran the planted break and recorded that the new test failed on it in all ten runs ([the fix-check report](ai-dlc/reviews/autopilot-year-ay10-fixcheck.md)).

- Fixing commit: "fix: close autopilot run-and-land review gaps", merged in pull request #142 of the private history.
