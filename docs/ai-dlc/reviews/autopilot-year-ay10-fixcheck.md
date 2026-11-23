verdict: PASS
AY10R-1: closed — new full-run test with --ready "" asserts exit 0 and no ignored line; data test renamed, assertion unchanged; plant `is not None` in autopilot_report.py failed 10/10 (AssertionError).
AY10R-2: closed — skipped-backup test asserts exit 1, skip line, exact section 4 recovery text, kept folder; plant `if code == 0:` failed 10/10 (AssertionError).
AY10R-3: closed — ran company_managed_years on rebuilt planted rows: old plant gave {park-a:{2008}} and 17a; new plant gives park-b {2009} and park-a verdict ALLOWED, not 17a. Test stays skipped.
AY10R-4: closed — relative OPENRCT2_DATA_DIR full-run test; plant `if True:` at the landing chdir failed 10/10, as FileNotFoundError 'data/company/parquet.lock' (a runtime error from the plant, not an import error or assertion).
AY10R-5: closed — bytes comparison kept with a comment; verified newest_own_copy needs the park label (not known there). Missing dated copy gives exit 1, line naming the folder, no recovery steps, folder kept, archive copy asserted; plant (return 0) failed 10/10 (AssertionError).
AY10R-6: closed — spec diff is exactly one added sentence in the backup bullet; no other spec text changed.
AY10R-7: unchanged (rejected) — exit 130 text not in the diff.
AY10R-8: closed — registry re-check only in the land guard (the earlier call is gone); text identical (_failed_checks, "Company data was not touched; the run folder is kept at"); test turns the park practice after the lock is taken, expects exit 1, folder kept, nothing landed; plant (drop `or unregistered`) failed 10/10 (AssertionError).
Other checks: weakening checker 0 failing (2 exempt) vs ae29e56 with the approvals file, 0 failing vs b650b6b; diff touches only the 10 owned files; autopilot_year.py 443 lines, all files under 500; no duplicate of the moved report code remains; the five named test files: 103 passed, 1 skipped (real game).
New findings: none.
Notes: (1) a registry problem and run problems no longer print together; a run with both shows only the run problems (the spec lists registry under the same checks) - non-blocking. (2) My first pytest run created ignored __pycache__ files in the worktree; git status is clean.
