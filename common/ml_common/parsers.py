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
    """True if the value counts as missing: None, NaN, empty or whitespace-only string."""
    if value is None:
        return True
    # NaN is the only float that doesn't equal itself.
    if isinstance(value, float) and value != value:
        return True
    return isinstance(value, str) and not value.strip()


def parse_money(value: object) -> float | None:
    """Parse a money amount: '$450,000' -> 450000.0. Returns None if unparseable.

    Handles dirty type 6: the same column mixes plain numbers with
    currency-formatted strings.
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
    """Parse a boolean from 8 possible representations. Returns None if unparseable.

    Handles dirty type 4: has_pool has Yes/No/Y/N/1/0/True/False.
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
    """Parse a date from 3 mixed formats. Returns None if unparseable.

    Handles dirty type 5: YYYY-MM-DD, MM/DD/YYYY, DD-Mon-YYYY.
    Tries each format in turn instead of using dateutil: much faster over
    2 million rows, and never mistakes DD/MM for MM/DD.
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
    """Parse a 5-digit zipcode. Returns None if missing or badly formatted.

    Handles dirty type 8. A 4-digit zipcode returns None instead of guessing
    a leading zero: guessing would silently produce wrong data, while None
    lets the `validate` stage count and report it.
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
    """Normalize a categorical value to lowercase, single spaces.

    Handles dirty type 3: 'NEW YORK', 'new_york', 'New-York', '  New York  '
    all normalize to 'new york'. Underscores and hyphens become spaces so
    every variant of 'Multi-Family' converges to the same value.
    """
    if _is_empty(value):
        return None
    text = str(value).strip().lower()
    text = text.replace("_", " ").replace("-", " ")
    text = _EXTRA_SPACES.sub(" ", text).strip()
    return text or None
