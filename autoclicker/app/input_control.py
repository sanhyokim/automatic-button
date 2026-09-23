"""ベジェ曲線の移動、クリック、キー入力、中断できる待機。

pyautogui は実際に操作するときに初めて読み込む(単体テストで画面を必要としないため)。
"""
from __future__ import annotations

import math
import random
import threading
import time
from typing import Callable, Optional

from .models import Region

MOVE_STEP_SEC = 0.01  # マウス移動の1点あたりの間隔


class StopRequested(Exception):
    """停止の指示を受けたときに送出する。"""


class InputError(Exception):
    """マウス・キーボード操作で例外が起きたときに送出する。"""


def random_point_in_region(
    region: Region, margin: int, rng: Optional[random.Random] = None
) -> tuple[int, int]:
    """範囲の内側のランダムな整数座標(端から margin 以上内側)。

    余白を取れない軸は中心座標を使う。
    """
    rng = rng or random

    def axis(start: int, length: int) -> int:
        lo = start + margin
        hi = start + length - 1 - margin
        if hi < lo:
            return start + length // 2
        return rng.randint(lo, hi)

    return axis(region.x, region.w), axis(region.y, region.h)


def ease_in_out(u: float) -> float:
    """開始と終了を緩やかにする(0→0、1→1)。"""
    return 0.5 - 0.5 * math.cos(math.pi * u)


def bezier_path(
    start: tuple[float, float],
    end: tuple[float, float],
    steps: int,
    rng: Optional[random.Random] = None,
) -> list[tuple[int, int]]:
    """ランダムな制御点を持つ3次ベジェ曲線上の点列(ease-in-out)。最後の点は end。"""
    rng = rng or random
    x0, y0 = start
    x3, y3 = end
    dx, dy = x3 - x0, y3 - y0
    dist = math.hypot(dx, dy)
    # 進行方向に垂直な向き
    if dist > 0:
        px, py = -dy / dist, dx / dist
    else:
        px, py = 0.0, 0.0
    spread = min(dist * 0.25, 200.0)

    def ctrl(t: float) -> tuple[float, float]:
        off = rng.uniform(-spread, spread)
        return x0 + dx * t + px * off, y0 + dy * t + py * off

    x1, y1 = ctrl(rng.uniform(0.2, 0.4))
    x2, y2 = ctrl(rng.uniform(0.6, 0.8))
    steps = max(1, steps)
    points: list[tuple[int, int]] = []
    for i in range(1, steps + 1):
        t = ease_in_out(i / steps)
        mt = 1 - t
        bx = mt**3 * x0 + 3 * mt**2 * t * x1 + 3 * mt * t**2 * x2 + t**3 * x3
        by = mt**3 * y0 + 3 * mt**2 * t * y1 + 3 * mt * t**2 * y2 + t**3 * y3
        points.append((int(round(bx)), int(round(by))))
    points[-1] = (int(x3), int(y3))
    return points


_pyautogui = None


def get_pyautogui():
    global _pyautogui
    if _pyautogui is None:
        import pyautogui

        pyautogui.FAILSAFE = False
        pyautogui.PAUSE = 0
        _pyautogui = pyautogui
    return _pyautogui


class InputController:
    """停止の指示で中断できるマウス・キーボード操作。"""

    def __init__(self, stop_event: threading.Event, rng: Optional[random.Random] = None):
        self.stop_event = stop_event
        self.rng = rng or random.Random()

    # ---- 待機
    def check_stop(self) -> None:
        if self.stop_event.is_set():
            raise StopRequested()

    def interruptible_sleep(self, sec: float) -> None:
        self.check_stop()
        if sec > 0 and self.stop_event.wait(sec):
            raise StopRequested()

    def random_sleep(self, lo: float, hi: float) -> float:
        sec = self.rng.uniform(lo, hi)
        self.interruptible_sleep(sec)
        return sec

    # ---- 操作
    def _call(self, fn: Callable, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except StopRequested:
            raise
        except Exception as e:  # pyautogui の例外
            raise InputError(f"{type(e).__name__}: {e}") from e

    def move_to(self, target: tuple[int, int], duration: float) -> None:
        """ベジェ曲線で duration 秒かけて target へ移動する。"""
        self.check_stop()
        pag = get_pyautogui()
        pos = self._call(pag.position)
        start = (pos[0], pos[1])
        steps = max(1, int(duration / MOVE_STEP_SEC))
        path = bezier_path(start, target, steps, self.rng)
        t0 = time.monotonic()
        for i, (x, y) in enumerate(path, start=1):
            self.check_stop()
            self._call(pag.moveTo, x, y, _pause=False)
            wait = t0 + duration * i / steps - time.monotonic()
            if wait > 0:
                self.interruptible_sleep(wait)

    def move_into(self, region: Region, margin: int, dur_min: float, dur_max: float) -> tuple[int, int]:
        target = random_point_in_region(region, margin, self.rng)
        self.move_to(target, self.rng.uniform(dur_min, dur_max))
        return target

    def click_region(self, region: Region, margin: int, dur_min: float, dur_max: float) -> tuple[int, int]:
        x, y = self.move_into(region, margin, dur_min, dur_max)
        self.check_stop()
        self._call(get_pyautogui().click, x, y, _pause=False)
        return x, y

    def hotkey(self, *keys: str) -> None:
        self.check_stop()
        self._call(get_pyautogui().hotkey, *keys, _pause=False)

    def press(self, key: str) -> None:
        self.check_stop()
        self._call(get_pyautogui().press, key, _pause=False)

    def type_text(self, text: str, interval_min: float, interval_max: float) -> None:
        """1文字ずつランダムな間隔で入力する。停止されたら残りは入力しない。"""
        pag = get_pyautogui()
        for i, ch in enumerate(text):
            if i > 0:
                self.random_sleep(interval_min, interval_max)
            self.check_stop()
            self._call(pag.write, ch, _pause=False)
