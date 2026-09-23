"""起動。DPI対応、設定の読み込み、GUIの起動。"""
from __future__ import annotations

import sys


def enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main() -> None:
    # DPI対応は Tk や pyautogui を読み込む前に行う
    enable_dpi_awareness()

    from app import capture  # OpenCV の環境変数を先に設定する
    del capture

    import tkinter as tk

    from app.config import default_config_path, load_config
    from app.engine import Engine
    from app.gui.main_window import MainWindow
    from app.hotkey import EscListener
    from app.input_control import get_pyautogui
    from app.ocr import OcrEngine

    config_path = default_config_path()
    config, messages = load_config(config_path)

    ocr = OcrEngine()
    ocr.warmup_async()  # 起動時に1回だけ作る(GUIを待たせないよう別スレッドで)

    holder: dict = {}

    def can_start():
        if not holder["hotkey"].running:
            return "Escキーの監視が動いていないため開始できません"
        return None

    engine = Engine(ocr, can_start=can_start)
    hotkey = EscListener(lambda: engine.request_stop("Escキー"))
    holder["hotkey"] = hotkey

    root = tk.Tk()
    app = MainWindow(root, config, config_path, engine, hotkey)
    for m in messages:
        app.log(m)
    try:
        get_pyautogui()  # FAILSAFE と PAUSE を設定しておく
    except Exception as e:
        app.log(f"pyautogui を読み込めません: {e}")
    if not hotkey.start():
        app.log(hotkey.error or "Escキーの監視を開始できません")
    app.log(f"起動しました(設定: {config_path.name})")
    root.mainloop()


if __name__ == "__main__":
    main()
