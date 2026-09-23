"""読み取りテストの結果表示(OCRに渡した画像と、文字検出あり・なしの結果)。"""
from __future__ import annotations

import base64
import tkinter as tk
from tkinter import ttk

import cv2

from ..diagnostics import hints

MAX_PREVIEW_W = 600
MAX_PREVIEW_H = 200


def show_test_result(parent: tk.Misc, info: dict) -> None:
    top = tk.Toplevel(parent)
    top.title("読み取りテストの結果")
    top.attributes("-topmost", True)
    frame = ttk.Frame(top, padding=6)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="OCRに渡した画像:").pack(anchor="w")
    img = info.get("image")
    if img is not None:
        h, w = img.shape[:2]
        scale = min(1.0, MAX_PREVIEW_W / w, MAX_PREVIEW_H / h)
        if scale < 1.0:
            img = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".png", img)
        if ok:
            photo = tk.PhotoImage(data=base64.b64encode(buf.tobytes()).decode("ascii"))
            label = tk.Label(frame, image=photo, bd=1, relief="solid")
            label.image = photo  # 参照を保持する
            label.pack(anchor="w", pady=(2, 6))

    res = info.get("results", {})
    current = "あり" if info.get("use_det", True) else "なし"
    lines = [
        f"文字検出あり: 「{res.get(True, '')}」",
        f"文字検出なし: 「{res.get(False, '')}」",
        f"(いまの設定は「文字検出{current}」)",
    ]
    ttk.Label(frame, text="\n".join(lines), justify="left").pack(anchor="w")
    for h in hints(info):
        ttk.Label(frame, text="・" + h, wraplength=MAX_PREVIEW_W, foreground="#b04000", justify="left").pack(
            anchor="w", pady=(4, 0)
        )
    ttk.Button(frame, text="閉じる", command=top.destroy).pack(anchor="e", pady=(8, 0))
    top.update_idletasks()
    x = parent.winfo_rootx() + parent.winfo_width() + 8
    top.geometry(f"+{x}+{parent.winfo_rooty()}")
