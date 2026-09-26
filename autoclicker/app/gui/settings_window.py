"""設定ウィンドウ(GUI-10〜17)。"""
from __future__ import annotations

import copy
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from .. import parser
from ..config import get_rules, retreat_overlaps, validate_settings
from ..models import REGION_LABELS, REQUIRED_REGIONS, Region, Rule
from .region_viewer import show_regions
from .rule_editor import RuleEditor
from .widgets import RegionField, fit_window, window_pos

NO_FALLBACK = "(未設定)"
SOURCES = (("screen", "画面を直接"), ("card", "キャプチャーカード"))

# (キー, 表示名) 最小と最大の組
TIMING_PAIRS = (
    ("reaction_delay", "反応待ち時間"),
    ("step_delay", "操作間待ち時間"),
    ("move_duration", "マウス移動時間"),
    ("type_interval", "入力の間隔"),
)
TIMING_SINGLE = (
    ("poll_interval", "監視の間隔"),
    ("waiting_timeout", "WAITING復帰のタイムアウト"),
)
# (セクション, キー, 表示名, 型)
DETAIL_FIELDS = (
    ("detection", "number_max_reads", "数値の最大読み取り回数", int),
    ("detection", "number_match_count", "確定に必要な一致回数", int),
    ("detection", "number_read_interval", "数値の読み取り間隔(秒)", float),
    ("detection", "keyword_confirm_count", "キーワード確定の回数", int),
    ("detection", "waiting_confirm_count", "WAITING確定の回数", int),
    ("detection", "ocr_min_height", "OCRの最小の高さ(px)", int),
    ("detection", "click_margin", "クリックの余白(px)", int),
    ("gui", "log_max_lines", "記録の最大行数", int),
    ("capture", "device_index", "キャプチャーの機器番号", int),
)


class SettingsWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.work = copy.deepcopy(app.config)
        self.rules: list[Rule] = get_rules(self.work)
        self.editor: Optional[RuleEditor] = None
        self.title("設定")
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.close)

        outer = ttk.Frame(self, padding=4)
        outer.pack(fill="both", expand=True)
        nb = ttk.Notebook(outer)
        nb.pack(fill="both", expand=True)
        self._build_rules_tab(nb)
        self._build_common_tab(nb)
        self._build_timing_tab(nb)
        self._build_detail_tab(nb)

        bottom = ttk.Frame(outer)
        bottom.pack(fill="x", pady=(6, 0))
        ttk.Button(bottom, text="範囲を表示", command=self.show_regions).pack(side="left")
        ttk.Button(bottom, text="閉じる", command=self.close).pack(side="right")
        ttk.Button(bottom, text="保存", command=self.save).pack(side="right", padx=4)

        root = app.root
        root.update_idletasks()
        x = root.winfo_x()
        y = root.winfo_rooty() + root.winfo_height() + 8
        fit_window(self, x, y)

    # ------------------------------------------------------------ ルール
    def _build_rules_tab(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb, padding=4)
        nb.add(tab, text="ルール")
        left = ttk.Frame(tab)
        left.pack(side="left", fill="both", expand=True)
        self.rule_list = tk.Listbox(left, height=12, exportselection=False, activestyle="none")
        sb = ttk.Scrollbar(left, orient="vertical", command=self.rule_list.yview)
        self.rule_list.configure(yscrollcommand=sb.set)
        self.rule_list.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.rule_list.bind("<Double-Button-1>", lambda e: self.edit_rule())
        right = ttk.Frame(tab)
        right.pack(side="left", fill="y", padx=(4, 0))
        for text, cmd in (
            ("追加", self.add_rule),
            ("編集", self.edit_rule),
            ("削除", self.delete_rule),
            ("上へ", lambda: self.move_rule(-1)),
            ("下へ", lambda: self.move_rule(1)),
        ):
            ttk.Button(right, text=text, width=6, command=cmd).pack(pady=2)
        self._refresh_rules()

    def _refresh_rules(self, select: Optional[int] = None) -> None:
        self.rule_list.delete(0, "end")
        for r in self.rules:
            self.rule_list.insert("end", r.list_label())
        if select is not None and 0 <= select < len(self.rules):
            self.rule_list.selection_set(select)
            self.rule_list.see(select)
        if hasattr(self, "fallback_combo"):
            self._refresh_fallback()

    def _selected(self) -> Optional[int]:
        sel = self.rule_list.curselection()
        return sel[0] if sel else None

    def _editor_open(self) -> bool:
        if self.editor is not None and self.editor.winfo_exists():
            self.editor.lift()
            return True
        return False

    def add_rule(self) -> None:
        if self._editor_open():
            return

        def on_save(rule: Rule):
            self.rules.append(rule)
            self._refresh_rules(len(self.rules) - 1)

        self.editor = RuleEditor(self, None, on_save)

    def edit_rule(self) -> None:
        idx = self._selected()
        if idx is None or self._editor_open():
            return

        def on_save(rule: Rule):
            self.rules[idx] = rule
            self._refresh_rules(idx)

        self.editor = RuleEditor(self, copy.deepcopy(self.rules[idx]), on_save)

    def delete_rule(self) -> None:
        idx = self._selected()
        if idx is None or self._editor_open():
            return
        rule = self.rules[idx]
        if not messagebox.askyesno("削除", f"ルール「{rule.display_name}」を削除しますか?", parent=self):
            return
        del self.rules[idx]
        self._refresh_rules(min(idx, len(self.rules) - 1))

    def move_rule(self, delta: int) -> None:
        idx = self._selected()
        if idx is None:
            return
        j = idx + delta
        if not 0 <= j < len(self.rules):
            return
        self.rules[idx], self.rules[j] = self.rules[j], self.rules[idx]
        self._refresh_rules(j)

    # ------------------------------------------------------------ 共通
    def _build_common_tab(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb, padding=4)
        nb.add(tab, text="共通")
        self.keyword_field = RegionField(tab, "キーワード範囲", self.app.pick_region, self._test_keyword)
        self.keyword_field.set(Region.from_dict(self.work.get("keyword_region")))
        self.keyword_field.pack(fill="x", pady=3)
        self.keyword_test_label = ttk.Label(tab, text="", wraplength=255, foreground="#0050a0")
        self.keyword_test_label.pack(fill="x")
        self.retreat_field = RegionField(tab, "退避エリア", self.app.pick_region)
        self.retreat_field.set(Region.from_dict(self.work.get("retreat_region")))
        self.retreat_field.pack(fill="x", pady=3)

        ttk.Label(tab, text="避難先(パターンA/Cのルール)").pack(anchor="w", pady=(6, 0))
        self.fallback_var = tk.StringVar()
        self.fallback_combo = ttk.Combobox(tab, textvariable=self.fallback_var, state="readonly")
        self.fallback_combo.pack(fill="x")
        self._fallback_id = self.work.get("fallback_rule_id")
        self.fallback_combo.bind("<<ComboboxSelected>>", self._on_fallback_selected)
        self._refresh_fallback()

        ttk.Label(tab, text="待機表示の文字").pack(anchor="w", pady=(6, 0))
        self.waiting_var = tk.StringVar(value=self.work.get("waiting_text", "WAITING"))
        ttk.Entry(tab, textvariable=self.waiting_var).pack(fill="x")

    def _fallback_choices(self) -> list[Rule]:
        return [r for r in self.rules if r.pattern in ("A", "C")]

    def _refresh_fallback(self) -> None:
        choices = self._fallback_choices()
        self.fallback_combo["values"] = [NO_FALLBACK] + [r.list_label() for r in choices]
        ids = [r.id for r in choices]
        if self._fallback_id in ids:
            self.fallback_combo.current(ids.index(self._fallback_id) + 1)
        else:
            # 削除された、またはパターンがBに変わった場合は未設定に戻す
            self._fallback_id = None
            self.fallback_combo.current(0)

    def _on_fallback_selected(self, _e=None) -> None:
        idx = self.fallback_combo.current()
        choices = self._fallback_choices()
        self._fallback_id = choices[idx - 1].id if idx >= 1 else None

    def waiting_text(self) -> str:
        return self.waiting_var.get().strip()

    def _test_keyword(self) -> None:
        try:
            region = self.keyword_field.get()
        except ValueError as e:
            messagebox.showerror("読み取りテスト", str(e), parent=self)
            return
        if region is None:
            messagebox.showerror("読み取りテスト", "キーワード範囲が設定されていません", parent=self)
            return
        text = self.app.test_read(region, self.test_config(), parent=self)
        if text is None:
            return
        if parser.is_waiting(text, self.waiting_text()):
            judge = "待機表示"
        else:
            rule = parser.match_rule(text, self.rules)
            judge = f"ルール「{rule.display_name}」に一致" if rule else "どのルールとも一致しない"
        self.keyword_test_label.configure(text=f"読み取り: 「{text}」\n判定: {judge}")
        fit_window(self, *window_pos(self))

    # ------------------------------------------------------------ 時間
    def _build_timing_tab(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb, padding=4)
        nb.add(tab, text="時間")
        timing = self.work["timing"]
        self.timing_vars: dict[str, tk.StringVar] = {}
        ttk.Label(tab, text="単位は秒(最小 〜 最大)").grid(row=0, column=0, columnspan=4, sticky="w")
        r = 1
        for key, label in TIMING_PAIRS:
            ttk.Label(tab, text=label).grid(row=r, column=0, sticky="w", pady=2)
            for col, suffix in ((1, "_min"), (3, "_max")):
                var = tk.StringVar(value=str(timing.get(key + suffix, "")))
                ttk.Entry(tab, textvariable=var, width=6).grid(row=r, column=col, pady=2)
                self.timing_vars[key + suffix] = var
            ttk.Label(tab, text="〜").grid(row=r, column=2)
            r += 1
        for key, label in TIMING_SINGLE:
            ttk.Label(tab, text=label).grid(row=r, column=0, columnspan=3, sticky="w", pady=2)
            var = tk.StringVar(value=str(timing.get(key, "")))
            ttk.Entry(tab, textvariable=var, width=6).grid(row=r, column=3, pady=2)
            self.timing_vars[key] = var
            r += 1

    # ------------------------------------------------------------ 詳細
    def _build_detail_tab(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb, padding=4)
        nb.add(tab, text="詳細")
        self.detail_vars: dict[tuple[str, str], tk.StringVar] = {}
        r = 0
        for section, key, label, _typ in DETAIL_FIELDS:
            ttk.Label(tab, text=label).grid(row=r, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=str(self.work[section].get(key, "")))
            ttk.Entry(tab, textvariable=var, width=6).grid(row=r, column=1, pady=2, padx=(4, 0))
            self.detail_vars[(section, key)] = var
            r += 1
        ttk.Label(tab, text="取り込み方法").grid(row=r, column=0, sticky="w", pady=2)
        self.source_var = tk.StringVar()
        self.source_combo = ttk.Combobox(
            tab, textvariable=self.source_var, state="readonly", width=12,
            values=[label for _v, label in SOURCES],
        )
        src = self.work["capture"].get("source", "screen")
        self.source_combo.current(next((i for i, (v, _l) in enumerate(SOURCES) if v == src), 0))
        self.source_combo.grid(row=r, column=1, pady=2, padx=(4, 0), sticky="w")
        r += 1
        self.use_det_var = tk.BooleanVar(value=bool(self.work["detection"].get("ocr_use_det", True)))
        ttk.Checkbutton(tab, text="文字検出を使う(ocr_use_det)", variable=self.use_det_var).grid(
            row=r, column=0, columnspan=2, sticky="w", pady=2
        )

    # ------------------------------------------------------------ 収集・保存
    def _collect(self) -> tuple[dict, list[str]]:
        """画面の内容から設定を組み立てる。(設定, 入力エラー) を返す。"""
        cfg = copy.deepcopy(self.work)
        errors: list[str] = []
        for name, field, key in (
            ("キーワード範囲", self.keyword_field, "keyword_region"),
            ("退避エリア", self.retreat_field, "retreat_region"),
        ):
            try:
                region = field.get()
                cfg[key] = region.to_dict() if region else None
            except ValueError as e:
                errors.append(str(e))
        cfg["waiting_text"] = self.waiting_text()
        cfg["fallback_rule_id"] = self._fallback_id
        cfg["rules"] = [r.to_dict() for r in self.rules]

        labels = dict(TIMING_PAIRS)
        for key, var in self.timing_vars.items():
            base = key.rsplit("_", 1)[0] if key.endswith(("_min", "_max")) else key
            label = labels.get(base) or dict(TIMING_SINGLE).get(key, key)
            try:
                cfg["timing"][key] = float(var.get())
            except ValueError:
                errors.append(f"{label}が数値ではありません")
        for (section, key), var in self.detail_vars.items():
            label, typ = next((l, t) for s, k, l, t in DETAIL_FIELDS if s == section and k == key)
            try:
                cfg[section][key] = typ(var.get())
            except ValueError:
                errors.append(f"{label}が{'整数' if typ is int else '数値'}ではありません")
        cfg["detection"]["ocr_use_det"] = bool(self.use_det_var.get())
        cfg["capture"]["source"] = SOURCES[max(0, self.source_combo.current())][0]
        return cfg, errors

    def test_config(self) -> dict:
        """読み取りテスト用の設定。入力途中で不正な値は保存済みの値を使う。"""
        cfg, errors = self._collect()
        if errors or validate_settings(cfg):
            base = copy.deepcopy(self.app.config)
            base["detection"]["ocr_use_det"] = bool(self.use_det_var.get())
            base["capture"]["source"] = SOURCES[max(0, self.source_combo.current())][0]
            return base
        return cfg

    def save(self) -> bool:
        cfg, errors = self._collect()
        if not errors:
            errors = validate_settings(cfg)
        # 保存済みのルールの内容も確認する(キーワードの重複など)
        norm = [parser.canonical(r.keyword) for r in self.rules]
        if len(set(norm)) != len(norm):
            errors.append("キーワードが重複しているルールがあります")
        if errors:
            messagebox.showerror("保存できません", "\n".join(errors), parent=self)
            return False
        overlaps = retreat_overlaps(cfg)
        if overlaps:
            messagebox.showwarning(
                "警告",
                "退避エリアが次の範囲と重なっています。\n・" + "\n・".join(overlaps)
                + "\n\n(保存はします)",
                parent=self,
            )
        if not self.app.apply_config(cfg):
            return False
        self.work = copy.deepcopy(cfg)
        return True

    def close(self) -> None:
        if self.editor is not None and self.editor.winfo_exists():
            self.editor.destroy()
        self.destroy()
        self.app.on_settings_closed()

    # ------------------------------------------------------------ 範囲を表示
    def show_regions(self) -> None:
        cfg, _errors = self._collect()
        items: list[tuple[str, Region, str]] = []
        kw = Region.from_dict(cfg.get("keyword_region"))
        if kw:
            items.append(("キーワード範囲", kw, "read"))
        for rule in self.rules:
            for key in REQUIRED_REGIONS.get(rule.pattern, ()):
                r = rule.regions.get(key)
                if r:
                    kind = "read" if key == "number" else "click"
                    items.append((f"{rule.display_name}:{REGION_LABELS[key]}", r, kind))
        rt = Region.from_dict(cfg.get("retreat_region"))
        if rt:
            items.append(("退避エリア", rt, "retreat"))
        show_regions(self.app.root, items)
