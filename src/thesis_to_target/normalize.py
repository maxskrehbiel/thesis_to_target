"""Pure name, phone, website and ZIP normalization used for matching and display."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from types import MappingProxyType

#: Tokens that describe an entity's legal form rather than its identity.
# fmt: off
LEGAL_SUFFIXES = frozenset({
    "inc", "incorporated", "llc", "lc", "co", "company", "corp", "corporation",
    "ltd", "limited", "lp", "llp", "lllp", "pllc", "pc", "plc",
})
# These are removed wherever they appear. The remaining suffixes ("co", "company",
# "limited", ...) are removed only at the end, because mid-name they can be identity.
_ALWAYS_STRIP = frozenset({
    "inc", "incorporated", "llc", "lc", "corp", "corporation", "ltd", "llp", "lllp", "pllc",
})
# fmt: on

STOPWORDS = frozenset({"the", "and", "of"})

#: Industry-neutral abbreviation and plural canonicalization, applied token by token.
#: A thesis extends it with its own vocabulary (see ``resolve.extra_abbreviations``).
# fmt: off
BUSINESS_ABBREVIATIONS: Mapping[str, str] = MappingProxyType({
    "svc": "service", "svcs": "service", "serv": "service", "services": "service",
    "sys": "system", "systems": "system",
    "equip": "equipment", "eqpt": "equipment",
    "natl": "national", "intl": "international",
    "mech": "mechanical", "elec": "electric", "electrical": "electric",
    "contr": "contractor", "contractors": "contractor",
    "bros": "brothers", "assoc": "associates", "mgmt": "management",
})
# fmt: on

_DBA_RE = re.compile(
    r"\s*[,;]?\s*\b(?:d\s*/\s*b\s*/\s*a|d\.\s*b\.\s*a|dba|doing\s+business\s+as|"
    r"a\s*/\s*k\s*/\s*a|aka|t\s*/\s*a|trading\s+as)\b\.?\s*",
    flags=re.IGNORECASE,
)
_PAREN_RE = re.compile(r"^(.*?\S)\s*\(([^()]+)\)\s*$")
# fmt: off
_US_STATES = frozenset({
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN",
    "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV",
    "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN",
    "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
})
# fmt: on
_DISPLAY_SUFFIX_RE = re.compile(
    r"[\s,]+(?:inc\.?|incorporated|l\.?\s?l\.?\s?c\.?|co\.?|company|corp\.?|corporation|ltd\.?)$",
    flags=re.IGNORECASE,
)
_KEEP_UPPER = frozenset({"LLC", "LP", "LLP", "PLLC", "PC", "II", "III", "IV", "USA"})
_KEEP_LOWER = frozenset({"and", "of", "the"})
_APOSTROPHES = "['`" + chr(0x2019) + "]"  # straight, backtick and curly apostrophes
_NANP_LENGTH = 10
_ZIP_LENGTH = 5


def split_dba(name: str | None) -> tuple[str, str | None]:
    """Split a legal name from the operating name it trades under.

    Recognizes ``dba``, ``d/b/a``, ``d.b.a.``, ``doing business as``, ``aka``,
    ``t/a`` and a trailing parenthetical alias.

    Args:
        name: Name as printed by a source.

    Returns:
        ``(legal, operating)``; ``operating`` is ``None`` when there is nothing to split.
    """
    if not name:
        return "", None
    parts = _DBA_RE.split(name, maxsplit=1)
    if len(parts) == 2 and parts[0].strip(" ,;") and parts[1].strip():
        return parts[0].strip(" ,;"), parts[1].strip(" ,;")
    paren = _PAREN_RE.match(name)
    if paren:
        alias = paren.group(2).strip()
        # "(IL)" or "(Inc.)" is a qualifier, not an alias.
        if alias.upper() not in _US_STATES and normalize_name(alias):
            return paren.group(1).strip(" ,;"), alias
    return name.strip(), None


def _merge_initials(tokens: list[str]) -> list[str]:
    """Merge runs of single letters so ``A.B.C.`` matches ``ABC``."""
    out: list[str] = []
    run: list[str] = []
    for tok in [*tokens, ""]:
        if len(tok) == 1 and tok.isalpha():
            run.append(tok)
            continue
        if len(run) >= 2:
            out.append("".join(run))
        else:
            out.extend(run)
        run = []
        if tok:
            out.append(tok)
    return out


def normalize_name(
    name: str | None, abbreviations: Mapping[str, str] = BUSINESS_ABBREVIATIONS
) -> str:
    """Reduce one company name to a lower-case token string for matching.

    Removes accents, punctuation, stop-words and legal suffixes, merges initials
    and canonicalizes abbreviations. Does not split DBAs; see :func:`name_variants`.

    Args:
        name: A single company name.
        abbreviations: Token -> canonical token map, e.g. ``{"svcs": "service"}``.

    Returns:
        Space-separated normalized tokens, or ``""`` for empty input.
    """
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = re.sub(_APOSTROPHES, "", text)
    text = text.replace("&", " and ").replace("+", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = _merge_initials(text.split())
    tokens = [abbreviations.get(t, t) for t in tokens]
    tokens = [t for t in tokens if t not in STOPWORDS and t not in _ALWAYS_STRIP]
    while len(tokens) > 1 and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def name_variants(
    name: str | None,
    dba: str | None = None,
    abbreviations: Mapping[str, str] = BUSINESS_ABBREVIATIONS,
) -> list[str]:
    """List every distinct normalized name a source record is known by.

    Args:
        name: Name as printed by the source (may embed a DBA).
        dba: Separate DBA field, if the source has one.
        abbreviations: Token -> canonical token map passed to :func:`normalize_name`.

    Returns:
        Normalized legal name, embedded alias and DBA field, de-duplicated in that order.
    """
    primary, alias = split_dba(name)
    out: list[str] = []
    for candidate in (primary, alias, dba):
        norm = normalize_name(candidate, abbreviations)
        if norm and norm not in out:
            out.append(norm)
    return out


def distinctive_tokens(normalized: str, generic: frozenset[str]) -> list[str]:
    """Return the tokens of a normalized name that are not generic industry words.

    Args:
        normalized: Output of :func:`normalize_name`.
        generic: Normalized industry words to ignore.

    Returns:
        The remaining tokens, in order.
    """
    return [t for t in normalized.split() if t not in generic]


def _smart_title(text: str) -> str:
    words = []
    for i, word in enumerate(text.split()):
        bare = re.sub(r"[^A-Za-z]", "", word).upper()
        if bare in _KEEP_UPPER or "." in word.rstrip(".,"):  # "L.L.C." but not "INC."
            words.append(word.upper())
        elif i > 0 and word.lower() in _KEEP_LOWER:
            words.append(word.lower())
        else:
            words.append(word[:1].upper() + word[1:].lower())
    return " ".join(words)


def clean_display_name(name: str | None, *, drop_legal_suffix: bool = False) -> str:
    """Tidy a name for display without changing its words.

    Args:
        name: Name as printed by a source.
        drop_legal_suffix: Also remove trailing ``Inc.``/``LLC``/``Co.`` etc.

    Returns:
        The name with normalized spacing and ALL-CAPS converted to title case.
    """
    if not name:
        return ""
    text = re.sub(r"\s*&\s*", " & ", name.strip())
    text = re.sub(r"\s+", " ", text).strip(" ,;-")
    letters = [c for c in text if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        text = _smart_title(text)
    if drop_legal_suffix:
        previous = None
        while previous != text:
            previous = text
            text = _DISPLAY_SUFFIX_RE.sub("", text).strip(" ,;-") or text
    return text


def has_legal_suffix(name: str) -> bool:
    """Return True when a printed name carries a legal-form token such as ``LLC``.

    Args:
        name: Name as printed by a source.

    Returns:
        Whether any token, ignoring periods and commas, is a legal suffix.
    """
    tokens = [t.strip(",;").lower() for t in name.replace(".", "").split()]
    return any(t in LEGAL_SUFFIXES for t in tokens)


def normalize_phone(phone: str | None) -> str | None:
    """Reduce a US phone number to ten digits.

    Args:
        phone: Phone number in any common format; digits past the tenth are
            treated as an extension.

    Returns:
        Ten digits, or ``None`` when fewer than ten digits are present.
    """
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if len(digits) > _NANP_LENGTH and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) < _NANP_LENGTH:
        return None
    return digits[:_NANP_LENGTH]


def normalize_domain(url: str | None) -> str | None:
    """Reduce a URL to its lower-case host without ``www.``, path, port or query.

    Offline by design (no public-suffix list), so subdomains other than ``www`` are kept.

    Args:
        url: URL or bare host.

    Returns:
        The host, or ``None`` when the input does not look like a host name.
    """
    if not url:
        return None
    host = url.strip().lower()
    host = re.sub(r"^[a-z][a-z0-9+.-]*://", "", host)
    host = re.split(r"[/?#]", host, maxsplit=1)[0]
    host = host.rsplit("@", 1)[-1].split(":", 1)[0].strip(".")
    host = host.removeprefix("www.")
    if "." not in host or not re.fullmatch(r"[a-z0-9.-]+", host):
        return None
    return host


def zip5(zip_code: str | None) -> str | None:
    """Return the first five digits of a ZIP or ZIP+4 code.

    Args:
        zip_code: ZIP code in any format.

    Returns:
        Five digits, or ``None`` when fewer are present.
    """
    if not zip_code:
        return None
    digits = re.sub(r"\D", "", zip_code)
    return digits[:_ZIP_LENGTH] if len(digits) >= _ZIP_LENGTH else None
