// The counts under "By the numbers", with the date and commit they were taken at and the exact
// commands that produce each one. They are counted by hand with these commands and pasted here;
// a rerun on a later commit means editing this file. Commands run from the repository root.
export const BUILT_COUNTS = {
  asOf: "2026-11-22",
  commit: "573a52f4",
  rows: [
    {
      label: "merged pull requests",
      count: 180,
      // Squash subjects ending "(#N)" plus merge commits "Merge pull request #N", one per N.
      command:
        "git log 573a52f4 --format=%s | grep -oE '\\(#[0-9]+\\)$|^Merge pull request #[0-9]+' | grep -oE '[0-9]+' | sort -un | wc -l",
    },
    {
      label: "review findings recorded",
      count: 2487,
      // A finding row is a row of a table in a review ledger whose header starts with an ID cell
      // and has a Severity cell; the header and separator rows are not counted.
      command:
        "awk -F'|' 'tolower($2)~/^ *id *$/ && tolower($0)~/severity/ {t=1; next} /^\\|/ && t && $2 !~ /^[ :-]+$/ {n++} !/^\\|/ {t=0} END{print n}' docs/ai-dlc/ledger/*.md",
    },
    {
      label: "Python tests",
      count: 4124,
      command: ".venv/bin/python -m pytest --collect-only -q | tail -1",
    },
    {
      label: "plugin tests",
      count: 190,
      command: "npm run --silent plugin:build && node --test plugin/test/*.test.mjs | grep '^ℹ tests'",
    },
  ],
};
