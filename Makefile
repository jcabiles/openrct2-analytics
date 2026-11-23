.PHONY: setup doctor check site-export site-company fix lock listen convert contracts transform pipeline capture-data play launcher capture-rehearsal register-parks play-status unfiled after-play auto-file autopilot-parks results real-play-check publish rollback bench bench-sample delete-company-data go-live ticket autopilot-year autopilot-real-test dashboard

MAIN := $(patsubst %/,%,$(dir $(shell git rev-parse --path-format=absolute --git-common-dir)))
BASE ?= develop
# Tool folders installed in the main checkout, linked into each ticket worktree.
LINK_DIRS := .venv node_modules

# DATA_SET comes only from the command line, and only data-set targets check it, so an export left in a shell never
# blocks the gate. The value is one of two words, so `--data-set $(DATA_SET)` can never carry shell text.
DATA_SET_GOALS := listen capture-data play capture-rehearsal register-parks play-status unfiled after-play auto-file autopilot-parks results real-play-check convert contracts transform pipeline publish rollback site-company autopilot-year dashboard
ifneq ($(filter $(DATA_SET_GOALS),$(MAKECMDGOALS)),)
ifneq ($(filter environment%,$(origin DATA_SET)),)
$(error DATA_SET must be given on the command line (make <target> DATA_SET=rehearsal or DATA_SET=company), not read from the environment)
endif
ifneq ($(DATA_SET),)
ifneq ($(DATA_SET),rehearsal)
ifneq ($(DATA_SET),company)
$(error DATA_SET must be exactly rehearsal or company on the command line (make <target> DATA_SET=rehearsal))
endif
endif
endif
endif

ifneq ($(filter register-parks,$(MAKECMDGOALS)),)
ifneq ($(filter environment%,$(origin PRACTICE)),)
$(error PRACTICE must be given on the command line (make register-parks DATA_SET=company PRACTICE=yes), not read from the environment)
endif
ifneq ($(PRACTICE),)
ifneq ($(PRACTICE),yes)
$(error PRACTICE must be empty or exactly yes)
endif
endif
endif

ifneq ($(filter register-parks after-play,$(MAKECMDGOALS)),)
ifneq ($(filter environment%,$(origin PARKS)),)
$(error PARKS must be given on the command line (make after-play DATA_SET=company PARKS="<id>:company,<id>:practice"), not read from the environment)
endif
ifneq ($(findstring $$,$(value PARKS)),)
$(error PARKS must not contain a dollar sign)
endif
ifneq ($(filter environment%,$(origin START_YEAR)),)
$(error START_YEAR must be given on the command line (make register-parks DATA_SET=company PARKS="<id>:company" START_YEAR=<year>), not read from the environment)
endif
ifneq ($(findstring $$,$(value START_YEAR)),)
$(error START_YEAR must not contain a dollar sign)
endif
endif

ifneq ($(filter auto-file,$(MAKECMDGOALS)),)
ifneq ($(filter environment%,$(origin COUNT_AS)),)
$(error COUNT_AS must be given on the command line (make auto-file DATA_SET=company COUNT_AS=company), not read from the environment)
endif
ifneq ($(findstring $$,$(value COUNT_AS)),)
$(error COUNT_AS must not contain a dollar sign)
endif
ifneq ($(filter environment%,$(origin RECORD)),)
$(error RECORD must be given on the command line (make auto-file DATA_SET=company RECORD=yes), not read from the environment)
endif
ifneq ($(findstring $$,$(value RECORD)),)
$(error RECORD must not contain a dollar sign)
endif
ifneq ($(RECORD),)
ifneq ($(RECORD),yes)
$(error RECORD must be empty or exactly yes)
endif
endif
endif

ifneq ($(filter autopilot-year,$(MAKECMDGOALS)),)
ifneq ($(filter environment%,$(origin PARK)),)
$(error PARK must be given on the command line (make autopilot-year DATA_SET=company PARK=<park id>), not read from the environment)
endif
ifneq ($(findstring $$,$(value PARK)),)
$(error PARK must not contain a dollar sign)
endif
ifneq ($(filter environment%,$(origin READY)),)
$(error READY must be given on the command line (make autopilot-year DATA_SET=company PARK=<park id> READY="<phrase>"), not read from the environment)
endif
ifneq ($(findstring $$,$(value READY)),)
$(error READY must not contain a dollar sign)
endif
endif

ifneq ($(filter results,$(MAKECMDGOALS)),)
ifneq ($(filter environment%,$(origin PUBLISHED)),)
$(error PUBLISHED must be given on the command line (make results DATA_SET=company PUBLISHED=yes), not read from the environment)
endif
ifneq ($(PUBLISHED),)
ifneq ($(PUBLISHED),yes)
$(error PUBLISHED must be empty or exactly yes)
endif
endif
endif

ifneq ($(filter real-play-check delete-company-data,$(MAKECMDGOALS)),)
ifneq ($(filter environment%,$(origin SESSION)),)
$(error SESSION must be given on the command line, not read from the environment)
endif
ifneq ($(findstring $$,$(value SESSION)),)
$(error SESSION must not contain a dollar sign)
endif
endif

ifneq ($(filter delete-company-data,$(MAKECMDGOALS)),)
ifneq ($(filter environment%,$(origin PARK)),)
$(error PARK must be given on the command line, not read from the environment)
endif
ifneq ($(findstring $$,$(value PARK)),)
$(error PARK must not contain a dollar sign)
endif
ifneq ($(filter environment%,$(origin CONFIRM)),)
$(error CONFIRM must be given on the command line, not read from the environment)
endif
ifneq ($(findstring $$,$(value CONFIRM)),)
$(error CONFIRM must not contain a dollar sign)
endif
endif

# CI passes CHECK_TESTS= to skip the pytest suite (about 50 minutes on a runner); the local gate keeps it.
CHECK_TESTS ?= $${RUN}pytest &&

# The doctor runs on the venv's own Python (never `uv run`, which would sync first and hide damage); with no venv
# it runs on the system python3 so it can say the venv is missing. Shared by setup, doctor and check; a `$(MAKE)`
# line would run even under `make -n`.
DOCTOR := if [ -x .venv/bin/python ]; then .venv/bin/python scripts/doctor.py; else python3 scripts/doctor.py; fi

setup: # Create or update the venv and deps (pip -e fallback if uv is unavailable; the doctor then skips its managed-Python check), install npm packages, then activate the git pre-commit hook. Safe to re-run.
	@git rev-parse --git-dir >/dev/null 2>&1 || { echo "run git init first, then make setup"; exit 1; }
	@if command -v uv >/dev/null 2>&1; then \
		uv sync; \
	else \
		python3.12 -m venv .venv && .venv/bin/pip install --upgrade pip && .venv/bin/pip install -e . --group dev; \
	fi
	npm ci --ignore-scripts
	mkdir -p warehouse/dev
	git config core.hooksPath .githooks
	@$(DOCTOR)

doctor: # Check the Python environment is whole: the venv's Python is uv-managed, every file in every installed package's RECORD exists, and the venv's Python imports dbt and this project (offline). Prints the repair when it is not.
	@$(DOCTOR)

check: # Canonical gate: the Python environment check (make doctor), format check, lint, file sizes, docs, absolute local paths, metric catalog rules, typecheck, tests, plugin build, plugin tests, sample-data contract check, registry feed check on the sample, save-file record check on the sample, play-mode label feed check on the sample, dbt source drift check, dbt house rules, contract breaking-change check (runs only while CI is set), metric catalog shape (dbt parse of the catalog), dbt parse+build on the sample, the showcase export comparison, the site build and the page check on that build, a second dbt build on a zero-row extract, a check that every built model's columns match its YAML and no `_tenths` column is built outside staging, the dbt docs build and the exposure check (every `obt_` model has an exposure), the cleaning-rule counts check (every known cleaning filter has a counts row), then SQL lint (sqlfluff), all on the `ci` target in a temporary folder that is removed afterwards, secret scan -- stops at the first failure. It leaves no warehouse behind.
	@set -e; \
	if command -v uv >/dev/null 2>&1; then RUN="uv run "; else RUN=".venv/bin/"; fi; \
	$(DOCTOR) && \
	$${RUN}ruff format --check . && \
	$${RUN}ruff check . && \
	$${RUN}python scripts/check_file_sizes.py && \
	$${RUN}python scripts/check_docs.py && \
	$${RUN}python scripts/check_local_paths.py && \
	$${RUN}python scripts/check_metric_catalog.py && \
	$${RUN}mypy . && \
	$(CHECK_TESTS) \
	npm run --silent plugin:build && \
	node --test plugin/test/*.test.mjs && \
	$${RUN}python -m openrct2_analytics.ingest.contracts --data-root data/sample/rehearsal && \
	$${RUN}python -m openrct2_analytics.ingest.registry_feed --data-root data/sample/rehearsal && \
	$${RUN}python -m openrct2_analytics.ingest.save_files --data-root data/sample/rehearsal && \
	$${RUN}python -m openrct2_analytics.ingest.play_mode_feed --data-root data/sample/rehearsal && \
	$${RUN}python scripts/generate_dbt_sources.py --check && \
	$${RUN}python scripts/check_dbt_rules.py && \
	$${RUN}python scripts/check_contract_breaking.py && \
	$${RUN}python scripts/check_metric_catalog_shape.py && \
	( dir=$$(mktemp -d "$${TMPDIR:-/tmp}/openrct2-ci.XXXXXX") && \
	dir=$$(cd "$$dir" && pwd -P) && \
	trap 'rm -rf "$${dir:?}"' EXIT && \
	trap 'exit 130' INT HUP TERM && \
	export OPENRCT2_CI_DIR="$$dir" && \
	export DBT_TARGET_PATH="$$dir/target" && \
	$${RUN}python -m openrct2_analytics.ingest.warehouse_guard --root "$$dir" "$$dir/ci.duckdb" && \
	$${RUN}dbt parse --profiles-dir . --target ci --target-path "$$dir/target" --log-path "$$dir/logs" --vars "{parquet_root: data/sample/rehearsal}" && \
	$${RUN}dbt build --profiles-dir . --target ci --target-path "$$dir/target" --log-path "$$dir/logs" --vars "{parquet_root: data/sample/rehearsal}" && \
	$${RUN}python -m openrct2_analytics.showcase.export check --warehouse "$$dir/ci.duckdb" && \
	npm run --silent site:build -- --output="$$dir/site" && \
	$${RUN}python -m openrct2_analytics.showcase.page_check --site "$$dir/site" --served-dir site/_data && \
	$${RUN}python -m openrct2_analytics.ingest.empty_extract --out-dir "$$dir/empty" && \
	$${RUN}dbt build --profiles-dir . --target ci --target-path "$$dir/target" --log-path "$$dir/logs" --vars "{parquet_root: $$dir/empty}" && \
	$${RUN}python scripts/check_model_columns.py "$$dir/target/manifest.json" "$$dir/ci.duckdb" && \
	$${RUN}dbt docs generate --profiles-dir . --target ci --target-path "$$dir/target" --log-path "$$dir/logs" --vars "{parquet_root: $$dir/empty}" && \
	$${RUN}python scripts/check_exposures.py "$$dir/target/manifest.json" && \
	$${RUN}python scripts/check_cleaning_rule_counts.py "$$dir/target/manifest.json" "$$dir/ci.duckdb" && \
	$${RUN}sqlfluff lint models tests/dbt ) && \
	$${RUN}detect-secrets-hook --baseline .secrets.baseline $$(git ls-files)

site-export: # Rebuild the sample warehouse in a temporary folder and rewrite the served files in site/_data from its marts. The folder is removed afterwards.
	@set -e; \
	if command -v uv >/dev/null 2>&1; then RUN="uv run "; else RUN=".venv/bin/"; fi; \
	( dir=$$(mktemp -d "$${TMPDIR:-/tmp}/openrct2-ci.XXXXXX") && \
	dir=$$(cd "$$dir" && pwd -P) && \
	trap 'rm -rf "$${dir:?}"' EXIT && \
	trap 'exit 130' INT HUP TERM && \
	export OPENRCT2_CI_DIR="$$dir" && \
	export DBT_TARGET_PATH="$$dir/target" && \
	$${RUN}python -m openrct2_analytics.ingest.warehouse_guard --root "$$dir" "$$dir/ci.duckdb" && \
	$${RUN}dbt parse --profiles-dir . --target ci --target-path "$$dir/target" --log-path "$$dir/logs" --vars "{parquet_root: data/sample/rehearsal}" && \
	$${RUN}dbt build --profiles-dir . --target ci --target-path "$$dir/target" --log-path "$$dir/logs" --vars "{parquet_root: data/sample/rehearsal}" && \
	$${RUN}python -m openrct2_analytics.showcase.export write --warehouse "$$dir/ci.duckdb" )

fix: # Auto-fix formatting and lint issues in place.
	@if command -v uv >/dev/null 2>&1; then \
		uv run ruff format . && uv run ruff check --fix .; \
	else \
		.venv/bin/ruff format . && .venv/bin/ruff check --fix .; \
	fi

lock: # Regenerate the uv lockfile.
	uv lock

listen: # Run the TCP listener that appends game events to data/<set>/raw.
	@set -e; \
	if command -v uv >/dev/null 2>&1; then RUN="uv run "; else RUN=".venv/bin/"; fi; \
	$${RUN}python -m openrct2_analytics.ingest.listener $(if $(DATA_SET),--data-set $(DATA_SET))

convert: # Convert the raw JSON Lines into Parquet under the Parquet folder.
	@set -e; \
	if command -v uv >/dev/null 2>&1; then RUN="uv run "; else RUN=".venv/bin/"; fi; \
	$${RUN}python -m openrct2_analytics.ingest.convert $(if $(DATA_SET),--data-set $(DATA_SET))

contracts: # Check the converted Parquet against the data contracts, then the data set's registry feed, save-file records and play-mode label feed.
	@set -e; \
	if command -v uv >/dev/null 2>&1; then RUN="uv run "; else RUN=".venv/bin/"; fi; \
	$${RUN}python -m openrct2_analytics.ingest.contracts $(if $(DATA_SET),--data-set $(DATA_SET)) && \
	$${RUN}python -m openrct2_analytics.ingest.registry_feed $(if $(DATA_SET),--data-set $(DATA_SET)) && \
	$${RUN}python -m openrct2_analytics.ingest.save_files $(if $(DATA_SET),--data-set $(DATA_SET)) && \
	$${RUN}python -m openrct2_analytics.ingest.play_mode_feed $(if $(DATA_SET),--data-set $(DATA_SET))

transform: # First check the data set's registry feed (stops when it is absent) and its play-mode label feed, then build the dbt models over the converted Parquet folder of one data set into warehouse/dev (DATA_SET=rehearsal or DATA_SET=company).
	@set -e; \
	if command -v uv >/dev/null 2>&1; then RUN="uv run "; else RUN=".venv/bin/"; fi; \
	if [ -z "$(DATA_SET)" ]; then echo "transform needs DATA_SET=rehearsal or DATA_SET=company on the command line" >&2; exit 2; fi; \
	ROOT=$$($${RUN}python -c "import sys; from openrct2_analytics.config import landing_dirs; print(landing_dirs(sys.argv[1]).parquet.resolve())" "$(DATA_SET)"); \
	REG=$$($${RUN}python -c "import sys; from openrct2_analytics.ingest.registry_feed import registry_dir; print(registry_dir(sys.argv[1]).resolve())" "$(DATA_SET)"); \
	$${RUN}python -m openrct2_analytics.ingest.registry_feed --data-set $(DATA_SET) && \
	$${RUN}python -m openrct2_analytics.ingest.play_mode_feed --data-set $(DATA_SET) && \
	$${RUN}python -m openrct2_analytics.ingest.warehouse_guard --root warehouse warehouse/dev/dev.duckdb && \
	mkdir -p warehouse/dev && \
	$${RUN}dbt build --profiles-dir . --target dev --vars "{parquet_root: '$$ROOT', registry_root: '$$REG'}"

pipeline: # Run the after-play steps in order -- convert, contracts, transform -- and stop at the first that fails.
	$(MAKE) convert
	$(MAKE) contracts
	$(MAKE) transform

capture-data: # Capture one play session: install the plugin, listen until the game quits, remove the plugin, convert and report.
	@set -e; \
	if command -v uv >/dev/null 2>&1; then RUN="uv run "; else RUN=".venv/bin/"; fi; \
	$${RUN}python -m openrct2_analytics.ingest.capture $(if $(DATA_SET),--data-set $(DATA_SET))

play: # Capture one session as capture-data does, but open the game once the plugin is installed (the launcher runs this).
	@set -e; \
	if command -v uv >/dev/null 2>&1; then RUN="uv run "; else RUN=".venv/bin/"; fi; \
	$${RUN}python -m openrct2_analytics.ingest.capture $(if $(DATA_SET),--data-set $(DATA_SET)) --open-game

launcher: # Build the "OpenRCT2 Enterprise" app in ~/Applications; it opens launcher/play-company.command in Terminal, which asks Company or Sandbox, plays, then files the play (macOS; never committed).
	@set -e; \
	command -v osacompile >/dev/null 2>&1 || { echo "make launcher needs osacompile, which only macOS has."; exit 2; }; \
	file="$$(pwd -P)/launcher/play-company.command"; \
	test -x "$$file" || { echo "$$file is missing or not executable."; exit 2; }; \
	apps="$$HOME/Applications"; app="$$apps/OpenRCT2 Enterprise.app"; \
	mkdir -p "$$apps"; \
	build=$$(mktemp -d "$$apps/.openrct2-enterprise.XXXXXX"); \
	trap 'rm -rf "$$build"' EXIT; \
	quoted=$$(printf '%s' "$$file" | sed 's/[\\"]/\\&/g'); \
	printf 'do shell script "open -a Terminal " & quoted form of "%s"\n' "$$quoted" > "$$build/launcher.applescript"; \
	osacompile -o "$$build/OpenRCT2 Enterprise.app" "$$build/launcher.applescript"; \
	game=/Applications/OpenRCT2.app; [ -d "$$game" ] || game="$$HOME/Applications/OpenRCT2.app"; \
	icon=$$(plutil -extract CFBundleIconFile raw "$$game/Contents/Info.plist" 2>/dev/null || true); \
	icon="$$game/Contents/Resources/$${icon%.icns}.icns"; \
	if [ -f "$$icon" ]; then \
	  contents="$$build/OpenRCT2 Enterprise.app/Contents"; \
	  cp "$$icon" "$$contents/Resources/applet.icns"; \
	  rm -f "$$contents/Resources/Assets.car"; \
	  plutil -remove CFBundleIconName "$$contents/Info.plist" 2>/dev/null || true; \
	  codesign --force --sign - "$$build/OpenRCT2 Enterprise.app"; \
	else echo "OpenRCT2.app was not found in /Applications or ~/Applications; the app keeps the script icon."; fi; \
	rm -rf "$$app"; \
	mv "$$build/OpenRCT2 Enterprise.app" "$$app"; \
	touch "$$app"; \
	echo "Built $$app. Drag it to the Dock; double-click it to record and play the company park."

capture-rehearsal: # Capture the two-park rehearsal chain headless and land it (DATA_SET=rehearsal only).
	@set -e; \
	if command -v uv >/dev/null 2>&1; then RUN="uv run "; else RUN=".venv/bin/"; fi; \
	$${RUN}python -m openrct2_analytics.ingest.rehearsal_capture $(if $(DATA_SET),--data-set $(DATA_SET))

register-parks: # Write the registry row for each captured park the registry does not list yet (DATA_SET=company; PRACTICE=yes marks a throwaway sandbox park; PARKS="<id>:company,<id>:practice" (`practice` is shown as Sandbox) registers only those parks, each with its own choice; START_YEAR=<year> sets the company start year of the parks being registered).
	@set -e; \
	if command -v uv >/dev/null 2>&1; then RUN="uv run "; else RUN=".venv/bin/"; fi; \
	$${RUN}python -m openrct2_analytics.ingest.register_parks $(if $(DATA_SET),--data-set $(DATA_SET)) $(if $(PRACTICE),--practice) $${PARKS+--parks="$$PARKS"} $${START_YEAR+--start-year="$$START_YEAR"}

play-status: # Print one JSON object: the dev warehouse state and the converted sessions it does not hold yet, with each park's registration and last save file. Read-only.
	@set -e; \
	if command -v uv >/dev/null 2>&1; then RUN="uv run "; else RUN=".venv/bin/"; fi; \
	$${RUN}python -m openrct2_analytics.ingest.play_status $(if $(DATA_SET),--data-set $(DATA_SET))

unfiled: # Print the launcher's status word and the play waiting to be filed; nothing when none waits. Read-only.
	@set -e; \
	if command -v uv >/dev/null 2>&1; then RUN="uv run "; else RUN=".venv/bin/"; fi; \
	$${RUN}python -m openrct2_analytics.ingest.unfiled $(if $(DATA_SET),--data-set $(DATA_SET))

after-play: # Register the waiting parks (PARKS="<id>:company,<id>:practice" names every one; START_YEAR=<year> sets the company start year), check the contracts, build dbt and print the results; stops at the first failing step (DATA_SET=company).
	@set -e; \
	if command -v uv >/dev/null 2>&1; then RUN="uv run "; else RUN=".venv/bin/"; fi; \
	$${RUN}python -m openrct2_analytics.ingest.after_play $(if $(DATA_SET),--data-set $(DATA_SET)) $${PARKS+--parks="$$PARKS"} $${START_YEAR+--start-year="$$START_YEAR"}

auto-file: # File the sessions of the play just finished: RECORD=yes notes the converted sessions before a play; COUNT_AS=<company|practice> files this play's parks after it (DATA_SET=company).
	@set -e; \
	if command -v uv >/dev/null 2>&1; then RUN="uv run "; else RUN=".venv/bin/"; fi; \
	$${RUN}python -m openrct2_analytics.ingest.auto_file $(if $(DATA_SET),--data-set $(DATA_SET)) $(if $(RECORD),--record) $${COUNT_AS+--count-as="$$COUNT_AS"}

autopilot-parks: # Print one JSON object listing the company parks the autopilot can run (DATA_SET=company). Read-only.
	@set -e; \
	if command -v uv >/dev/null 2>&1; then RUN="uv run "; else RUN=".venv/bin/"; fi; \
	$${RUN}python -m openrct2_analytics.ingest.autopilot_parks $(if $(DATA_SET),--data-set $(DATA_SET))

autopilot-year: # Run a finished company park headless to 1 March of the next game year and land the capture labeled autopilot (DATA_SET=company PARK=<id>; READY="<phrase>" on the park's first run).
	@set -e; \
	if command -v uv >/dev/null 2>&1; then RUN="uv run "; else RUN=".venv/bin/"; fi; \
	$${RUN}python -m openrct2_analytics.ingest.autopilot_year $(if $(DATA_SET),--data-set $(DATA_SET)) $${PARK+--park="$$PARK"} $${READY+--ready="$$READY"}

results: # Print the results tables of one data set (PUBLISHED=yes reads the published file).
	@set -e; \
	if command -v uv >/dev/null 2>&1; then RUN="uv run "; else RUN=".venv/bin/"; fi; \
	$${RUN}python -m openrct2_analytics.ingest.results $(if $(DATA_SET),--data-set $(DATA_SET)) $(if $(PUBLISHED),--published)

real-play-check: # Print whether the plugin captured what it should in the latest practice session (SESSION=<id> picks another).
	@set -e; \
	if command -v uv >/dev/null 2>&1; then RUN="uv run "; else RUN=".venv/bin/"; fi; \
	$${RUN}python -m openrct2_analytics.ingest.real_play_check $(if $(DATA_SET),--data-set $(DATA_SET)) $${SESSION+--session="$$SESSION"}

publish: # Build, check and publish the warehouse of one data set (DATA_SET=rehearsal or DATA_SET=company).
	@set -e; \
	if command -v uv >/dev/null 2>&1; then RUN="uv run "; else RUN=".venv/bin/"; fi; \
	$${RUN}python -m openrct2_analytics.ingest.publish $(if $(DATA_SET),--data-set $(DATA_SET))

rollback: # Restore the previous published warehouse of one data set (DATA_SET=rehearsal or DATA_SET=company).
	@set -e; \
	if command -v uv >/dev/null 2>&1; then RUN="uv run "; else RUN=".venv/bin/"; fi; \
	$${RUN}python -m openrct2_analytics.ingest.publish --rollback $(if $(DATA_SET),--data-set $(DATA_SET))

site-company: # Build the company site from the published company warehouse (DATA_SET=company).
	@set -e; \
	if command -v uv >/dev/null 2>&1; then RUN="uv run "; else RUN=".venv/bin/"; fi; \
	$${RUN}python -m openrct2_analytics.ingest.site_company $(if $(DATA_SET),--data-set $(DATA_SET))

dashboard: # Serve the company dashboard on localhost from the development warehouse until stopped (DATA_SET=company; DASHBOARD_PORT=<port>, default 8780; DASHBOARD_DETACH=1 keeps it running after its terminal closes). The launcher starts it.
	@set -e; \
	case '$(DASHBOARD_PORT)' in *[!0-9]*) echo "DASHBOARD_PORT must be digits"; exit 2 ;; esac; \
	if command -v uv >/dev/null 2>&1; then RUN="uv run "; else RUN=".venv/bin/"; fi; \
	$${RUN}python -m openrct2_analytics.ingest.dashboard $(if $(DATA_SET),--data-set $(DATA_SET)) $(if $(DASHBOARD_PORT),--port $(DASHBOARD_PORT)) $(if $(DASHBOARD_DETACH),--detach)

bench: # Measure the plugin headless on a copy of the benchmark park: three judged runs, verdict.json in the work folder (needs the benchmark park from OPENRCT2_BENCH_PARK or local/game-settings.env).
	@set -e; \
	if command -v uv >/dev/null 2>&1; then RUN="uv run "; else RUN=".venv/bin/"; fi; \
	$${RUN}python -m openrct2_analytics.ingest.bench_run

bench-sample: # Rebuild data/sample/rehearsal from three chained headless sessions on a copy of the benchmark park.
	@set -e; \
	if command -v uv >/dev/null 2>&1; then RUN="uv run "; else RUN=".venv/bin/"; fi; \
	$${RUN}python -m openrct2_analytics.ingest.bench_run --sample

autopilot-real-test: # Run the opt-in real-game autopilot test (starts the game; settings come from the environment, local/game-settings.env or OpenRCT2's own settings); not part of make check.
	@set -e; \
	if command -v uv >/dev/null 2>&1; then RUN="uv run "; else RUN=".venv/bin/"; fi; \
	OPENRCT2_AUTOPILOT_REAL_GAME=1 $${RUN}python -m pytest tests/test_autopilot_real_game.py -rA

delete-company-data: # Preview or archive and delete company data before go-live.
	@set -e; \
	if command -v uv >/dev/null 2>&1; then RUN="uv run "; else RUN=".venv/bin/"; fi; \
	$${RUN}python -m openrct2_analytics.ingest.delete_data $${PARK+--park="$$PARK"} $${SESSION+--session="$$SESSION"} $${CONFIRM+--confirm="$$CONFIRM"}

go-live: # Refuse until a way around the seq stop in make pipeline exists.
	@set -e; \
	if command -v uv >/dev/null 2>&1; then RUN="uv run "; else RUN=".venv/bin/"; fi; \
	$${RUN}python -m openrct2_analytics.ingest.go_live

# Claim an agent ticket: `make ticket ID=<id>` creates .worktrees/<id> on branch ticket/<id>
# from $(BASE). An existing branch means another session already claimed it. Values reach the
# shell as environment variables, never as recipe text, and a missing tool folder stops the claim.
ticket: export TICKET_ID = $(ID)
ticket: export TICKET_BASE = $(BASE)
ticket: export TICKET_MAIN = $(MAIN)
ticket: export TICKET_LINKS = $(LINK_DIRS)
ticket:
	@case "$$TICKET_ID" in "") echo "usage: make ticket ID=<ticket id> [BASE=<branch>]"; exit 2 ;; -* | .* | *[!A-Za-z0-9._-]*) echo "ticket id may use only letters, digits, dot, dash and underscore"; exit 2 ;; esac; \
	case "$$TICKET_BASE" in "" | -*) echo "BASE must name a branch"; exit 2 ;; esac; \
	for d in $$TICKET_LINKS; do test -e "$$TICKET_MAIN/$$d" || { echo "not claimed: $$d is missing in the main checkout; install dependencies there first"; exit 1; }; done; \
	if git show-ref --verify --quiet "refs/heads/ticket/$$TICKET_ID"; then echo "ticket $$TICKET_ID is already claimed (branch ticket/$$TICKET_ID exists)"; exit 1; fi; \
	set -e; git -C "$$TICKET_MAIN" worktree add -b "ticket/$$TICKET_ID" "$$TICKET_MAIN/.worktrees/$$TICKET_ID" "$$TICKET_BASE"; \
	for d in $$TICKET_LINKS; do ln -s "$$TICKET_MAIN/$$d" "$$TICKET_MAIN/.worktrees/$$TICKET_ID/$$d"; done; \
	echo "claimed: $$TICKET_MAIN/.worktrees/$$TICKET_ID"
