from types import SimpleNamespace

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from app.models import Region  # noqa: E402
from app.ocr import crop_region, extract_text, preprocess  # noqa: E402


def test_crop_clamps_to_frame():
    frame = np.zeros((1080, 1920, 3), np.uint8)
    assert crop_region(frame, Region(1900, 1070, 50, 50)).shape == (10, 20, 3)
    assert crop_region(frame, Region(3000, 0, 10, 10)) is None


def test_preprocess_upscales_and_pads():
    img = np.full((20, 40, 3), 200, np.uint8)
    out = preprocess(img, 64, pad=10)
    assert out.shape == (64 + 20, 128 + 20, 3)
    assert tuple(out[0, 0]) == (200, 200, 200)
    big = np.zeros((100, 50, 3), np.uint8)
    assert preprocess(big, 64, pad=0).shape == (100, 50, 3)


def test_extract_text_new_api_sorted_by_x():
    boxes = np.array([[[50, 0], [60, 0], [60, 10], [50, 10]], [[0, 0], [10, 0], [10, 10], [0, 10]]])
    out = SimpleNamespace(boxes=boxes, txts=("250", "1,"), scores=(0.9, 0.9))
    assert extract_text(out) == "1,250"
    assert extract_text(SimpleNamespace(boxes=None, txts=None)) == ""
    assert extract_text(SimpleNamespace(txts=("WAITING",))) == "WAITING"  # 認識のみ


def test_extract_text_legacy_api():
    result = [[[[30, 0], [40, 0], [40, 9], [30, 9]], "KY", 0.9], [[[0, 0], [9, 0], [9, 9], [0, 9]], "S", 0.9]]
    assert extract_text((result, [0.1])) == "SKY"
    assert extract_text((None, None)) == ""
    assert extract_text(([["12.50", 0.99]], [0.1])) == "12.50"
