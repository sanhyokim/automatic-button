"""範囲設定のオーバーレイ(GUI-30〜34)。"""
from __future__ import annotations

import tkinter as tk
from typing import Optional

from ..models import Region

MIN_SIZE = 5


def select_region(master: tk.Misc) -> Optional[Region]:
    """画面全体の半透明ウィンドウでドラッグさせ、範囲を返す。キャンセルなら None。

    呼び出し側で、事前に GUI のウィンドウを隠しておくこと。
    """
    top = tk.Toplevel(master)
    top.overrideredirect(True)
    sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
    top.geometry(f"{sw}x{sh}+0+0")
    top.attributes("-topmost", True)
    try:
        top.attributes("-alpha", 0.3)
    except tk.TclError:
        pass
    canvas = tk.Canvas(top, bg="black", highlightthickness=0, cursor="crosshair")
    canvas.pack(fill="both", expand=True)
    canvas.create_text(
        sw // 2, 40, fill="white", font=("", 16, "bold"),
        text="ドラッグで範囲を指定(Esc/右クリックでキャンセル)",
    )
    state = {"start": None, "rect": None, "label": None, "result": None}

    def on_press(e):
        state["start"] = (e.x_root, e.y_root)
        for key in ("rect", "label"):
            if state[key] is not None:
                canvas.delete(state[key])
                state[key] = None

    def current(e):
        x0, y0 = state["start"]
        x1, y1 = e.x_root, e.y_root
        return min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)

    def on_drag(e):
        if state["start"] is None:
            return
        x, y, w, h = current(e)
        if state["rect"] is None:
            state["rect"] = canvas.create_rectangle(x, y, x + w, y + h, outline="#ff3030", width=2)
            state["label"] = canvas.create_text(0, 0, fill="white", anchor="sw", font=("", 12, "bold"))
        canvas.coords(state["rect"], x, y, x + w, y + h)
        ty = y - 4 if y > 24 else y + h + 20
        canvas.coords(state["label"], x, ty)
        canvas.itemconfigure(state["label"], text=f"x={x} y={y} w={w} h={h}")

    def on_release(e):
        if state["start"] is None:
            return
        x, y, w, h = current(e)
        state["start"] = None
        if w < MIN_SIZE or h < MIN_SIZE:
            # 小さすぎる範囲は無効。もう一度ドラッグさせる
            if state["label"] is not None:
                canvas.itemconfigure(state["label"], text=f"小さすぎます({MIN_SIZE}ピクセル以上)。もう一度ドラッグ")
            return
        state["result"] = Region(x, y, w, h)
        top.destroy()

    def cancel(_e=None):
        state["result"] = None
        top.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    canvas.bind("<ButtonPress-3>", cancel)
    top.bind("<Escape>", cancel)
    top.update_idletasks()
    top.deiconify()
    top.lift()
    top.focus_force()
    try:
        top.grab_set()
    except tk.TclError:
        pass
    master.wait_window(top)
    return state["result"]
