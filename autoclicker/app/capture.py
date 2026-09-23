"""キャプチャーカードの取り込みスレッドと最新フレームの保持。"""
from __future__ import annotations

import threading
import time
from typing import Optional

import cv2
import numpy as np

OPEN_FIRST_FRAME_TIMEOUT = 5.0  # 開いた直後に最初のフレームを待つ秒数
STALE_FRAME_SEC = 2.0  # この秒数以上更新のないフレームは使わない


class CaptureError(Exception):
    pass


class FrameGrabber:
    """専用スレッドで常にフレームを読み続け、最新の1枚だけを保持する。"""

    def __init__(self, device_index: int, width: int, height: int, fps: int, fourcc: str = ""):
        self.device_index = device_index
        self.width = width
        self.height = height
        self.fps = fps
        self.fourcc = fourcc
        self._cap = None
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._lock = threading.Lock()
        self._frame: Optional[np.ndarray] = None
        self._frame_time = 0.0

    def open(self) -> None:
        api = getattr(cv2, "CAP_DSHOW", None)
        cap = cv2.VideoCapture(self.device_index, api) if api is not None else cv2.VideoCapture(self.device_index)
        if cap is None or not cap.isOpened():
            raise CaptureError(f"キャプチャーカード(機器番号{self.device_index})を開けません")
        if self.fourcc and len(self.fourcc) == 4:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.fourcc))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.fps)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        frame = None
        deadline = time.monotonic() + OPEN_FIRST_FRAME_TIMEOUT
        while time.monotonic() < deadline:
            ok, f = cap.read()
            if ok and f is not None:
                frame = f
                break
            time.sleep(0.05)
        if frame is None:
            cap.release()
            raise CaptureError("キャプチャーカードから映像を取得できません")
        h, w = frame.shape[:2]
        if (w, h) != (self.width, self.height):
            cap.release()
            raise CaptureError(
                f"キャプチャーの解像度が {w}×{h} です({self.width}×{self.height} が必要です)"
            )
        self._cap = cap
        with self._lock:
            self._frame = frame
            self._frame_time = time.monotonic()
        self._running.set()
        self._thread = threading.Thread(target=self._loop, name="capture", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        cap = self._cap
        while self._running.is_set():
            try:
                ok, frame = cap.read()
            except Exception:
                ok, frame = False, None
            if ok and frame is not None:
                with self._lock:
                    self._frame = frame
                    self._frame_time = time.monotonic()
            else:
                time.sleep(0.01)

    def latest_frame(self) -> Optional[np.ndarray]:
        """最新フレームのコピー。古すぎる(取り込みが止まっている)場合は None。"""
        with self._lock:
            if self._frame is None or time.monotonic() - self._frame_time > STALE_FRAME_SEC:
                return None
            return self._frame.copy()

    def close(self) -> None:
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        with self._lock:
            self._frame = None
