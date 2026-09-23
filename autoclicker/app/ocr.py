"""RapidOCR のアダプター、前処理、連結。

RapidOCR はバージョンによって API が異なるため、ここで吸収する。
- 新: `rapidocr` パッケージ(`RapidOCROutput` / `TextRecOutput` を返す)
- 旧: `rapidocr_onnxruntime` パッケージ(`(result, elapse)` を返す)
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

import cv2
import numpy as np

from .models import Region

PAD = 10  # 前後に加える余白(ピクセル)


class OcrError(Exception):
    pass


def crop_region(frame: np.ndarray, region: Region) -> Optional[np.ndarray]:
    """フレームから範囲を切り出す。画面の外にはみ出す分は切り詰める。"""
    h, w = frame.shape[:2]
    r = region.clamp(w, h)
    if r is None:
        return None
    return frame[r.y : r.y + r.h, r.x : r.x + r.w]


def preprocess(img: np.ndarray, min_height: int, pad: int = PAD) -> np.ndarray:
    """小さい画像を拡大し、背景に近い色の余白を加える。"""
    h, w = img.shape[:2]
    if h < min_height:
        scale = min_height / h
        img = cv2.resize(img, (max(1, round(w * scale)), min_height), interpolation=cv2.INTER_CUBIC)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if pad > 0:
        border = np.concatenate([img[0, :], img[-1, :], img[:, 0], img[:, -1]], axis=0)
        color = [int(c) for c in np.median(border, axis=0)]
        img = cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=color)
    return img


def _left_x(box) -> float:
    try:
        return float(min(p[0] for p in box))
    except Exception:
        return 0.0


def extract_text(output) -> str:
    """RapidOCR の結果から、文字の塊を左端のX座標の順に連結した文字列を返す。"""
    items: list[tuple[float, str]] = []
    if output is None:
        return ""
    txts = getattr(output, "txts", None)
    if txts is not None or hasattr(output, "boxes"):
        # 新しい rapidocr
        boxes = getattr(output, "boxes", None)
        for i, t in enumerate(txts or ()):
            x = _left_x(boxes[i]) if boxes is not None and i < len(boxes) else float(i)
            items.append((x, str(t)))
    else:
        # 旧 rapidocr_onnxruntime: (result, elapse)
        result = output[0] if isinstance(output, tuple) else output
        for i, item in enumerate(result or []):
            if isinstance(item, (list, tuple)) and len(item) >= 3:
                items.append((_left_x(item[0]), str(item[1])))
            elif isinstance(item, (list, tuple)) and len(item) >= 1:
                items.append((float(i), str(item[0])))
    items.sort(key=lambda it: it[0])
    return "".join(t for _, t in items)


class OcrEngine:
    """RapidOCR のインスタンスを1回だけ作って使い回す。"""

    def __init__(self):
        self._engine = None
        self._kind = ""
        self._lock = threading.Lock()
        self.init_error: Optional[str] = None

    def load(self) -> None:
        with self._lock:
            self._load_locked()

    def _load_locked(self) -> None:
        if self._engine is not None:
            return
        try:
            try:
                from rapidocr import RapidOCR  # 新しい版

                self._kind = "rapidocr"
            except ImportError:
                from rapidocr_onnxruntime import RapidOCR  # 旧版

                self._kind = "rapidocr_onnxruntime"
            for name in ("RapidOCR", "rapidocr", "rapidocr_onnxruntime"):
                logging.getLogger(name).setLevel(logging.WARNING)
            self._engine = RapidOCR()
            self.init_error = None
        except Exception as e:
            self.init_error = f"RapidOCR を初期化できません: {type(e).__name__}: {e}"
            raise OcrError(self.init_error) from e

    def warmup_async(self) -> threading.Thread:
        def run():
            try:
                self.load()
            except OcrError:
                pass

        t = threading.Thread(target=run, name="ocr-load", daemon=True)
        t.start()
        return t

    def recognize(self, img: np.ndarray, use_det: bool) -> str:
        with self._lock:
            self._load_locked()
            try:
                out = self._engine(img, use_det=use_det, use_cls=False, use_rec=True)
            except TypeError:
                out = self._engine(img)
            return extract_text(out)

    def diagnose(self, frame: np.ndarray, region: Region, min_height: int) -> dict:
        """読み取りテスト用。OCRに渡す画像と、文字検出あり・なしの両方の結果を返す。"""
        img = crop_region(frame, region)
        if img is None or img.size == 0:
            return {"image": None, "results": {}, "errors": {}, "brightness": None, "contrast": None}
        pre = preprocess(img, min_height)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        results: dict[bool, str] = {}
        errors: dict[bool, str] = {}
        for use_det in (True, False):
            try:
                results[use_det] = self.recognize(pre, use_det).strip()
            except OcrError as e:
                errors[use_det] = str(e)
            except Exception as e:
                errors[use_det] = f"{type(e).__name__}: {e}"
        return {
            "image": pre,
            "results": results,
            "errors": errors,
            "brightness": float(gray.mean()),
            "contrast": float(gray.std()),
        }

    def read_region(self, frame: np.ndarray, region: Region, min_height: int, use_det: bool) -> str:
        """範囲を切り出して読み取る。例外は OcrError として送出する(結果なしは空文字列)。"""
        img = crop_region(frame, region)
        if img is None or img.size == 0:
            return ""
        try:
            return self.recognize(preprocess(img, min_height), use_det).strip()
        except OcrError:
            raise
        except Exception as e:
            raise OcrError(f"{type(e).__name__}: {e}") from e
