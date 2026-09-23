"""メインウィンドウ(GUI-01〜04)とアプリ全体のまとめ役。"""
from __future__ import annotations

import copy
import queue
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Optional

from .. import engine as eng
from ..config import save_config
from ..engine import Engine, EngineStop, timestamp
from ..hotkey import EscListener
from ..models import Region
from .region_selector import select_region
from .settings_window import SettingsWindow
from .widgets import WIDTH

STATE_LABELS = {
    eng.STOPPED: "停止",
    eng.STARTING: "開始準備中",
    eng.MONITORING: "監視中",
    eng.EXECUTING: "動作中",
    eng.WAIT_RETURN: "WAITING待ち",
}
POLL_MS = 100


class MainWindow:
    def __init__(self, root: tk.Tk, config: dict, config_path: Path, engine: Engine, hotkey: EscListener):
        self.root = root
        self.config = config
        self.config_path = config_path
        self.engine = engine
        self.hotkey = hotkey
        self.state = eng.STOPPED
        self.settings: Optional[SettingsWindow] = None

        root.title("自動クリック")
        root.geometry(f"{WIDTH}x420+0+0")
        root.minsize(WIDTH, 250)
        root.maxsize(WIDTH, 10000)
        root.attributes("-topmost", True)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        frame = ttk.Frame(root, padding=4)
        frame.pack(fill="both", expand=True)

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        self.start_btn = ttk.Button(buttons, text="開始", command=self.on_start)
        self.start_btn.pack(side="left", fill="x", expand=True)
        self.stop_btn = ttk.Button(buttons, text="停止", command=self.on_stop)
        self.stop_btn.pack(side="left", fill="x", expand=True, padx=(4, 0))

        self.status_var = tk.StringVar(value="停止")
        ttk.Label(frame, textvariable=self.status_var, wraplength=WIDTH - 16, font=("", 10, "bold")).pack(
            fill="x", pady=4
        )

        logf = ttk.Frame(frame)
        logf.pack(fill="both", expand=True)
        self.log_text = tk.Text(logf, wrap="char", height=10, state="disabled", font=("", 9))
        sb = ttk.Scrollbar(logf, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")

        self.settings_btn = ttk.Button(frame, text="設定", command=self.open_settings)
        self.settings_btn.pack(fill="x", pady=(4, 0))

        self._update_buttons()
        root.after(POLL_MS, self._poll_events)

    # ------------------------------------------------------------ 記録
    def log(self, msg: str) -> None:
        self.append_log(f"{timestamp()} {msg}")

    def append_log(self, line: str) -> None:
        t = self.log_text
        t.configure(state="normal")
        t.insert("end", line + "\n")
        max_lines = self.config.get("gui", {}).get("log_max_lines", 200)
        lines = int(t.index("end-1c").split(".")[0]) - 1
        if lines > max_lines:
            t.delete("1.0", f"{lines - max_lines + 1}.0")
        t.configure(state="disabled")
        t.see("end")

    def _poll_events(self) -> None:
        try:
            while True:
                ev = self.engine.events.get_nowait()
                if ev[0] == "log":
                    self.append_log(ev[1])
                elif ev[0] == "state":
                    self._on_state(ev[1], ev[2])
        except queue.Empty:
            pass
        self.root.after(POLL_MS, self._poll_events)

    def _on_state(self, state: str, reason: str) -> None:
        self.state = state
        label = STATE_LABELS.get(state, state)
        if state == eng.STOPPED and reason:
            label = f"停止: {reason}"
        self.status_var.set(label)
        self._update_buttons()

    def _update_buttons(self) -> None:
        stopped = self.state == eng.STOPPED
        settings_open = self.settings is not None
        self.start_btn.configure(state="normal" if stopped and not settings_open else "disabled")
        self.stop_btn.configure(state="disabled" if stopped else "normal")
        self.settings_btn.configure(state="normal" if stopped and not settings_open else "disabled")

    # ------------------------------------------------------------ 開始・停止
    def on_start(self) -> None:
        if self.state != eng.STOPPED or self.settings is not None:
            return
        self.engine.start(self.config)

    def on_stop(self) -> None:
        self.engine.request_stop("停止ボタン")

    # ------------------------------------------------------------ 設定
    def open_settings(self) -> None:
        if self.state != eng.STOPPED or self.settings is not None:
            return
        self.settings = SettingsWindow(self)
        self._update_buttons()

    def on_settings_closed(self) -> None:
        self.settings = None
        self._update_buttons()

    def apply_config(self, cfg: dict) -> bool:
        """設定ウィンドウで保存した内容を反映し、ファイルに書き込む。"""
        self.config = copy.deepcopy(cfg)
        try:
            save_config(self.config_path, self.config)
        except OSError as e:
            messagebox.showerror("保存できません", f"設定ファイルに書き込めません: {e}", parent=self.settings)
            return False
        self.log("設定を保存しました")
        return True

    # ------------------------------------------------------------ 範囲・読み取りテスト
    def _visible_windows(self) -> list[tk.Misc]:
        wins: list[tk.Misc] = [self.root]
        if self.settings is not None:
            wins.append(self.settings)
            ed = self.settings.editor
            if ed is not None and ed.winfo_exists():
                wins.append(ed)
        return [w for w in wins if w.winfo_exists() and w.state() != "withdrawn"]

    def pick_region(self) -> Optional[Region]:
        """GUIを一時的に隠して、範囲設定のオーバーレイを表示する。"""
        if self.state != eng.STOPPED:
            return None
        grab = self.root.grab_current()
        if grab is not None:
            grab.grab_release()
        wins = self._visible_windows()
        for w in wins:
            w.withdraw()
        self.root.update()
        try:
            region = select_region(self.root)
        finally:
            for w in wins:
                if w.winfo_exists():
                    w.deiconify()
                    w.attributes("-topmost", True)
            self.root.update()
            if grab is not None and grab.winfo_exists():
                try:
                    grab.grab_set()
                except tk.TclError:
                    pass
            if wins:
                wins[-1].lift()
                wins[-1].focus_force()
        return region

    def test_read(self, region: Region, cfg: dict, parent: tk.Misc) -> Optional[str]:
        """読み取りテスト。失敗した場合はメッセージを出して None を返す。"""
        if self.state != eng.STOPPED:
            messagebox.showerror("読み取りテスト", "停止の状態でのみ使えます", parent=parent)
            return None
        parent.configure(cursor="watch")
        parent.update()
        try:
            text = self.engine.test_read(cfg, region)
        except EngineStop as e:
            messagebox.showerror("読み取りテスト", str(e), parent=parent)
            return None
        finally:
            try:
                parent.configure(cursor="")
            except tk.TclError:
                pass
        self.log(f"読み取りテスト: 「{text}」")
        return text

    # ------------------------------------------------------------ 終了
    def on_close(self) -> None:
        self.engine.request_stop("アプリ終了")
        self.engine.join(5.0)
        self.hotkey.stop()
        try:
            save_config(self.config_path, self.config)
        except OSError:
            pass
        self.root.destroy()
