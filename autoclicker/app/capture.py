"""キャプチャーカードの取り込みスレッドと最新フレームの保持。"""
from __future__ import annotations

import os
import threading
import time
from typing import Optional

# Media Foundation(MSMF)の起動が遅い問題を避ける。cv2 を読み込む前に設定する
os.environ.setdefault("OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS", "0")
# 開けない方式を試したときの警告を出さない
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")

import cv2
import numpy as np

OPEN_FIRST_FRAME_TIMEOUT = 20.0  # 開いた直後に最初のフレームを待つ秒数
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

    def _open_capture(self):
        """DirectShow で開く。開けなければ Media Foundation、既定の方式の順に試す。"""
        apis = [getattr(cv2, name) for name in ("CAP_DSHOW", "CAP_MSMF") if hasattr(cv2, name)]
        apis.append(None)
        for api in apis:
            try:
                cap = cv2.VideoCapture(self.device_index) if api is None else cv2.VideoCapture(self.device_index, api)
            except Exception:
                continue
            if cap is not None and cap.isOpened():
                return cap
            if cap is not None:
                cap.release()
        return None

    def open(self) -> None:
        cap = self._open_capture()
        if cap is None:
            raise CaptureError(
                f"キャプチャーカード(機器番号{self.device_index})を開けません。"
                "接続、ほかのアプリ(OBSなど)で使用中でないか、機器番号(設定の「詳細」タブ)を確認してください"
            )
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


def pick_primary(monitors: list) -> Optional[dict]:
    """mss のモニター一覧から、Windows のメインディスプレイ(左上が 0,0)を選ぶ。

    mss の monitors[1] はメインディスプレイとは限らない(2画面の環境で別の画面になることがある)。
    範囲の設定とクリックの座標はメインディスプレイ基準なので、取り込みもそれに合わせる。
    """
    screens = monitors[1:]  # monitors[0] は全画面を合わせた領域
    for mon in screens:
        if mon.get("left") == 0 and mon.get("top") == 0:
            return mon
    return screens[0] if screens else None


class ScreenGrabber:
    """このPCの画面を直接取り込む(キャプチャーカードを使わない)。

    FrameGrabber と同じ使い方ができる。キャプチャーカードを占有しないので、
    キャプチャーカードを使うほかのアプリと同時に動かせる。
    """

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self._local = threading.local()
        self._opened = False
        self._mon: Optional[dict] = None

    def _sct(self):
        # mss のインスタンスは作ったスレッドでだけ使う
        sct = getattr(self._local, "sct", None)
        if sct is None:
            import mss

            sct = mss.mss()
            self._local.sct = sct
        return sct

    def open(self) -> None:
        try:
            sct = self._sct()
            monitors = sct.monitors
        except Exception as e:
            raise CaptureError(f"画面を取り込めません: {e}") from e
        mon = pick_primary(monitors)
        if mon is None:
            raise CaptureError("メインディスプレイが見つかりません")
        self._mon = {k: mon[k] for k in ("left", "top", "width", "height")}
        w, h = mon["width"], mon["height"]
        if (w, h) != (self.width, self.height):
            raise CaptureError(
                f"画面の解像度が {w}×{h} です({self.width}×{self.height}、表示スケール100%が必要です)"
            )
        self._opened = True
        if self.latest_frame() is None:
            raise CaptureError("画面を取り込めません")

    def latest_frame(self) -> Optional[np.ndarray]:
        if not self._opened:
            return None
        try:
            sct = self._sct()
            shot = sct.grab(self._mon)
            return cv2.cvtColor(np.asarray(shot), cv2.COLOR_BGRA2BGR)
        except Exception:
            return None

    def close(self) -> None:
        self._opened = False
        sct = getattr(self._local, "sct", None)
        if sct is not None:
            try:
                sct.close()
            except Exception:
                pass
            self._local.sct = None


def make_grabber(cfg: dict):
    """設定の capture.source に応じて取り込み方法を選ぶ。"""
    c = cfg["capture"]
    if c.get("source", "screen") == "card":
        return FrameGrabber(c["device_index"], c["width"], c["height"], c["fps"], c.get("fourcc", ""))
    return ScreenGrabber(c["width"], c["height"])
