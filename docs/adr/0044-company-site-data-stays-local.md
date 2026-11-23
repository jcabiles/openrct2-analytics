# ADR 0044: Company site data stays local

- Date: 2026-11-02.
- Status: Accepted 2026-11-02 (the project owner's ruling on where company figures for the site live; the rest are director rulings taken while the project owner was unreachable and stand until the project owner changes them).

## Bottom line

Company figures for the public site are exported to the git-ignored folder `local/site-data/` and the site is built from them on request with `make site-company DATA_SET=company`. The committed `site/_data/` stays the sample, so `make check` and `make site-export` are unchanged. The price is that the company site can only be built and deployed from the project owner's machine, not by CI or from a fresh clone.

## Context

`docs/ai-dlc/roadmap/park-company.md` asks for company data to reach the site in one command, and ADR 0026 (`docs/adr/0026-build-time-json-for-the-first-site-page.md`) made the site a build over committed JSON files in `site/_data/`. Those files hold the committed rehearsal sample, and `make check` compares them with a fresh sample build. Writing company figures there would put company data in the repository, or make the gate compare files it cannot rebuild. ADR 0013 (`docs/adr/0013-one-duckdb-file-per-environment.md`) already keeps the published company warehouse as a file outside git, which is where the command reads from.

## Decision

1. **Company exports go to `local/site-data/`, and the site is built from them (ruling CS, the project owner's answer to where the company figures live).** The command reads `warehouse/company.duckdb` read-only, stages the export files `site/exports.toml` lists and a build of a copy of `site/` under `local/`, and lands them as `local/site-data/` and `site/_site/`, both git-ignored. Every temporary folder it makes (the stage and the export-input folder) is under `local/`. It never writes the committed `site/_data/`. It refuses with exit 2 when no published company file exists, when the `warehouse/` folder, the published file, an entry inside the copied `site/` tree or `local/site-data/` is a symbolic link, or when an output exists but is not a folder.
2. **Delete covers the site outputs (director ruling 2).** `make delete-company-data` previews and removes `local/site-data/` and a `site/_site/` that the company command built, so no deleted park's or session's figures linger (ADR 0033). A `site/_site/` counts as a company build only while its build stamp, a source line plus the SHA-256 of its `index.html`, still matches, so a sample build over it is never removed; no sample build source carries the stamp. It also removes the stage and export-input folders a killed run leaves under `local/`. A linked `local/` or `site/` is never followed.
3. **A company build never publishes a sample statement that does not match its data (director ruling 1).** The built page is checked against the committed sample statement, `EVIDENCE.sample` in `site/figures.mjs:46-48` (rendered by `site/_includes/evidence.njk:7` and `site/_includes/infra.njk:69`), which describes the committed sample. While the built page still holds it, the command exits 1 and lands nothing, so the repository's rule that an analysis states its sample cannot be broken by a company build. Until a later change makes the page state its own sample from the export, every company build stops here.
4. **A published file that lists a practice park is refused (director ruling 4).** The command exits 2 before writing anything when the registry marks a park as a throwaway practice park (ADR 0038), and names `make delete-company-data PARK=<id>` for each, so practice figures stay off the public site.

## Given up

- **Deploy from anywhere.** The committed option (company figures in `site/_data/` with a source stamp) would let any checkout build the company site. Local-only means only this machine, with its published company file, can build and deploy it.
- **A CI build of the company site.** The gate cannot rebuild company figures, so the company page is never proven by CI. The command is proven on fixture warehouses only, and its first run on the real file is the project owner's.

## Consequences

- **Gain:** company data stays out of git, and the gate keeps comparing the sample it can rebuild. The reason committed exports stay the sample is findable here.
- **Cost:** a company build must run on this machine. A later plain `npm run site:build` replaces the company build in `site/_site/` with a sample build, and the command replaces a sample build there.
- **Cost:** until the page states its own sample, `make site-company` is preparatory: it refuses or fails in every real run, by design.
- ADR 0026 is not edited by this record; it is cited one way only.
