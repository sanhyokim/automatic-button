"""正規化、キーワード照合、数値の形式チェック、数値の確定判定(純粋な関数)。"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from .models import Rule

_WS_RE = re.compile(r"\s+")
# OCRが取り違えやすい文字をそろえる(キーワード・待機表示の比較に使う)
_CONFUSABLE = str.maketrans({"0": "O", "1": "I", "L": "I", "|": "I", "!": "I"})
_INTEGER_RE = re.compile(r"^(\d{1,3}(,\d{3})+|\d+)$")
_DECIMAL_RE = re.compile(r"^\d+\.\d{2}$")

CONFIRMED = "confirmed"  # 確定値あり
CONTINUE = "continue"  # 読み取り継続
FAILED = "failed"  # 確定不可(避難動作へ)


def normalize(text: Optional[str]) -> str:
    """空白をすべて削除し、大文字に変換する。"""
    if not text:
        return ""
    return _WS_RE.sub("", text).upper()


def canonical(text: Optional[str]) -> str:
    """比較用の形。正規化したうえで、OCRが取り違えやすい文字(0/O、1/I/L など)をそろえる。"""
    return normalize(text).translate(_CONFUSABLE)


def is_waiting(text: Optional[str], waiting_text: str) -> bool:
    """読み取り結果が待機表示かどうか。待機表示の設定が空なら常に False。"""
    target = canonical(waiting_text)
    return bool(target) and canonical(text) == target


def match_rule(text: Optional[str], rules: Iterable[Rule]) -> Optional[Rule]:
    """正規化して完全一致したルールを返す。空文字列は何にも一致しない。"""
    n = canonical(text)
    if not n:
        return None
    for rule in rules:
        if canonical(rule.keyword) == n:
            return rule
    return None


def check_number(text: Optional[str], number_format: str) -> tuple[bool, Optional[str]]:
    """数値の形式チェック(仕様書 5.3節)。(合否, 入力する値) を返す。"""
    s = _WS_RE.sub("", text or "")
    if number_format == "integer":
        if _INTEGER_RE.match(s):
            return True, s.replace(",", "")
        return False, None
    if number_format == "decimal":
        if _DECIMAL_RE.match(s):
            return True, s
        return False, None
    return False, None


@dataclass(frozen=True)
class NumberDecision:
    status: str  # CONFIRMED / CONTINUE / FAILED
    value: Optional[str] = None


def decide_number(
    reads: Sequence[str], number_format: str, max_reads: int, match_count: int
) -> NumberDecision:
    """数値の確定判定(FR-31)。

    reads はこれまでの読み取り結果(OCRの元の文字列)を古い順に並べたもの。
    - いずれかの「入力する値」が match_count 回に達したら CONFIRMED
    - 残りの読み取り回数ではどの値も match_count に届かない、
      または max_reads 回読み終えたら FAILED
    - それ以外は CONTINUE
    """
    counts: Counter[str] = Counter()
    for raw in reads[:max_reads]:
        ok, value = check_number(raw, number_format)
        if ok:
            counts[value] += 1
            if counts[value] >= match_count:
                return NumberDecision(CONFIRMED, value)
    done = min(len(reads), max_reads)
    remaining = max_reads - done
    best = max(counts.values(), default=0)
    if best + remaining < match_count:
        return NumberDecision(FAILED)
    return NumberDecision(CONTINUE)
