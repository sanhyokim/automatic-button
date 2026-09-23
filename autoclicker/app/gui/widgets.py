"""GUI で共通に使う部品。"""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from ..models import Region

WIDTH = 275  # すべてのウィンドウの幅(GUI-01, GUI-10, GUI-20)


class RegionField(ttk.Frame):
    """範囲の項目:「範囲を設定」ボタンと数値欄(x, y, w, h)。数値欄は直接書き換えられる。"""

    def __init__(
        self,
        master,
        label: str,
        on_pick: Callable[[], Optional[Region]],
        on_test: Optional[Callable[[], None]] = None,
    ):
        super().__init__(master)
        self._on_pick = on_pick
        self.label = label
        head = ttk.Frame(self)
        head.pack(fill="x")
        ttk.Label(head, text=label).pack(side="left")
        if on_test is not None:
            ttk.Button(head, text="読み取りテスト", command=on_test).pack(side="right")
        ttk.Button(head, text="範囲を設定", command=self._pick).pack(side="right", padx=(0, 2))
        body = ttk.Frame(self)
        body.pack(fill="x", pady=(1, 0))
        self.vars = {}
        for key in ("x", "y", "w", "h"):
            ttk.Label(body, text=key).pack(side="left")
            var = tk.StringVar()
            ttk.Entry(body, textvariable=var, width=5).pack(side="left", padx=(1, 4))
            self.vars[key] = var

    def _pick(self) -> None:
        region = self._on_pick()
        if region is not None:
            self.set(region)

    def set(self, region: Optional[Region]) -> None:
        for key in ("x", "y", "w", "h"):
            self.vars[key].set("" if region is None else str(getattr(region, key)))

    def get(self) -> Optional[Region]:
        """範囲を返す。すべて空なら None。不正な値なら ValueError。"""
        texts = {k: v.get().strip() for k, v in self.vars.items()}
        if not any(texts.values()):
            return None
        try:
            vals = {k: int(t) for k, t in texts.items()}
        except ValueError:
            raise ValueError(f"{self.label}の数値が正しくありません") from None
        if vals["w"] <= 0 or vals["h"] <= 0:
            raise ValueError(f"{self.label}の幅と高さは1以上にしてください")
        return Region(vals["x"], vals["y"], vals["w"], vals["h"])


def fit_window(win: tk.Toplevel, x: int, y: int) -> None:
    """幅を WIDTH に固定し、高さを内容に合わせる。"""
    win.update_idletasks()
    h = win.winfo_reqheight()
    screen_h = win.winfo_screenheight()
    if y + h > screen_h - 40:
        y = max(0, screen_h - 40 - h)
    win.geometry(f"{WIDTH}x{h}+{x}+{y}")


def window_pos(win: tk.Misc) -> tuple[int, int]:
    """ウィンドウの現在の表示位置(外枠の左上)。"""
    m = re.search(r"([+-]-?\d+)([+-]-?\d+)$", win.geometry())
    if m:
        return int(m.group(1)), int(m.group(2))
    return win.winfo_x(), win.winfo_y()
