"""Region、Rule などのデータクラス(GUI・外部機器に依存しない)。"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

PATTERNS = ("A", "B", "C")
NUMBER_FORMATS = ("integer", "decimal")
REGION_KEYS = ("number", "input_field", "button1", "button2")

# パターンごとに必要な範囲(仕様書 6.3節の表)
REQUIRED_REGIONS = {
    "A": ("button1",),
    "B": ("number", "input_field", "button1"),
    "C": ("button1", "button2"),
}

REGION_LABELS = {
    "number": "数値範囲",
    "input_field": "入力欄",
    "button1": "ボタン1",
    "button2": "ボタン2",
}


@dataclass(frozen=True)
class Region:
    """画面上の四角形。左上座標 (x, y) と幅・高さ (w, h)。"""

    x: int
    y: int
    w: int
    h: int

    @classmethod
    def from_dict(cls, d) -> Optional["Region"]:
        """辞書から作る。None や不正な値の場合は None を返す。"""
        if not isinstance(d, dict):
            return None
        try:
            r = cls(int(d["x"]), int(d["y"]), int(d["w"]), int(d["h"]))
        except (KeyError, TypeError, ValueError):
            return None
        if r.w <= 0 or r.h <= 0:
            return None
        return r

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)

    def intersects(self, other: "Region") -> bool:
        """面積を共有する重なりがあれば True(辺が接するだけなら False)。"""
        return (
            self.x < other.x + other.w
            and other.x < self.x + self.w
            and self.y < other.y + other.h
            and other.y < self.y + self.h
        )

    def clamp(self, width: int, height: int) -> Optional["Region"]:
        """画面 (width × height) の内側に切り詰める。内側に何も残らなければ None。"""
        x0 = max(0, self.x)
        y0 = max(0, self.y)
        x1 = min(width, self.x + self.w)
        y1 = min(height, self.y + self.h)
        if x1 <= x0 or y1 <= y0:
            return None
        return Region(x0, y0, x1 - x0, y1 - y0)


@dataclass
class Rule:
    """「キーワード + パターン + 必要な範囲 + 設定」の1組。"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    keyword: str = ""
    pattern: str = "A"
    regions: dict = field(default_factory=lambda: {k: None for k in REGION_KEYS})
    number_format: str = "integer"

    @classmethod
    def from_dict(cls, d: dict) -> "Rule":
        if not isinstance(d, dict):
            raise ValueError("ルールの形式が正しくありません")
        raw_regions = d.get("regions") if isinstance(d.get("regions"), dict) else {}
        regions = {k: Region.from_dict(raw_regions.get(k)) for k in REGION_KEYS}
        rule_id = d.get("id")
        pattern = d.get("pattern")
        fmt = d.get("number_format")
        return cls(
            id=str(rule_id) if rule_id else str(uuid.uuid4()),
            name=str(d.get("name") or ""),
            keyword=str(d.get("keyword") or ""),
            pattern=pattern if pattern in PATTERNS else "A",
            regions=regions,
            number_format=fmt if fmt in NUMBER_FORMATS else "integer",
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "keyword": self.keyword,
            "pattern": self.pattern,
            "regions": {
                k: (self.regions.get(k).to_dict() if self.regions.get(k) else None)
                for k in REGION_KEYS
            },
            "number_format": self.number_format,
        }

    def region(self, key: str) -> Optional[Region]:
        return self.regions.get(key)

    @property
    def display_name(self) -> str:
        return self.name or self.keyword

    def list_label(self) -> str:
        """ルール一覧の表示(例: 'SKY | A')。"""
        return f"{self.display_name} | {self.pattern}"
