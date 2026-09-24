"""The dashboard's two label dictionaries, checked against the server's enums.

``static/app.js`` holds the Bengali and English strings and builds label keys
by string concatenation — ``kind`` + ``data_quality`` -> ``kindDataQuality``.
Nothing ties those keys to the values the API can actually send, so a new
``AlertKind`` or ``CaseStatus`` would ship with no label and reach an operator
as a raw key or a raw enum value in the middle of a sentence.

These tests read the JavaScript as data rather than executing it: they check
the dictionaries cover every value the enums can produce, and that the two
languages define the same set of keys — a key present in one and missing from
the other means that string silently falls back to the other language, which is
how a Bengali dashboard ends up with an English sentence in it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.coordination import ROUTES
from app.domain import AlertKind, CaseStatus, Classification, Severity

APP_JS = Path(__file__).resolve().parents[1] / "static" / "app.js"

# Every list below is derived from the code that produces the value, not written
# out by hand. A hand-written list is a second copy of the enum that can drift
# from it in silence — the first draft of this file asserted labels for two
# classifications and a role that do not exist, which tests nothing and hides
# the gap it was meant to catch.
KINDS = [k.value for k in AlertKind]
STATUSES = [s.value for s in CaseStatus]
SEVERITIES = [s.value for s in Severity]
CLASSIFICATIONS = [c.value for c in Classification]
# The roles the routing table can actually hand a case to.
ROLES = sorted({role for table in ROUTES.values()
                for role, _assignee in table.values()})


def _masked(source: str) -> str:
    """The source with the contents of strings and comments blanked out.

    Blanked rather than deleted so every index still lines up with the original
    text. Without this a brace or a colon inside a Bengali string would be read
    as structure, and the dictionaries are full of both.
    """
    pattern = re.compile(r"""
          '(?:\\.|[^'\\])*'
        | "(?:\\.|[^"\\])*"
        | /\*.*?\*/
        | //[^\n]*
    """, re.VERBOSE | re.DOTALL)
    return pattern.sub(lambda m: " " * len(m.group(0)), source)


def _brace_body(text: str, start: int) -> str:
    """The text from the ``{`` at ``start`` through its matching ``}``."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise AssertionError("unbalanced braces in app.js")


def _dict_bodies() -> dict[str, str]:
    """The source text of the ``bn`` and ``en`` dictionaries."""
    source = _masked(APP_JS.read_text(encoding="utf-8"))
    head = re.search(r"var STR = \{", source)
    assert head, "no STR dictionary in app.js"
    outer = _brace_body(source, head.end() - 1)
    bodies = {}
    for lang in ("bn", "en"):
        found = re.search(rf"\b{lang}: \{{", outer)
        assert found, f"no {lang} dictionary in app.js"
        bodies[lang] = _brace_body(outer, found.end() - 1)
    return bodies


def _keys(body: str) -> set[str]:
    """The keys defined directly in one dictionary body.

    A key is an identifier followed by a colon at the dictionary's own nesting
    level. Indentation is deliberately not used to decide this: the two
    dictionaries in this file do not agree on it — some English keys sit one
    space deeper than their Bengali twins — so an indent-based rule reports
    translations as missing when they are present and merely misaligned.
    """
    keys: set[str] = set()
    depth = 0
    i = 0
    while i < len(body):
        char = body[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif depth == 1:
            match = re.compile(r"([A-Za-z][A-Za-z0-9_]*)\s*:").match(body, i)
            if match:
                keys.add(match.group(1))
                i = match.end()
                continue
        i += 1
    return keys


def _camel(value: str) -> str:
    return "".join(w.capitalize() for w in value.split("_"))


@pytest.fixture(scope="module")
def dictionaries() -> dict[str, set[str]]:
    return {lang: _keys(body) for lang, body in _dict_bodies().items()}


def test_both_languages_define_the_same_keys(dictionaries):
    """A key in one language and not the other silently borrows the other's text."""
    missing_bn = sorted(dictionaries["en"] - dictionaries["bn"])
    missing_en = sorted(dictionaries["bn"] - dictionaries["en"])
    assert not missing_bn, f"defined in en but not bn: {missing_bn}"
    assert not missing_en, f"defined in bn but not en: {missing_en}"


@pytest.mark.parametrize("kind", KINDS)
def test_every_alert_kind_has_a_label(kind, dictionaries):
    key = "kind" + _camel(kind)
    for lang in ("bn", "en"):
        assert key in dictionaries[lang], f"{key} missing from {lang}"


@pytest.mark.parametrize("status", STATUSES)
def test_every_case_status_has_a_label(status, dictionaries):
    key = "st" + _camel(status)
    for lang in ("bn", "en"):
        assert key in dictionaries[lang], f"{key} missing from {lang}"


@pytest.mark.parametrize("severity", SEVERITIES)
def test_every_severity_has_a_label(severity, dictionaries):
    key = "sev" + severity.capitalize()
    for lang in ("bn", "en"):
        assert key in dictionaries[lang], f"{key} missing from {lang}"


@pytest.mark.parametrize("classification", CLASSIFICATIONS)
def test_every_classification_has_a_label(classification, dictionaries):
    key = "cls" + _camel(classification)
    for lang in ("bn", "en"):
        assert key in dictionaries[lang], f"{key} missing from {lang}"


@pytest.mark.parametrize("role", ROLES)
def test_every_route_role_has_a_label(role, dictionaries):
    """The routing table names these roles; the queue prints them."""
    key = "role" + _camel(role)
    for lang in ("bn", "en"):
        assert key in dictionaries[lang], f"{key} missing from {lang}"


def test_the_label_builders_degrade_to_the_raw_value():
    """An unknown value must not be shown to an operator as an i18n key.

    All five builders share one ``labelFrom`` helper for this reason. If they
    are ever un-shared, the fallback has to travel with them.
    """
    source = APP_JS.read_text(encoding="utf-8")
    assert "function labelFrom(" in source
    assert "translated === prefix + stem ? text : translated" in source
    for builder in ("sevLabel", "kindLabel", "statusLabel", "roleLabel",
                    "clsLabel"):
        body = re.search(rf"function {builder}\(.*?\) \{{(.*?)\}}", source, re.S)
        assert body, f"{builder} not found"
        assert "labelFrom(" in body.group(1), \
            f"{builder} builds its key directly instead of via labelFrom"


INDEX_HTML = Path(__file__).resolve().parents[1] / "static" / "index.html"


def _page_markup() -> str:
    """index.html with its comments blanked.

    A key quoted in a comment explaining the mechanism is not a key the page asks
    for, and reading it as one would make the tests below fail for a reason that
    has nothing to do with the page.
    """
    source = INDEX_HTML.read_text(encoding="utf-8")
    return re.sub(r"<!--.*?-->", lambda m: " " * len(m.group(0)), source,
                  flags=re.DOTALL)


def test_every_static_label_the_page_asks_for_exists_in_both_languages(dictionaries):
    """The static markup and the dictionaries must agree on which keys exist.

    index.html ships English defaults so the page reads correctly before the script
    runs, and applyI18n replaces them on load. A key the page asks for and the
    dictionary does not define leaves the English default in place — a Bengali
    dashboard with one English sentence in it — and nothing used to notice.
    """
    keys = set(re.findall(r'data-i18n="([^"]+)"', _page_markup()))
    assert keys, "no data-i18n attributes found in index.html"
    for lang in ("bn", "en"):
        missing = sorted(keys - dictionaries[lang])
        assert not missing, f"{lang} dictionary is missing {missing}"


def test_every_attribute_label_the_page_asks_for_exists_in_both_languages(dictionaries):
    """The same check for labels translated through an attribute.

    aria-label and title are the strings that reach a screen reader and never an
    eye, so a wrong language or a missing key here is invisible in exactly the way
    that makes it worth a test. The binding is written ``attr:key``, matching what
    applyI18n parses, so the two cannot drift apart.
    """
    specs = []
    for raw in re.findall(r'data-i18n-attr="([^"]+)"', _page_markup()):
        for part in raw.split(","):
            bits = part.split(":")
            attr = bits[0].strip() if len(bits) > 1 else "title"
            specs.append((attr, bits[-1].strip()))
    assert specs, "no data-i18n-attr attributes found in index.html"
    for attr, key in sorted(specs):
        assert attr.startswith("aria-") or attr in ("title", "alt"), \
            f"{key} is bound to {attr!r}, which is not a label attribute"
        for lang in ("bn", "en"):
            assert key in dictionaries[lang], f"{key} missing from {lang}"


def test_the_attribute_translation_is_actually_wired_up():
    """The mechanism, not only the keys: a key nothing reads is not a label.

    applyI18n sets text content on [data-i18n] elements. Attributes need their own
    pass, and if that pass is dropped the markup goes on declaring itself
    translated while every aria-label keeps whatever language the HTML was written
    in — which is the state this pair of tests was added to close.
    """
    source = APP_JS.read_text(encoding="utf-8")
    assert "querySelectorAll('[data-i18n-attr]')" in source
    assert "setAttribute(attr, avalue)" in source
