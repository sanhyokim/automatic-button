"""ルール編集ダイアログ(GUI-20〜24)。"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional

from .. import parser
from ..config import validate_rule
from ..models import REGION_KEYS, REGION_LABELS, Rule
from .widgets import RegionField, fit_window, window_pos

# パターンごとに表示する項目(仕様書 6.3節の表)
VISIBLE = {
    "A": ("button1",),
    "B": ("number", "input_field", "button1"),
    "C": ("button1", "button2"),
}


class RuleEditor(tk.Toplevel):
    def __init__(
        self,
        settings,  # SettingsWindow
        rule: Optional[Rule],
        on_save: Callable[[Rule], None],
    ):
        super().__init__(settings)
        self.settings = settings
        self.app = settings.app
        self.rule = rule or Rule()
        self.is_new = rule is None
        self._on_save = on_save
        self.title("ルールの追加" if self.is_new else "ルールの編集")
        self.attributes("-topmost", True)
        self.transient(settings)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        body = ttk.Frame(self, padding=6)
        body.pack(fill="both", expand=True)
        self.body = body

        row = ttk.Frame(body)
        ttk.Label(row, text="ルール名", width=8).pack(side="left")
        self.name_var = tk.StringVar(value=self.rule.name)
        ttk.Entry(row, textvariable=self.name_var).pack(side="left", fill="x", expand=True)
        self.name_row = row

        row = ttk.Frame(body)
        ttk.Label(row, text="キーワード", width=8).pack(side="left")
        self.keyword_var = tk.StringVar(value=self.rule.keyword)
        ttk.Entry(row, textvariable=self.keyword_var).pack(side="left", fill="x", expand=True)
        self.keyword_row = row

        row = ttk.Frame(body)
        ttk.Label(row, text="パターン", width=8).pack(side="left")
        self.pattern_var = tk.StringVar(value=self.rule.pattern)
        for p in ("A", "B", "C"):
            ttk.Radiobutton(row, text=p, value=p, variable=self.pattern_var, command=self._layout).pack(
                side="left", padx=(0, 6)
            )
        self.pattern_row = row

        self.fields: dict[str, RegionField] = {}
        for key in REGION_KEYS:
            on_test = self._test_number if key == "number" else None
            f = RegionField(body, REGION_LABELS[key], on_pick=self.app.pick_region, on_test=on_test)
            f.set(self.rule.regions.get(key))
            self.fields[key] = f

        self.test_label = ttk.Label(body, text="", wraplength=255, foreground="#0050a0")

        row = ttk.Frame(body)
        ttk.Button(row, text="キャンセル", command=self.destroy).pack(side="right")
        ttk.Button(row, text="保存", command=self._save).pack(side="right", padx=4)
        self.button_row = row

        self._placed = False
        self._layout()
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _layout(self) -> None:
        pattern = self.pattern_var.get()
        visible = VISIBLE.get(pattern, ())
        for child in self.body.pack_slaves():
            child.pack_forget()
        opts = {"fill": "x", "pady": 3}
        self.name_row.pack(**opts)
        self.keyword_row.pack(**opts)
        self.pattern_row.pack(**opts)
        for key in REGION_KEYS:
            if key not in visible:
                continue
            self.fields[key].pack(**opts)
            if key == "number" and self.test_label.cget("text"):
                self.test_label.pack(fill="x")
        self.button_row.pack(fill="x", pady=(8, 0))
        if self._placed:
            x, y = window_pos(self)
        else:
            x, y = window_pos(self.settings)
            self._placed = True
        fit_window(self, x, y)

    def _test_number(self) -> None:
        try:
            region = self.fields["number"].get()
        except ValueError as e:
            messagebox.showerror("読み取りテスト", str(e), parent=self)
            return
        if region is None:
            messagebox.showerror("読み取りテスト", "数値範囲が設定されていません", parent=self)
            return
        text = self.app.test_read(region, self.settings.test_config(), parent=self)
        if text is None:
            return
        fmt = self.app.config.get("number_format", "integer")  # メインウィンドウの切り替え
        ok, value = parser.check_number(text, fmt)
        fmt_name = "整数" if fmt == "integer" else "小数"
        self.test_label.configure(
            text=(
                f"読み取り: 「{text}」\n"
                f"形式チェック({fmt_name}): {'合格' if ok else '不合格'}\n"
                f"入力する値: {value if ok else '(なし)'}"
            )
        )
        self._layout()

    def _save(self) -> None:
        errors: list[str] = []
        pattern = self.pattern_var.get()
        regions = {}
        for key in REGION_KEYS:
            try:
                regions[key] = self.fields[key].get()
            except ValueError as e:
                if key in VISIBLE.get(pattern, ()):
                    errors.append(str(e))
                regions[key] = None
        # 表示していない項目は保存しない
        for key in REGION_KEYS:
            if key not in VISIBLE.get(pattern, ()):
                regions[key] = None
        rule = Rule(
            id=self.rule.id,
            name=self.name_var.get().strip(),
            keyword=self.keyword_var.get().strip(),
            pattern=pattern,
            regions=regions,
        )
        others = [r for r in self.settings.rules if r.id != rule.id]
        errors += validate_rule(rule, others, self.settings.waiting_text())
        if errors:
            messagebox.showerror("保存できません", "\n".join(errors), parent=self)
            return
        if not rule.name:
            rule.name = rule.keyword
        self._on_save(rule)
        self.destroy()
