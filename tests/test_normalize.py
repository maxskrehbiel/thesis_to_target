"""Name, phone, website and ZIP normalization."""

from __future__ import annotations

import pytest

from thesis_to_target.config import ResolveConfig
from thesis_to_target.normalize import (
    BUSINESS_ABBREVIATIONS,
    clean_display_name,
    distinctive_tokens,
    has_legal_suffix,
    name_variants,
    normalize_domain,
    normalize_name,
    normalize_phone,
    split_dba,
    zip5,
)


@pytest.mark.parametrize(
    "variant",
    [
        "Braxmoor Fire Protection, Inc.",
        "BRAXMOOR FIRE PROTECTION LLC",
        "Braxmoor Fire Prot. Svcs",
        "The Braxmoor Fire Protection Services Co.",
        "Braxmoor  Fire Protection Service, L.L.C.",
    ],
)
def test_legal_suffixes_abbreviations_and_case_collapse(
    variant: str, fire_cfg: ResolveConfig
) -> None:
    base = normalize_name("Braxmoor Fire Protection", fire_cfg.abbreviations)
    assert normalize_name(variant, fire_cfg.abbreviations) in (base, f"{base} service")


def test_default_vocabulary_is_industry_neutral(fire_cfg: ResolveConfig) -> None:
    assert normalize_name("Braxmoor Svcs") == "braxmoor service"
    assert normalize_name("Braxmoor Fire Prot.") == "braxmoor fire prot"
    assert (
        normalize_name("Braxmoor Fire Prot.", fire_cfg.abbreviations) == "braxmoor fire protection"
    )
    assert "prot" not in BUSINESS_ABBREVIATIONS


def test_initials_ampersand_and_accents(fire_cfg: ResolveConfig) -> None:
    assert (
        normalize_name("A.B.C. Fire & Safety")
        == normalize_name("ABC Fire and Safety")
        == "abc fire safety"
    )
    assert normalize_name("Quénholt Alarm") == "quenholt alarm"
    assert normalize_name("O'Velt Sprinklers", fire_cfg.abbreviations) == "ovelt sprinkler"


def test_company_word_is_kept_mid_name_but_dropped_at_the_end() -> None:
    assert normalize_name("Company Fire Protection") == "company fire protection"
    assert normalize_name("Veltmere Sprinkler Company") == "veltmere sprinkler"
    assert normalize_name("") == ""
    assert normalize_name(None) == ""


@pytest.mark.parametrize(
    ("raw", "legal", "operating"),
    [
        ("Quenholt Holdings LLC dba Braxmoor Fire", "Quenholt Holdings LLC", "Braxmoor Fire"),
        ("QUENHOLT HOLDINGS, LLC D/B/A BRAXMOOR FIRE", "QUENHOLT HOLDINGS, LLC", "BRAXMOOR FIRE"),
        ("Quenholt Group d.b.a. Braxmoor Fire", "Quenholt Group", "Braxmoor Fire"),
        ("Quenholt Group doing business as Braxmoor Fire", "Quenholt Group", "Braxmoor Fire"),
        ("Quenholt Group (Braxmoor Fire)", "Quenholt Group", "Braxmoor Fire"),
    ],
)
def test_split_dba_forms(raw: str, legal: str, operating: str) -> None:
    assert split_dba(raw) == (legal, operating)


def test_split_dba_leaves_qualifiers_and_plain_names_alone() -> None:
    assert split_dba("Braxmoor Fire (IL)") == ("Braxmoor Fire (IL)", None)
    assert split_dba("Braxmoor Fire (Inc.)") == ("Braxmoor Fire (Inc.)", None)
    assert split_dba("Braxmoor Fire") == ("Braxmoor Fire", None)
    assert split_dba(None) == ("", None)


def test_name_variants_include_embedded_and_separate_dba() -> None:
    variants = name_variants(
        "Quenholt Holdings LLC dba Braxmoor Fire", dba="Braxmoor Fire Protection"
    )
    assert variants == ["quenholt holdings", "braxmoor fire", "braxmoor fire protection"]


def test_clean_display_name() -> None:
    assert clean_display_name("BRAXMOOR FIRE & SAFETY, LLC") == "Braxmoor Fire & Safety, LLC"
    assert clean_display_name("Braxmoor Fire Co., Inc.", drop_legal_suffix=True) == "Braxmoor Fire"
    assert clean_display_name("  Braxmoor   Fire&Alarm  ") == "Braxmoor Fire & Alarm"
    assert clean_display_name(None) == ""


def test_has_legal_suffix() -> None:
    assert has_legal_suffix("Braxmoor Fire, L.L.C.")
    assert has_legal_suffix("Braxmoor Fire Co.")
    assert not has_legal_suffix("Braxmoor Fire Protection")


@pytest.mark.parametrize(
    "raw",
    [
        "(217) 555-0142",
        "217-555-0142",
        "217.555.0142",
        "+1 217 555 0142",
        "1-217-555-0142",
        "2175550142 x12",
    ],
)
def test_normalize_phone_formats(raw: str) -> None:
    assert normalize_phone(raw) == "2175550142"


def test_normalize_phone_rejects_short_numbers() -> None:
    assert normalize_phone("555-0142") is None
    assert normalize_phone(None) is None


@pytest.mark.parametrize(
    ("raw", "host"),
    [
        ("https://www.braxmoorfire.example/about?x=1", "braxmoorfire.example"),
        ("http://BRAXMOORFIRE.example", "braxmoorfire.example"),
        ("www.braxmoorfire.example", "braxmoorfire.example"),
        ("braxmoorfire.example:8080/contact", "braxmoorfire.example"),
        ("not a url", None),
        ("", None),
    ],
)
def test_normalize_domain(raw: str, host: str | None) -> None:
    assert normalize_domain(raw) == host


def test_zip5_and_distinctive_tokens(fire_cfg: ResolveConfig) -> None:
    assert zip5("61204-1234") == "61204"
    assert zip5("612") is None
    assert zip5(None) is None
    assert distinctive_tokens("braxmoor fire protection", fire_cfg.generic_tokens) == ["braxmoor"]
