"""pynput による Escキーの監視(アプリが前面になくても有効)。"""
from __future__ import annotations

from typing import Callable, Optional


class EscListener:
    def __init__(self, on_esc: Callable[[], None]):
        self._on_esc = on_esc
        self._listener = None
        self.error: Optional[str] = None

    def start(self) -> bool:
        try:
            from pynput import keyboard
        except Exception as e:  # 未インストールなど
            self.error = f"Escキーの監視を開始できません: {e}"
            return False

        def on_press(key):
            if key == keyboard.Key.esc:
                try:
                    self._on_esc()
                except Exception:
                    pass

        try:
            self._listener = keyboard.Listener(on_press=on_press)
            self._listener.daemon = True
            self._listener.start()
        except Exception as e:
            self.error = f"Escキーの監視を開始できません: {e}"
            self._listener = None
            return False
        return True

    @property
    def running(self) -> bool:
        return self._listener is not None and self._listener.is_alive()

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
