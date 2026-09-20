"""Parse functions for individual raw values.

Each function takes an arbitrary value (string, number, None, NaN) and
returns a normalized value, or None if it could not be parsed. Never raises
an exception and never guesses: an ambiguous value returns None so the
`validate` stage can count and report it.

This module does not import pandas or sklearn — just pure functions, tested
with parametrized tables.
"""

from __future__ import annotations

import re
from datetime import date, datetime

_MONEY_NOISE_CHARS = re.compile(r"[$,\s]")
_ONLY_DIGITS = re.compile(r"^-?\d+(\.\d+)?$")
_VALID_ZIPCODE = re.compile(r"^\d{5}$")
_EXTRA_SPACES = re.compile(r"\s+")

_BOOL_TRUE = {"yes", "y", "1", "true", "t"}
_BOOL_FALSE = {"no", "n", "0", "false", "f"}

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y")


def _is_empty(value: object) -> bool:
    """Decides whether a value counts as missing.

    Args:
        value: any raw value straight from the file.

    Returns:
        True for None, NaN, and a string that is empty or whitespace-only.

    Example:
        _is_empty(None)           # -> True
        _is_empty(float("nan"))   # -> True
        _is_empty("   ")          # -> True
        _is_empty(0)              # -> False, zero is a value, not a gap
        _is_empty("0")            # -> False
    """
    if value is None:
        return True
    # NaN is the only float that doesn't equal itself.
    if isinstance(value, float) and value != value:
        return True
    return isinstance(value, str) and not value.strip()


def parse_money(value: object) -> float | None:
    """Parses a money amount: '$450,000' -> 450000.0.

    Handles dirty type 6: the same column mixes plain numbers with
    currency-formatted strings.

    Args:
        value: a number, or a string that may carry '$', commas and spaces.

    Returns:
        The amount as a float, or None when the value is missing or carries
        anything that is not a number once '$', commas and spaces are stripped.
        A bool returns None: True is not an amount of money.

    Example:
        parse_money("$450,000")       # -> 450000.0
        parse_money("450,000.50")     # -> 450000.5
        parse_money(450000)           # -> 450000.0
        parse_money("call for price") # -> None
        parse_money(True)             # -> None
    """
    if _is_empty(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _MONEY_NOISE_CHARS.sub("", str(value))
    if not _ONLY_DIGITS.match(text):
        return None
    return float(text)


def parse_bool(value: object) -> bool | None:
    """Parses a boolean from the 8 representations this dataset uses.

    Handles dirty type 4: has_pool has Yes/No/Y/N/1/0/True/False.

    Args:
        value: a bool, a 0/1 number, or a string in any case.

    Returns:
        True or False, or None when the value is missing or is a number other
        than 0 or 1 — 2 is not a truth value and guessing would invent data.

    Example:
        parse_bool("Yes")    # -> True
        parse_bool("N")      # -> False
        parse_bool("TRUE")   # -> True
        parse_bool(1)        # -> True
        parse_bool(2)        # -> None
        parse_bool("maybe")  # -> None
    """
    if _is_empty(value):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False
        return None
    text = str(value).strip().lower()
    if text in _BOOL_TRUE:
        return True
    if text in _BOOL_FALSE:
        return False
    return None


def parse_date(value: object) -> date | None:
    """Parses a date from the 3 formats mixed into this dataset.

    Handles dirty type 5: YYYY-MM-DD, MM/DD/YYYY, DD-Mon-YYYY.
    Tries each format in turn instead of using dateutil: much faster over
    2 million rows, and never mistakes DD/MM for MM/DD.

    Args:
        value: a date, a datetime, or a string in one of the 3 formats.

    Returns:
        A `datetime.date`, or None when the value is missing or matches none of
        the 3 formats. A datetime keeps only its date part.

    Example:
        parse_date("2026-09-20")   # -> date(2026, 9, 20)
        parse_date("09/20/2026")   # -> date(2026, 9, 20)
        parse_date("20-Sep-2026")  # -> date(2026, 9, 20)
        parse_date("20/09/2026")   # -> None, day-first is never assumed
    """
    if _is_empty(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_zipcode(value: object) -> str | None:
    """Parses a 5-digit zipcode.

    Handles dirty type 8. A 4-digit zipcode returns None instead of guessing
    a leading zero: guessing would silently produce wrong data, while None
    lets the `validate` stage count and report it.

    Args:
        value: a string, or a whole number read from a numeric column.

    Returns:
        The zipcode as a 5-character string, or None when the value is missing
        or is not exactly 5 digits.

    Example:
        parse_zipcode("02134")  # -> "02134"
        parse_zipcode(94107.0)  # -> "94107", read back from a numeric column
        parse_zipcode(2134)     # -> None, the leading zero is NOT invented
        parse_zipcode("9410")   # -> None
    """
    if _is_empty(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if value != int(value):
            return None
        value = int(value)
    text = str(value).strip()
    if not _VALID_ZIPCODE.match(text):
        return None
    return text


def normalize_text(value: object) -> str | None:
    """Normalizes a categorical value to lowercase with single spaces.

    Handles dirty type 3: 'NEW YORK', 'new_york', 'New-York', '  New York  '
    all normalize to 'new york'. Underscores and hyphens become spaces so
    every variant of 'Multi-Family' converges to the same value.

    Args:
        value: any raw categorical value.

    Returns:
        The normalized string, or None when the value is missing or normalizes
        to nothing at all (a string of only underscores, say).

    Example:
        normalize_text("Multi-Family")   # -> "multi family"
        normalize_text("MULTI FAMILY")   # -> "multi family"
        normalize_text("multi_family")   # -> "multi family"
        normalize_text("  New   York ")  # -> "new york"
        normalize_text("___")            # -> None
    """
    if _is_empty(value):
        return None
    text = str(value).strip().lower()
    text = text.replace("_", " ").replace("-", " ")
    text = _EXTRA_SPACES.sub(" ", text).strip()
    return text or None
