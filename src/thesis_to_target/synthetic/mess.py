"""Realistic damage applied to generated names and contacts: abbreviations, typos, formats."""

from __future__ import annotations

import re

from .draws import Draws
from .vocabulary import EMPLOYEE_BANDS, LEGAL_SUFFIXES, NAME_ABBREVIATIONS

# Words of at least this many letters can receive a typo.
_TYPO_MIN_LETTERS = 5


def abbreviate(name: str, draws: Draws, max_words: int = 2) -> str:
    """Abbreviate up to ``max_words`` words the way directories do (``Protection`` -> ``Prot.``).

    Args:
        name: Name to abbreviate.
        draws: Random source.
        max_words: Most words changed in one name.

    Returns:
        The abbreviated name, or ``name`` unchanged if nothing applies.
    """
    options = [(src, alts) for src, alts in NAME_ABBREVIATIONS if re.search(rf"\b{src}\b", name)]
    if "&" in name:
        options.append(("&", ("and",)))
    elif " and " in name:
        options.append(("and", ("&",)))
    for src, alts in draws.sample(options, draws.integer(1, max_words)):
        name = re.sub(rf"(?<!\w){re.escape(src)}(?!\w)", draws.choice(alts), name, count=1)
    return name


def typo(name: str, draws: Draws, swap_share: float = 0.5) -> str:
    """Swap two interior letters, or drop one, in a word of five or more letters.

    Args:
        name: Name to damage.
        draws: Random source.
        swap_share: Probability of a swap rather than a dropped letter.

    Returns:
        The name with one typo, or unchanged if no word is long enough.
    """
    words = name.split()
    candidates = [i for i, w in enumerate(words) if len(w) >= _TYPO_MIN_LETTERS and w.isalpha()]
    if not candidates:
        return name
    i = draws.choice(candidates)
    w = words[i]
    j = draws.integer(1, len(w) - 2)
    words[i] = (
        w[:j] + w[j + 1] + w[j] + w[j + 2 :] if draws.chance(swap_share) else w[:j] + w[j + 1 :]
    )
    return " ".join(words)


def with_suffix(name: str, draws: Draws) -> str:
    """Append a random legal suffix, avoiding ``Co. Co.`` style doubles."""
    choices = [s for s in LEGAL_SUFFIXES if not (name.endswith(" Co") and s in ("Co.", "Company"))]
    return f"{name}{draws.choice((', ', ' '))}{draws.choice(choices)}"


def format_phone(digits: str, draws: Draws) -> str:
    """Print a ten-digit number in one of several common styles."""
    a, b, c = digits[:3], digits[3:6], digits[6:]
    return draws.choice(
        (
            f"({a}) {b}-{c}",
            f"{a}-{b}-{c}",
            f"{a}.{b}.{c}",
            f"+1 {a} {b} {c}",
            f"1-{a}-{b}-{c}",
            digits,
        )
    )


def format_website(domain: str, draws: Draws) -> str:
    """Print a host as one of several common URL spellings."""
    return draws.choice(
        (
            f"https://www.{domain}/",
            f"http://{domain}",
            f"www.{domain}",
            f"https://{domain}/about",
            domain,
        )
    )


def band_label(employees: int, draws: Draws, noise: float) -> str:
    """Return the census-style employee band, one band off with probability ``noise``."""
    idx = next(
        (i for i, (_lo, hi) in enumerate(EMPLOYEE_BANDS) if employees <= hi),
        len(EMPLOYEE_BANDS) - 1,
    )
    if draws.chance(noise):
        idx = min(max(idx + draws.choice((-1, 1)), 0), len(EMPLOYEE_BANDS) - 1)
    lo, hi = EMPLOYEE_BANDS[idx]
    return f"{lo}+" if idx == len(EMPLOYEE_BANDS) - 1 else f"{lo}-{hi}"
