import pytest

from app import parser
from app.models import Rule
from app.parser import CONFIRMED, CONTINUE, FAILED, check_number, decide_number, normalize


# T-01
@pytest.mark.parametrize("raw", [" sky ", "Sk Y", "sky", "S\tK\nY"])
def test_normalize(raw):
    assert normalize(raw) == "SKY"


def test_normalize_empty():
    assert normalize("") == ""
    assert normalize(None) == ""


# T-02
def test_match_rule():
    rules = [Rule(name="SKY", keyword="SKY"), Rule(name="SEA", keyword="sea")]
    assert parser.match_rule("sky", rules).name == "SKY"
    assert parser.match_rule(" S e a ", rules).name == "SEA"
    assert parser.match_rule("SKY1", rules) is None
    assert parser.match_rule("SK", rules) is None
    assert parser.match_rule("", rules) is None
    assert parser.match_rule("WAITING", rules) is None
    assert parser.is_waiting("WAITING", "WAITING")
    assert parser.is_waiting("wait ing", "WAITING")
    assert not parser.is_waiting("SKY", "WAITING")
    assert not parser.is_waiting("", "WAITING")
    assert not parser.is_waiting("", "")


# T-03
@pytest.mark.parametrize(
    "raw,value", [("1250", "1250"), ("1,250", "1250"), ("12,345,678", "12345678"), ("0", "0"), (" 1 250 ", "1250")]
)
def test_integer_ok(raw, value):
    assert check_number(raw, "integer") == (True, value)


@pytest.mark.parametrize("raw", ["1.250", "12,50", "1,2500", "12a", "", ",250", "1,250,", "-5"])
def test_integer_ng(raw):
    assert check_number(raw, "integer") == (False, None)


# T-04
@pytest.mark.parametrize("raw,value", [("12.50", "12.50"), ("3.00", "3.00"), ("0.05", "0.05")])
def test_decimal_ok(raw, value):
    assert check_number(raw, "decimal") == (True, value)


@pytest.mark.parametrize("raw", ["12.5", "1250", "12,50", "12.500", "1,234.50", ".50", "", "abc"])
def test_decimal_ng(raw):
    assert check_number(raw, "decimal") == (False, None)


# T-05
def run_incrementally(reads, fmt="decimal", max_reads=5, match=3):
    """1回ずつ読み取りを追加し、(判定, 読んだ回数) を返す。"""
    got = []
    for raw in reads:
        got.append(raw)
        d = decide_number(got, fmt, max_reads, match)
        if d.status != CONTINUE:
            return d, len(got)
    return decide_number(got, fmt, max_reads, match), len(got)


def test_decide_confirm_on_third():
    d, n = run_incrementally(["12.50", "12.50", "12.50", "99.99", "99.99"])
    assert (d.status, d.value, n) == (CONFIRMED, "12.50", 3)


def test_decide_skip_invalid():
    d, n = run_incrementally(["12.50", "12.5", "12.50", "12.50"])
    assert (d.status, d.value, n) == (CONFIRMED, "12.50", 4)


def test_decide_majority_fifth_a():
    d, n = run_incrementally(["12.50", "12.80", "12.50", "12.80", "12.50"])
    assert (d.status, d.value, n) == (CONFIRMED, "12.50", 5)


def test_decide_majority_fifth_b():
    d, n = run_incrementally(["12.50", "12.80", "12.50", "12.80", "12.80"])
    assert (d.status, d.value, n) == (CONFIRMED, "12.80", 5)


def test_decide_fail():
    reads = ["12.5", "abc", "12.5", "12.50", "12.80"]
    assert decide_number(reads, "decimal", 5, 3).status == FAILED


def test_decide_early_abort():
    d, n = run_incrementally(["12.5", "abc", "12.5", "12.50", "12.80"])
    assert (d.status, n) == (FAILED, 3)
    assert decide_number(["12.5", "abc"], "decimal", 5, 3).status == CONTINUE


def test_decide_integer_compares_input_value():
    d, n = run_incrementally(["1,250", "1250", "1,250"], fmt="integer")
    assert (d.status, d.value, n) == (CONFIRMED, "1250", 3)
