"""登録済みの範囲を色つきの枠と名前で3秒間表示する(GUI-15)。"""
from __future__ import annotations

import tkinter as tk

from ..models import Region

COLORS = {
    "read": "#00ff66",  # 読み取り範囲
    "click": "#ff4040",  # クリック範囲
    "retreat": "#40a0ff",  # 退避エリア
}
LEGEND = (("read", "読み取り範囲"), ("click", "クリック範囲"), ("retreat", "退避エリア"))
SHOW_MS = 3000


def show_regions(master: tk.Misc, items: list[tuple[str, Region, str]]) -> None:
    """items は (名前, 範囲, 種類) の一覧。種類は read / click / retreat。"""
    top = tk.Toplevel(master)
    top.overrideredirect(True)
    sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
    top.geometry(f"{sw}x{sh}+0+0")
    top.attributes("-topmost", True)
    try:
        top.attributes("-alpha", 0.6)
    except tk.TclError:
        pass
    canvas = tk.Canvas(top, bg="#202020", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    for name, r, kind in items:
        color = COLORS.get(kind, "white")
        canvas.create_rectangle(r.x, r.y, r.x + r.w, r.y + r.h, outline=color, width=3)
        ty = r.y - 3 if r.y > 18 else r.y + r.h + 16
        canvas.create_text(r.x, ty, text=name, fill=color, anchor="sw", font=("", 11, "bold"))
    lx, ly = sw - 20, sh - 60
    for kind, label in reversed(LEGEND):
        canvas.create_text(lx, ly, text=f"■ {label}", fill=COLORS[kind], anchor="e", font=("", 12, "bold"))
        ly -= 22
    if not items:
        canvas.create_text(sw // 2, sh // 2, text="登録済みの範囲がありません", fill="white", font=("", 18, "bold"))
    canvas.bind("<Button-1>", lambda e: top.destroy())
    top.after(SHOW_MS, top.destroy)
