from datetime import date

import numpy as np
import pytest

from ml_common import parsers

# --- Dirty type 6: mixed plain numbers and "$xxx,xxx" strings ---

@pytest.mark.parametrize(
    "input,expected",
    [
        ("$450,000", 450000.0),
        ("$1,250,000", 1250000.0),
        ("$999", 999.0),
        ("450000", 450000.0),
        (450000, 450000.0),
        (450000.75, 450000.75),
        ("  $450,000  ", 450000.0),
        ("$450,000.50", 450000.50),
    ],
)
def test_parse_money_with_multiple_input_format(input, expected):
    assert parsers.parse_money(input) == expected


@pytest.mark.parametrize("input", [None, "", "   ", np.nan, "Not number", "$"])
def test_parse_money_invalid_input_expect_return_none(input):
    assert parsers.parse_money(input) is None


# --- Dirty type 4: has_pool has 8 different representations ---

@pytest.mark.parametrize(
    "input,expected",
    [
        ("Yes", True), ("No", False),
        ("Y", True), ("N", False),
        ("1", True), ("0", False),
        ("True", True), ("False", False),
        ("yes", True), ("NO", False),
        ("  Y  ", True),
        (1, True), (0, False),
        (True, True), (False, False),
        (1.0, True), (0.0, False),
    ],
)
def test_parse_bool_every_representation(input, expected):
    assert parsers.parse_bool(input) is expected


@pytest.mark.parametrize("input", [None, "", "   ", np.nan, "maybe", "2"])
def test_parse_bool_invalid_input_expect_return_none(input):
    assert parsers.parse_bool(input) is None


# --- Dirty type 5: listing_date has 3 formats ---

@pytest.mark.parametrize(
    "input,expected",
    [
        ("2023-07-15", date(2023, 7, 15)),
        ("07/15/2023", date(2023, 7, 15)),
        ("15-Jul-2023", date(2023, 7, 15)),
        ("  2023-07-15  ", date(2023, 7, 15)),
        ("01/02/2023", date(2023, 1, 2)),  # MM/DD, not DD/MM
        ("03-Mar-2020", date(2020, 3, 3)),
    ],
)
def test_parse_date_three_formats(input, expected):
    assert parsers.parse_date(input) == expected


@pytest.mark.parametrize("input", [None, "", "   ", np.nan, "not a date", "2023-13-45"])
def test_parse_date_invalid_input_expect_return_none(input):
    assert parsers.parse_date(input) is None


def test_parse_date_accepts_existing_date_object():
    assert parsers.parse_date(date(2023, 7, 15)) == date(2023, 7, 15)


# --- Dirty type 8: zipcode missing or truncated to 4 digits ---

@pytest.mark.parametrize(
    "input,expected",
    [
        ("90210", "90210"),
        ("  90210  ", "90210"),
        (90210, "90210"),
        ("02134", "02134"),  # leading 0 must not be lost
    ],
)
def test_parse_zipcode_valid_input(input, expected):
    assert parsers.parse_zipcode(input) == expected


@pytest.mark.parametrize("input", [None, "", "9021", "902101", "abcde", np.nan, 9021])
def test_parse_zipcode_invalid_format_expect_return_none(input):
    assert parsers.parse_zipcode(input) is None


def test_parse_zipcode_integer_with_lost_leading_zero_is_not_recovered():
    # 2134 in the CSV is very likely 02134 with its leading zero stripped by Excel.
    # We do NOT guess: return None so validate can count and report it.
    assert parsers.parse_zipcode(2134) is None


# --- Dirty type 3: categorical mixing upper/lower case and separators ---

@pytest.mark.parametrize(
    "input,expected",
    [
        ("NEW YORK", "new york"),
        ("new york", "new york"),
        ("New_York", "new york"),
        ("  New York  ", "new york"),
        ("New-York", "new york"),
        ("SINGLE FAMILY", "single family"),
        ("Single_Family", "single family"),
        ("Multi-Family", "multi family"),
        ("MULTI FAMILY", "multi family"),
        ("multi_family", "multi family"),
        ("New   York", "new york"),  # multiple spaces -> one
        ("CA", "ca"),
    ],
)
def test_normalize_text(input, expected):
    assert parsers.normalize_text(input) == expected


@pytest.mark.parametrize("input", [None, "", "   ", np.nan])
def test_normalize_text_empty_input_expect_return_none(input):
    assert parsers.normalize_text(input) is None


def test_every_multi_family_variant_normalizes_to_the_same_value():
    variants = ["Multi-Family", "MULTI FAMILY", "multi_family", "  Multi Family  "]
    result = {parsers.normalize_text(v) for v in variants}
    assert result == {"multi family"}
