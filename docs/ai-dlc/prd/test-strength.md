# Test strength: finding and fixing bugs the tests miss — idea document

status: approved (project owner, 2026-11-02) as NEXT 33, after the v1 showcase release

## Bottom line

- **The problem.** The Python tests pass, but some small bugs planted in the code still pass them too.
  A 2026-11-02 sample of three safety-critical files found that the tests caught 183 of 230
  planted bugs (80%). The other 44 are places where the code could quietly break and `make check`
  would stay green.
- **The tool.** mutmut (mutation testing) makes many small edits to the code, one at a time: it flips a
  condition, swaps a string, or returns a different value. It then runs the tests against each edit. An
  edit the tests catch is "killed"; one they miss "survived". Each survivor is a candidate gap in the tests.
- **The fix.** Triage every survivor in the risk-ranked files below. Each one either gets a test that
  catches it, or is recorded as harmless with a reason. The tests never get weaker to raise the score.
- **When.** After the v1 showcase ships (roadmap NEXT 33). It changes tests only, not product behaviour.

## 1. What was measured

- **Sample:** `src/openrct2_analytics/state.py`, `ingest/lock.py` and `ingest/publish_rollback.py`, 268
  lines in all. They were chosen because a wrong change there loses or corrupts data.
- **Run:** mutmut 3.8.1 on a throwaway copy of commit `79542d2`, with the 17 test files that
  import the three files; the `docs/FINDINGS.md` row of 2026-11-02 has the method and numbers.
- **Result:** 230 planted bugs; 183 caught, 44 missed, 3 unclear (a test
  run that was slower or flakier than normal).
- **A first run that used only five test files reported 182 of 230 caught (79%).** Adding the other
  12 related test files caught only one more, so the gaps are real, not an artifact of the selection.
  Before triage, still include every test file that imports the target files.

## 2. What to look for

Each survivor falls into one of four kinds. Triage in this order.

### 2.1 Real gaps: fix these first

- **An untested branch.** Example: `state.state_dir()` reads `XDG_DATA_HOME` and `LOCALAPPDATA`
  when `OPENRCT2_STATE_DIR` is unset, but every test sets `OPENRCT2_STATE_DIR`, so those two lines
  can be deleted and no test fails.
- **A flipped decision.** Example: making `state._inside()` end with `return True` instead of
  `return False` survives. `_inside()` decides whether the state folder sits inside the data or
  warehouse folders, which the go-live safety check depends on.
- **Signal handlers never checked.** Making `lock.set_signal_handlers()` skip every handler
  (`if number is None` in place of `is not None`) survives, so no test confirms that Ctrl-C or a
  stop signal is actually caught.
- **A dropped type check.** Example: `state.is_live()` still passes its tests when it treats any
  marker file content as a dictionary, so no test feeds it a marker whose JSON is not an object.
- **A file name that is a contract.** Example: the go-live marker names in `state.marker_paths()`
  can change without a failing test, yet old markers on disk use those exact names.

### 2.2 Harmless on this machine, real elsewhere

- **Case-only path changes** (for example `"warehouse"` to `"WAREHOUSE"`) survive because macOS
  disks ignore letter case by default. On a Linux CI runner they would fail.
- **What to do:** mark them `harmless on case-insensitive disks` and rely on CI; do not write a
  test that only checks spelling.

### 2.3 Message text: usually ignore

- **A changed error or status message** (for example `FileExistsError("company already has a
  go-live marker")` to `FileExistsError(None)`) survives when no test reads the message.
- **What to do:** add a check only when the text is something a person or a script relies on,
  such as the `unknown (invalid marker)` value that `state.is_live()` returns to
  `ingest/delete_data.py`. Otherwise mark it `message text only`.

### 2.4 Equivalent changes: record and move on

- **A change that cannot alter behaviour for any real input** is called an equivalent mutant.
  Prove it by reading the code before using this label; for example, `continue` to `break` in
  `state._inside()` is equivalent only if at most one existing ancestor can ever match.
- **What to do:** record it with the reason; never add a test to "kill" it.

## 3. How to run it

1. **Approval first.** mutmut is a new dev dependency, so adding it to `pyproject.toml` and
   `uv.lock` needs the project owner's sign-off (`docs/CONVENTIONS.md`, "No new dependency without
   approval"). Until then, run it from a throwaway copy:
   `git archive HEAD | tar -x -C <scratch>/copy`, then `uv sync` and
   `uv pip install mutmut==3.8.1` there.
2. **Configure it in `pyproject.toml`** (in the copy, or in the repo once approved). All three
   settings below are needed, or every run fails with `BadTestExecutionCommandsException`:

   ```toml
   [tool.mutmut]
   source_paths = ["src"]
   do_not_mutate = ["<every src file outside this round's target files>"]
   also_copy = ["data", "scripts", "contracts", "docs", "models", "macros", "metrics", "plugin",
                "site", "dbt_project.yml", "profiles.yml", "packages.yml", "package.json",
                "Makefile", "README.md", "ARCHITECTURE.md", "CHANGELOG.md", "CLAUDE.md",
                ".github", ".sqlfluff", ".secrets.baseline"]
   ```

   - `source_paths` must be the whole `src` folder. Naming single files copies only those files
     into mutmut's work folder, so every other import fails.
   - `do_not_mutate` is how a round is limited to its target files.
   - `also_copy` brings the sample data, scripts and docs that tests read by path.
   - Add `pytest_add_cli_args_test_selection` with every test file that imports the round's target
     files (find them with `grep -l`). The full suite took 23 minutes in one pass on 2026-11-02,
     and mutmut runs it once for its baseline plus parts of it for every planted bug.
   - Leave out tests that need a git checkout or a built plugin; 15 of 2,055 tests failed in
     mutmut's folder for that reason on 2026-11-02 (for example
     `test_bench_run_refusals.py::test_the_work_folder_is_ignored_by_git`).
3. **Run** `.venv/bin/mutmut run`, then `.venv/bin/mutmut results` for the survivors, and
   `.venv/bin/mutmut show <name>` for one survivor's edit.
4. **Re-check one survivor** after adding its test with `.venv/bin/mutmut run "<name>"`.
5. **Never run `mutmut apply`** in a real checkout; it writes the planted bug into the source.

## 4. How to size it

- **Planted bugs per line:** about 0.86 (230 from 268 lines).
- **The whole package:** `src/` holds 58 files and about 12,800 lines, so about 11,000 planted
  bugs. Never run it all at once against the full suite; run it round by round with a test
  selection. Round 1's run time is in `docs/FINDINGS.md`; scale later rounds from it.
- **Triage time:** about 2 to 5 minutes of agent time per survivor to classify it, and about 10
  to 20 minutes per new test (guesses; record the real figures from round 1 in `docs/FINDINGS.md`).
- **Rounds, in risk order.** One round is one pull request.
  1. The three sampled files above (this document's survivors).
  2. Data deletion, go-live and publishing: `ingest/delete_*.py`, `ingest/go_live.py` and
     `ingest/publish*.py`.
  3. Ingest and contract checks: the rest of `ingest/`.
  4. Everything else, only if rounds 1 to 3 found real gaps at a rate worth continuing (more than
     about one real gap per 50 planted bugs).
- **Stop rule.** A round is done when every survivor in its files is killed or recorded under one
  of the kinds in section 2. A score target is not the goal.

## 5. How to fix a survivor

1. **Read the edit** with `mutmut show <name>` and decide its kind (section 2).
2. **For a real gap, write the test that a careful reviewer would want anyway:** it states the
   behaviour in its name and checks the outcome a user would see, such as the folder chosen, the
   error raised, or the file left on disk.
3. **Prove the test catches the bug:** it fails with the survivor in place (`mutmut run "<name>"`
   reports it killed) and passes on the real code (`make check`).
4. **Record the rest** in a table in the round's pull request: survivor name, kind, one-line reason.
5. **Never** loosen another test, add `# pragma: no mutate`, or add the file to `do_not_mutate`
   to hide a survivor; review treats those as weakening the gate.

## 6. What this does not cover

- **dbt models and SQL.** Planted-mismatch tests for the reconciliation identities are a separate
  v1.1 item ("Check: planted-mismatch tests for the reconciliation identities").
- **The TypeScript plugin.** A JavaScript mutation tool (such as StrykerJS) would be its own spike.
- **Making mutmut part of `make check`.** That decision waits until round 1's run time is known.
