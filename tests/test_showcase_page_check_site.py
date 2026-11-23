"""One failing planted case per tightened or new page-check rule (PC2-PC5, PC12-PC17)."""

from __future__ import annotations

from pathlib import Path

import pytest

from openrct2_analytics.showcase import page_check_text
from tests.page_check_support import PARK_YEAR_ROW, Fault, _fails, _html_append, _run, _site

PARK_ID = "k1234567890123-abc123"
GOOD_UNIT = "unit: US dollars; clock: company month"


def _file(relative: str, text: str) -> Fault:
    def fault(site: Path, served: Path) -> None:
        path = site / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    return fault


def _module(text: str) -> Fault:
    return _file("assets/extra.mjs", text)


def _figure(state: str, body: str, unit: str = GOOD_UNIT) -> Fault:
    return _html_append(
        f'<section data-figure="f" data-figure-state="{state}">'
        f"<p data-figure-unit>{unit}</p><div data-figure-body>{body}</div></section>"
    )


def _both(first: Fault, second: Fault) -> Fault:
    def fault(site: Path, served: Path) -> None:
        first(site, served)
        second(site, served)

    return fault


GOOD = [
    pytest.param(
        _module('const ns = "http://www.w3.org/2000/svg"; const n = 52 + 14 + 999;'),
        id="svg namespace and small numbers",
    ),
    pytest.param(
        _module("// Year 2000 and $5,000 and 1,234 in a comment only\nconst a = 'six';"),
        id="figures in comments",
    ),
    pytest.param(_file("assets/vendor/big.js", "var y = 2024, z = 123456;"), id="vendor skipped"),
    pytest.param(
        _both(
            _file("assets/helper.mjs", "export const a = 1;"),
            _module("import { a } from './helper.mjs'; console.log(a);"),
        ),
        id="local import",
    ),
    pytest.param(
        _module("""document.querySelector('#park-month-chart [href="a.b"]');"""),
        id="lookup on a known id",
    ),
    pytest.param(
        _file(
            "assets/js/dom.mjs",
            "export const $ = (selector, root = document) => root.querySelector(selector);\n"
            "export const $$ = (selector, root = document) => root.querySelectorAll(selector);\n",
        ),
        id="helper definitions",
    ),
    pytest.param(
        _module("const a = 'x' // note\nconst b = [\"park-month-chart\" // mount\n];"),
        id="string followed by a trailing comment",
    ),
    pytest.param(
        _module("// import { a } from './gone.mjs';\n/* from './gone.mjs' */ export const b = 1;"),
        id="import named only in a comment",
    ),
    pytest.param(
        _figure("live", "1"),
        id="live figure",
    ),
    pytest.param(
        _html_append(
            '<section data-figure="f" data-figure-state="pending">'
            "<p data-figure-unit>unit: US dollars; clock: company year</p></span>"
            "<div data-figure-body>figure pending</div></section>"
        ),
        id="stray end tag keeps the open figure",
    ),
    pytest.param(
        _figure("pending", "figure pending", "unit: US dollars; clock: company year"),
        id="pending figure",
    ),
    pytest.param(
        _html_append(
            f'<script type="application/json" id="park-year-data">[{PARK_YEAR_ROW}]</script>'
        ),
        id="matching further data block",
    ),
]


@pytest.mark.parametrize("fault", GOOD)
def test_planted_valid_variants_pass(tmp_path: Path, fault: Fault) -> None:
    site, served = _site(tmp_path)
    fault(site, served)
    assert _run(site, served) == 0


FAILURES = [
    # PC2: remote strings in modules and stylesheets
    _fails(
        "module URL: assets/extra.mjs holds a remote string literal (https://e.test/x)",
        _module('const url = "https://e.test/x";'),
        "pc2 https literal",
    ),
    _fails(
        "module URL: assets/extra.mjs holds a remote string literal (//e.test/x)",
        _module("const url = `//e.test/x`;"),
        "pc2 protocol-relative literal",
    ),
    _fails(
        "stylesheet URL: assets/site.css names another host",
        _file("assets/site.css", "a { background: url( 'https://e.test/a.png' ); }"),
        "pc2 css url",
    ),
    _fails(
        "module URL: assets/extra.mjs holds a remote string literal (//host/x)",
        _module("const a = 'x' // note\nconst u = '//host/x';"),
        "pc2 protocol-relative literal after a comment",
    ),
    _fails(
        "module URL: assets/extra.mjs holds a remote string literal (http://e.test)",
        _module('const u = "http://e.test";'),
        "pc2 http literal",
    ),
    _fails(
        "module URL: assets/extra.mjs holds a remote string literal (http://www.w3.org/1999/xhtml)",
        _module('const ns = "http://www.w3.org/1999/xhtml";'),
        "pc2 svg exception is only the two namespace strings",
    ),
    _fails(
        "stylesheet URL: assets/site.css names another host",
        _file("assets/site.css", "a { background: url(//e.test/a.png); }"),
        "pc2 css protocol-relative url",
    ),
    _fails(
        "stylesheet URL: assets/site.css names another host",
        _file("assets/site.css", '@import "https://e.test/a.css";'),
        "pc2 css import string",
    ),
    _fails(
        "stylesheet URL: assets/site.css names another host",
        _file("assets/site.css", "@import url(//e.test/a.css);"),
        "pc2 css import url",
    ),
    # PC3: further data blocks equal their served file
    _fails(
        "embedded park-year-data: differs from served park_year.json",
        _html_append('<script type="application/json" id="park-year-data">[]</script>'),
        "pc3 differing block",
    ),
    _fails(
        "embedded rooms-data: served rooms.json is missing",
        _html_append('<script type="application/json" id="rooms-data">[]</script>'),
        "pc3 block without a served file",
    ),
    # PC5: unit lines
    _fails(
        "figure region: the data-figure-unit line is missing",
        _html_append(
            '<section data-figure="f" data-figure-state="live">'
            "<div data-figure-body>1</div></section>"
        ),
        "pc5 live region without a unit line",
    ),
    _fails(
        "figure region: the data-figure-unit line is missing",
        _html_append(
            '<section data-figure="f" data-figure-state="pending">'
            "<div data-figure-body>figure pending</div></section>"
        ),
        "pc5 pending region without a unit line",
    ),
    _fails("figure unit line", _figure("live", "1", "unit: US dollars"), "pc5 no clock"),
    _fails("figure unit line", _figure("live", "1", "clock: company month"), "pc5 no unit"),
    _fails(
        "figure unit line", _figure("live", "1", "unit: dollars; clock: sometime"), "pc5 bad clock"
    ),
    # PC12: local scripts, resolvable imports, no inline code
    _fails(
        "script source: assets/missing.js is not a file in the built site",
        _html_append('<script src="assets/missing.js"></script>'),
        "pc12 missing script",
    ),
    _fails(
        "script source: ../x is not a file in the built site",
        _both(_file("../x", "var a;"), _html_append('<script src="../x"></script>')),
        "pc12 script outside the site",
    ),
    _fails(
        "inline script: only application/json blocks",
        _html_append("<script>alert(1)</script>"),
        "pc12 inline code",
    ),
    _fails(
        "inline script: only application/json blocks",
        _html_append('<script type="module">import "./x.mjs"</script>'),
        "pc12 inline module",
    ),
    _fails(
        "import: ./nope.mjs in assets/extra.mjs is not a file in the built site",
        _module("import { a } from './nope.mjs';"),
        "pc12 unresolved import",
    ),
    _fails(
        "import: ./gone.mjs in assets/extra.mjs is not a file in the built site",
        _module("// kept\nimport { a } from './gone.mjs';"),
        "pc12 real import after a comment",
    ),
    # PC13: network bans and literal lookups in every module
    _fails("module assets/extra.mjs: fetch", _module('fetch("data.json");'), "pc13 fetch"),
    _fails(
        "module assets/extra.mjs: fetch",
        _module("const m = await import('./x.mjs');"),
        "pc13 dynamic import",
    ),
    _fails(
        "module assets/extra.mjs: class nope is not in the built page",
        _module('document.querySelector(".nope");'),
        "pc13 unknown class selector",
    ),
    _fails(
        "module assets/extra.mjs: id nope is not in the built page",
        _module('document.getElementById("nope");'),
        "pc13 unknown id",
    ),
    _fails(
        "module assets/extra.mjs: id nope is not in the built page",
        _module('el.closest("#nope");'),
        "pc13 unknown closest id",
    ),
    _fails(
        "module assets/extra.mjs: an element lookup takes a computed value",
        _module("document.querySelectorAll(name);"),
        "pc13 computed selector",
    ),
    _fails(
        "module assets/extra.mjs: an element lookup takes a computed value",
        _module("const x = $(`#${name}`);"),
        "pc13 helper with a template",
    ),
    _fails(
        "module assets/js/dom.mjs: an element lookup takes a computed value",
        _file("assets/js/dom.mjs", "export const f = (s) => document.querySelector(s);\n"),
        "pc13 lookup outside a helper definition",
    ),
    # PC15: figure regions
    _fails(
        "figure region: data-figure-state is missing",
        _html_append('<div data-figure="f"></div>'),
        "pc15 no state",
    ),
    _fails(
        "pending figure: body must be exactly",
        _figure("pending", "$4,000"),
        "pc15 pending with a figure",
    ),
    _fails(
        "pending figure: body must be exactly",
        _figure("pending", "figure pending."),
        "pc15 pending extra text",
    ),
    _fails(
        "pending figure: body must be exactly",
        _html_append(
            '<div data-figure="f" data-figure-state="pending">'
            "<p data-figure-unit>unit: US dollars; clock: company year</p></div>"
        ),
        "pc15 pending without a body",
    ),
    # PC16: invented copy
    _fails(
        "illustrative copy: index.html", _html_append("<p>Illustrative season</p>"), "pc16 page"
    ),
    _fails(
        "illustrative copy: assets/extra.mjs", _module("// ILLUSTRATIVE values\n"), "pc16 module"
    ),
    _fails(
        "pending figure: the unit line holds a year",
        _figure("pending", "figure pending", "unit: US dollars; clock: company year 2000"),
        "pc16 year in pending unit",
    ),
    _fails(
        f"park ID: index.html holds {PARK_ID}, not in the exports",
        _html_append(f"<p>{PARK_ID}</p>"),
        "pc16 invented park id in the page",
    ),
    _fails(
        f"park ID: assets/extra.mjs holds {PARK_ID}, not in the exports",
        _module(f"const id = 'park {PARK_ID}';"),
        "pc16 invented park id in a module",
    ),
    # PC17: literals in modules
    _fails(
        "module literal: assets/extra.mjs holds '2000'", _module("const year = 2000;"), "pc17 year"
    ),
    _fails(
        "module literal: assets/extra.mjs holds '1000'",
        _module("const n = 1000;"),
        "pc17 large count",
    ),
    _fails(
        "module literal: assets/extra.mjs holds '1e3'", _module("const n = 1e3;"), "pc17 exponent"
    ),
    _fails(
        "module literal: assets/extra.mjs holds '$5.00'",
        _module('const s = "$5.00";'),
        "pc17 money string",
    ),
    _fails(
        "module literal: assets/extra.mjs holds '6,500'",
        _module("const s = '6,500';"),
        "pc17 thousands string",
    ),
    _fails(
        "module literal: assets/extra.mjs holds 'Mar 2000'",
        _module("const s = `Mar 2000`;"),
        "pc17 year string",
    ),
]


@pytest.mark.parametrize(("fault", "message"), FAILURES)
def test_each_planted_rule_break_exits_one_with_its_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], fault: Fault, message: str
) -> None:
    site, served = _site(tmp_path)
    fault(site, served)
    assert _run(site, served) == 1
    assert f"page check failed: {message}" in capsys.readouterr().out


def test_invented_park_id_passes_when_the_exports_hold_it(tmp_path: Path) -> None:
    site, served = _site(tmp_path)
    (served / "extra.json").write_text(f'{{"rows":["{PARK_ID}"]}}\n')
    _html_append(f"<p>{PARK_ID}</p>")(site, served)
    assert _run(site, served) == 0


def test_a_listed_module_literal_passes_and_an_unlisted_one_still_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    site, served = _site(tmp_path)
    _module("const year = 2000; const n = 5000;")(site, served)
    monkeypatch.setitem(
        page_check_text.MODULE_NUMBER_ALLOWLIST,
        "assets/extra.mjs",
        {"2000": "fixture year", "5000": "fixture count"},
    )
    assert _run(site, served) == 0
    _module("const year = 2000; const n = 5001;")(site, served)
    assert _run(site, served) == 1
    assert "holds '5001'" in capsys.readouterr().out
