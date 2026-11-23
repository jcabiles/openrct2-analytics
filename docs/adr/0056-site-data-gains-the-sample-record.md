# ADR 0056: site data gains the sample record

- Date: 2026-11-20
- Status: Accepted; supersedes the file count of ADR 0045 (ADR 0057 amended that count to seven) and decision 3 of ADR 0044

## Bottom line

`site/_data/` serves eight files: the seven allowlisted exports and `sample.json`, a one-row record of the sample behind the page (`data_set`, `parks`, `sessions`, `player_played`). The page prints its sample statement from that record, and `make site-company` refuses a company build whose record repeats the committed one. This replaces a hand-written sentence that described only the committed sample.

## Context

The page stated its sample in a fixed sentence, so a company build still said "three headless sessions with no player". The repo rule is that analyses state their sample, and a sentence written by hand cannot follow the data. ADR 0045 fixed the served set at six files and ADR 0057 raised it to seven; neither has a place for a record that is not a copy of a mart.

## Decision

1. **`showcase.export` writes and checks `sample.json` beside the allowlisted files.** It is a fixed query in the export module, not an allowlist entry, so `site/exports.toml` does not change. `parks` counts distinct parks in `marts.obt_park_year`, `sessions` counts distinct sessions in `marts.fct_park_day`, and `player_played` is true when any of those sessions was not headless.
2. **The served set is eight files.** Any test that pins the list of files in `site/_data/` lists the eight; the success line of `make site-company` prints 8.
3. **The page prints the sample statement from the record.** The sentence pattern lives in the figure registry (`site/figures.mjs`) and the evidence block carries the one element that holds it (`site/_includes/evidence.njk`). The page check verifies the element against the served record and rejects stale fixed phrases.
4. **`make site-company` runs a record guard.** After the export and before the site build, so that a bad record is refused and the template never crashes on it, it refuses (exit 2, reason `sample-record`) a staged record that is missing, unreadable, not labeled `company`, or equal to the committed record in `parks`, `sessions` and `player_played`, and a committed record that is missing or unreadable. The page check after the build still compares the printed statement with the record.
5. **This replaces decision 3 of ADR 0044.** That decision's sentence guard and its behaviour that every company build exits 1 ("preparatory") are gone; ADR 0044's requirement that a company build state a sample that matches its data stands and is now met by decisions 3 and 4. ADR 0044's other decisions and the other decisions of ADR 0045 stand.

## Consequences

- Gain: the page states the sample of the data it was built from, for the committed sample and for a company build, with no sentence to keep in step by hand.
- Cost: one more committed file to regenerate whenever the sample changes, and the export comparison in `make check` fails until it is. The guard compares only the staged and committed records; a stale committed record is caught by that comparison, not by the guard.
- The session count prints as a numeral with no singular form ("1 sessions"), as the pattern is fixed.
