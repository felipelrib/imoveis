"""Frontend message-catalog contract (NFR-7 + v0.13-s2.6).

Three guards, all catalog-side so they run in ``validate.sh fast`` without a
frontend test runner:

1. **Parity** — every catalog carries the same dotted key set and the same
   ``{placeholder}`` set per key as ``en``. A string added to one catalog only
   would show English inside a pt-BR session (pt-BR is the product default
   since v0.13-s1.6), so a one-sided key is a defect, not a TODO.
2. **Pairing** — every ``…One`` key has a ``…Many`` sibling interpolating the
   same placeholders, in every catalog. This is the structural half: it holds
   for count keys this story never touched, and for ones added later.
3. **Plural pins** — the four count-bearing keys this story split are pinned
   verbatim. Interpolating a count into a hardcoded plural noun rendered
   ``1 imóveis`` / ``1 selecionados`` to every user.

Scope limit, deliberately: these are *copy* locks, not *behaviour* locks. They
cannot tell that a noun ought to agree with its count, so a newly added
``"{n} salvos"`` passes all three. Only splitting a key and selecting at the
call site fixes agreement; these tests keep the split from silently rotting.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_LOCALES = _REPO / "frontend" / "src" / "i18n" / "locales"
_REFERENCE_LOCALE = "en"

_PLACEHOLDER = re.compile(r"\{(\w+)\}")

# Exact values the UI must render, per catalog. `n === 1` selects `…One`;
# everything else (including 0) selects `…Many`.
_PLURAL_PINS: dict[str, dict[str, str]] = {
    "en": {
        "common.bedsShortOne": "{n} bed",
        "common.bedsShortMany": "{n} beds",
        "properties.countPropertiesOne": "{n} property",
        "properties.countPropertiesMany": "{n} properties",
        "properties.countFavouritedOne": "{n} favourited",
        "properties.countFavouritedMany": "{n} favourited",
        "properties.compareSelectedOne": "{n} selected",
        "properties.compareSelectedMany": "{n} selected",
    },
    "pt-BR": {
        "common.bedsShortOne": "{n} quarto",
        "common.bedsShortMany": "{n} quartos",
        "properties.countPropertiesOne": "{n} imóvel",
        "properties.countPropertiesMany": "{n} imóveis",
        "properties.countFavouritedOne": "{n} favorito",
        "properties.countFavouritedMany": "{n} favoritos",
        "properties.compareSelectedOne": "{n} selecionado",
        "properties.compareSelectedMany": "{n} selecionados",
    },
}

# Keys the `…One`/`…Many` pairing check must not treat as one half of a pair.
# Both are matched only because they happen to end in "One": they are whole
# fixed sentences with no `{n}`, selected instead of `operations.throughputLine`
# — `throughputOne` is the exact-one form ("ritmo: ~1 imóvel/dia") and
# `throughputBelowOne` is a *below*-one form ("ritmo: menos de 1 imóvel/dia"),
# not a singular at all. See `frontend/src/components/operations/lines.ts`.
#
# The suffix rule cuts the other way too: `operations.etaOneDay` is a genuine
# singular that the check never sees, because the key does not end in "One".
# The pairing invariant is a cheap structural net, not a complete one.
_UNPAIRED_SINGULAR_KEYS = frozenset(
    {
        "operations.throughputOne",
        "operations.throughputBelowOne",
    }
)

# The unsplit keys these pairs replaced — a reappearance means a call site is
# back to interpolating a count into a fixed plural noun.
_RETIRED_KEYS = (
    "common.bedsShort",
    "properties.countProperties",
    "properties.countFavourited",
    "properties.compareSelected",
)


def _flatten(node: object, prefix: str = "") -> dict[str, str]:
    """Flatten a nested catalog into ``{"a.b": "value"}``.

    Strict on purpose: a non-string leaf, or two paths colliding on one dotted
    key, would make a value invisible to every check below rather than failing.
    """
    out: dict[str, str] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            for flat, leaf in _flatten(value, f"{prefix}{key}.").items():
                assert flat not in out, f"duplicate flattened key {flat!r}"
                out[flat] = leaf
        return out
    flat = prefix.rstrip(".")
    assert isinstance(node, str), f"{flat!r}: catalog leaves must be strings, got {type(node).__name__}"
    return {flat: node}


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """``json.loads`` keeps the last of two identical keys; refuse instead.

    Without this, a key duplicated inside one catalog object (an easy merge
    artefact) silently wins over its twin and `_flatten` never sees the
    collision it exists to catch.
    """
    seen: set[str] = set()
    for key, _ in pairs:
        assert key not in seen, f"duplicate JSON key {key!r} in the same object"
        seen.add(key)
    return dict(pairs)


def _catalog(locale: str) -> dict[str, str]:
    path = _LOCALES / f"{locale}.json"
    return _flatten(
        json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_json_keys)
    )


def _locales() -> list[str]:
    """Every catalog on disk, so a new locale is covered the day it lands."""
    return sorted(path.stem for path in _LOCALES.glob("*.json"))


def _non_reference_locales() -> list[str]:
    return [locale for locale in _locales() if locale != _REFERENCE_LOCALE]


@pytest.mark.unit
def test_reference_catalog_exists():
    """Parity is defined against `en`; without it the suite would pass vacuously."""
    assert _REFERENCE_LOCALE in _locales(), f"missing {_REFERENCE_LOCALE}.json in {_LOCALES}"


@pytest.mark.unit
def test_a_second_catalog_exists_to_compare_against():
    """The parity tests are parametrized over the non-`en` catalogs.

    An empty parameter list makes pytest *skip* them rather than fail, so
    losing `pt-BR.json` would quietly retire the NFR-7 guard instead of
    tripping it. This is the check that cannot be skipped away.
    """
    assert _non_reference_locales(), (
        f"no catalog besides {_REFERENCE_LOCALE}.json in {_LOCALES} — the parity "
        "tests would skip, not fail (pt-BR is the product default since v0.13-s1.6)."
    )


@pytest.mark.unit
@pytest.mark.parametrize("locale", _non_reference_locales())
def test_catalog_key_sets_match_reference(locale: str):
    """Every string exists in every catalog (NFR-7)."""
    reference = _catalog(_REFERENCE_LOCALE)
    catalog = _catalog(locale)

    only_reference = sorted(set(reference) - set(catalog))
    only_locale = sorted(set(catalog) - set(reference))
    assert not only_reference and not only_locale, (
        f"Message catalogs drifted — every string lands in both (NFR-7).\n"
        f"  {_REFERENCE_LOCALE} only: {only_reference}\n"
        f"  {locale} only: {only_locale}"
    )


@pytest.mark.unit
@pytest.mark.parametrize("locale", _non_reference_locales())
def test_catalog_placeholders_match_per_key(locale: str):
    """A key interpolates the same ``{placeholder}`` names in every catalog."""
    reference = _catalog(_REFERENCE_LOCALE)
    catalog = _catalog(locale)

    mismatched = [
        f"{key}: {_REFERENCE_LOCALE}={sorted(set(_PLACEHOLDER.findall(reference[key])))} "
        f"{locale}={sorted(set(_PLACEHOLDER.findall(catalog[key])))}"
        for key in sorted(set(reference) & set(catalog))
        if set(_PLACEHOLDER.findall(reference[key])) != set(_PLACEHOLDER.findall(catalog[key]))
    ]
    assert not mismatched, "Placeholder sets differ between catalogs:\n" + "\n".join(mismatched)


@pytest.mark.unit
@pytest.mark.parametrize("locale", _locales())
def test_singular_keys_have_a_plural_sibling(locale: str):
    """Every ``…One`` key pairs with a ``…Many`` that interpolates the same names.

    A missing sibling is not a cosmetic gap: ``t()`` falls back to `en` and then
    to the raw key, so the call site would render English — or the literal
    ``properties.countPropertiesMany`` — inside a pt-BR session.
    """
    catalog = _catalog(locale)

    singulars = [
        key for key in sorted(catalog) if key.endswith("One") and key not in _UNPAIRED_SINGULAR_KEYS
    ]

    orphans = [key for key in singulars if f"{key[:-3]}Many" not in catalog]
    assert not orphans, (
        f"{locale}: `…One` keys with no `…Many` sibling: {orphans} — add the sibling, "
        "or record the differently-named partner in _UNPAIRED_SINGULAR_KEYS."
    )

    # The mirror image, and the likelier half to be forgotten: a call site's
    # `n === 1` arm is the one that goes missing when only the plural is added.
    orphan_plurals = [
        key for key in sorted(catalog) if key.endswith("Many") and f"{key[:-4]}One" not in catalog
    ]
    assert not orphan_plurals, (
        f"{locale}: `…Many` keys with no `…One` sibling: {orphan_plurals} — the "
        "singular arm of the call-site ternary would render the raw dotted key."
    )

    mismatched = [
        f"{key[:-3]}: One={sorted(set(_PLACEHOLDER.findall(catalog[key])))} "
        f"Many={sorted(set(_PLACEHOLDER.findall(catalog[f'{key[:-3]}Many'])))}"
        for key in singulars
        if set(_PLACEHOLDER.findall(catalog[key]))
        != set(_PLACEHOLDER.findall(catalog[f"{key[:-3]}Many"]))
    ]
    assert not mismatched, (
        f"{locale}: a One/Many pair interpolates different placeholders — the call "
        "site passes one params object to both:\n" + "\n".join(mismatched)
    )


@pytest.mark.unit
@pytest.mark.parametrize("locale", sorted(_PLURAL_PINS))
def test_count_keys_are_split_into_singular_and_plural(locale: str):
    """The count-bearing keys render an agreeing noun, verbatim."""
    catalog = _catalog(locale)
    for key, expected in _PLURAL_PINS[locale].items():
        assert catalog.get(key) == expected, (
            f"{locale}.{key} must read exactly {expected!r} — the call site picks the "
            "form with `n === 1`, so the copy itself carries the agreement."
        )


@pytest.mark.unit
@pytest.mark.parametrize("locale", _locales())
def test_unsplit_count_keys_are_gone(locale: str):
    """No catalog keeps the old count-into-fixed-plural key."""
    catalog = _catalog(locale)
    still_present = [key for key in _RETIRED_KEYS if key in catalog]
    assert not still_present, (
        f"{locale}: retired keys reappeared {still_present} — use the "
        "`…One`/`…Many` pair and select at the call site."
    )


def _frontend_sources() -> list[Path]:
    """Every frontend source file that could name a catalog key.

    One glob per extension on purpose: ``Path.glob`` does **not** expand
    brace patterns, so a `*.{ts,tsx}` spelling silently matches nothing.
    """
    sources: list[Path] = []
    for suffix in ("ts", "tsx", "js", "jsx"):
        sources.extend((_REPO / "frontend" / "src").rglob(f"*.{suffix}"))
    return sorted(sources)


@pytest.mark.unit
def test_no_call_site_still_names_a_retired_key():
    """The other half of the retired-key guard: the call sites, not the catalogs.

    Deleting a key from every catalog does not make its call site fail — `t()`
    falls back to the raw key (`frontend/src/i18n/index.ts`), so a resurrected
    `t('properties.countProperties')` renders that dotted string to the user
    instead of a count. Only a source scan catches that direction.
    """
    sources = _frontend_sources()
    assert sources, f"no frontend sources found under {_REPO / 'frontend' / 'src'} — this guard must not pass vacuously"

    # Quoted, so `common.bedsShort` does not match `common.bedsShortOne`.
    patterns = {key: re.compile(rf"""['"`]{re.escape(key)}['"`]""") for key in _RETIRED_KEYS}

    offenders: list[str] = []
    for path in sources:
        content = path.read_text(encoding="utf-8")
        for number, line in enumerate(content.splitlines(), start=1):
            for key, pattern in patterns.items():
                if pattern.search(line):
                    offenders.append(f"{path.relative_to(_REPO)}:{number}: {key}")

    assert not offenders, (
        "Call sites still name a retired count key — they would render the raw "
        "dotted key. Select the `…One`/`…Many` pair with `n === 1`:\n" + "\n".join(offenders)
    )
