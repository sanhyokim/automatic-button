"""エンジンの流れを、偽のキャプチャー・OCR・pyautogui で確認する。"""
import json
import threading
import time

import numpy as np
import pytest

from app import engine as eng
from app import input_control
from app.config import DEFAULT_CONFIG
from app.models import Region, Rule

KW = Region(0, 0, 100, 30)
NUM = Region(200, 0, 100, 30)


class FakeGrabber:
    def open(self):
        pass

    def latest_frame(self):
        return np.zeros((1080, 1920, 3), np.uint8)

    def close(self):
        pass


class FakeOcr:
    """範囲ごとに、読み取り結果を関数で返す。"""

    def __init__(self, keyword_fn, number_fn=lambda n: ""):
        self.keyword_fn = keyword_fn
        self.number_fn = number_fn
        self.kw_calls = 0
        self.num_calls = 0

    def load(self):
        pass

    def read_region(self, frame, region, min_height, use_det):
        if region == KW:
            self.kw_calls += 1
            return self.keyword_fn(self.kw_calls)
        self.num_calls += 1
        return self.number_fn(self.num_calls)


class FakePag:
    def __init__(self):
        self.pos = (960, 540)
        self.ops = []
        self.held = set()
        self.down = False
        self.lock = threading.Lock()

    def position(self):
        return self.pos

    def moveTo(self, x, y, _pause=True):
        self.pos = (x, y)

    def mouseDown(self, x, y, button="left", _pause=True):
        self.ops.append(("click", x, y))
        self.down = True

    def mouseUp(self, x, y, button="left", _pause=True):
        self.down = False

    def keyDown(self, key, _pause=True):
        self.ops.append(("key", key))
        self.held.add(key)

    def keyUp(self, key, _pause=True):
        self.held.discard(key)


@pytest.fixture
def pag(monkeypatch):
    fake = FakePag()
    monkeypatch.setattr(input_control, "_pyautogui", fake)
    return fake


def make_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    cfg["keyword_region"] = KW.to_dict()
    cfg["retreat_region"] = Region(1800, 1000, 100, 50).to_dict()
    t = cfg["timing"]
    for k in list(t):
        t[k] = 0.0
    t["move_duration_min"] = t["move_duration_max"] = 0.02
    t["poll_interval"] = 0.001
    t["waiting_timeout"] = 0.3
    cfg["detection"]["number_read_interval"] = 0.001
    a = Rule(name="SKY", keyword="SKY", pattern="A")
    a.regions["button1"] = Region(1000, 500, 50, 20)
    c = Rule(name="SEA", keyword="SEA", pattern="C")
    c.regions.update(button1=Region(1100, 500, 50, 20), button2=Region(1200, 500, 50, 20))
    b = Rule(name="NUM", keyword="NUM", pattern="B")
    b.regions.update(number=NUM, input_field=Region(300, 300, 80, 20), button1=Region(400, 300, 50, 20))
    cfg["rules"] = [a.to_dict(), c.to_dict(), b.to_dict()]
    cfg["fallback_rule_id"] = c.id
    cfg["number_format"] = "decimal"
    return cfg


def in_region(op, region):
    return region.x <= op[1] < region.x + region.w and region.y <= op[2] < region.y + region.h


def run_until_stopped(engine, cfg, timeout=5.0, stop_when=None):
    assert engine.start(cfg)
    deadline = time.monotonic() + timeout
    while engine.running and time.monotonic() < deadline:
        if stop_when and stop_when():
            engine.request_stop("テスト")
        time.sleep(0.005)
    engine.join(2)
    assert not engine.running
    events = []
    while not engine.events.empty():
        events.append(engine.events.get())
    return events


def logs(events):
    return [e[1] for e in events if e[0] == "log"]


def states(events):
    return [e[1] for e in events if e[0] == "state"]


def test_pattern_b_then_wait_timeout(pag):
    # WAITING → NUM → NUM (確定) → 以後 NUM のまま(WAITINGに戻らない)
    seq = lambda n: "WAITING" if n <= 2 else "NUM"
    ocr = FakeOcr(seq, number_fn=lambda n: ["12.50", "12.5", "12.50", "12.50", "12.50"][n - 1])
    engine = eng.Engine(ocr, grabber_factory=lambda cfg: FakeGrabber())
    events = run_until_stopped(engine, make_config())
    kinds = [op[0] for op in pag.ops]
    assert kinds == ["click"] + ["key"] * 8 + ["click"]
    assert pag.ops[1:4] == [("key", "ctrl"), ("key", "a"), ("key", "delete")]
    assert "".join(op[1] for op in pag.ops[4:9]) == "12.50"
    assert not pag.held and not pag.down  # 押したままのキー・ボタンがない
    assert in_region(pag.ops[0], Region(300 + 2, 300 + 2, 80 - 4, 20 - 4))
    assert in_region(pag.ops[-1], Region(400, 300, 50, 20))
    assert ocr.num_calls == 4  # 4回目で確定
    assert in_region(("", *pag.pos), Region(1800, 1000, 100, 50))  # 退避
    assert "enter" not in str(pag.ops).lower()
    assert states(events)[-4:] == [eng.MONITORING, eng.EXECUTING, eng.WAIT_RETURN, eng.STOPPED]
    assert events[-1][2] == "WAITINGに戻らないため停止(最後の読み取り: 「NUM」)"
    assert any("数値を確定: 12.50" in l for l in logs(events))


def test_pattern_b_fallback_and_return(pag):
    kw = lambda n: {3: "NUM", 4: "NUM"}.get(n, "WAITING")
    ocr = FakeOcr(kw, number_fn=lambda n: "??")
    engine = eng.Engine(ocr, grabber_factory=lambda cfg: FakeGrabber())
    events = run_until_stopped(engine, make_config(), stop_when=lambda: ocr.kw_calls > 20)
    # 避難先はパターンC: ボタン1 → ボタン2
    assert [op[0] for op in pag.ops] == ["click", "click"]
    assert in_region(pag.ops[0], Region(1100, 500, 50, 20))
    assert in_region(pag.ops[1], Region(1200, 500, 50, 20))
    assert ocr.num_calls == 3  # 3回で打ち切り
    text = "\n".join(logs(events))
    assert "数値を確定できませんでした" in text and "避難動作を実行" in text
    assert "WAITINGに復帰" in text
    assert events[-1] == ("state", eng.STOPPED, "テスト")


def test_no_double_action_and_confirm_count(pag):
    # SKY が1回だけ出ても動作しない。2回連続で確定。確定後 SKY のままでも二度目は起きない
    kw = lambda n: {2: "SKY", 3: "WAITING"}.get(n, "SKY" if n >= 5 else "WAITING")
    ocr = FakeOcr(kw)
    engine = eng.Engine(ocr, grabber_factory=lambda cfg: FakeGrabber())
    events = run_until_stopped(engine, make_config())
    assert [op[0] for op in pag.ops] == ["click"]
    assert events[-1][2].startswith("WAITINGに戻らないため停止")


def test_stop_during_move(pag, monkeypatch):
    kw = lambda n: "SKY"
    ocr = FakeOcr(kw)
    cfg = make_config()
    cfg["timing"]["move_duration_min"] = cfg["timing"]["move_duration_max"] = 5.0
    engine = eng.Engine(ocr, grabber_factory=lambda cfg: FakeGrabber())
    moved = {"n": 0}
    orig = pag.moveTo

    def counting(x, y, _pause=True):
        moved["n"] += 1
        orig(x, y)

    pag.moveTo = counting
    t0 = time.monotonic()
    events = run_until_stopped(engine, cfg, stop_when=lambda: moved["n"] > 3)
    assert time.monotonic() - t0 < 2.0
    assert pag.ops == []  # クリック前に止まった
    assert events[-1] == ("state", eng.STOPPED, "テスト")


def test_start_validation_fails(pag):
    cfg = make_config()
    cfg["retreat_region"] = None
    engine = eng.Engine(FakeOcr(lambda n: ""), grabber_factory=lambda cfg: FakeGrabber())
    assert not engine.start(cfg)
    assert any("退避エリア" in e[1] for e in list(engine.events.queue))


def test_capture_open_error(pag):
    class Bad(FakeGrabber):
        def open(self):
            raise RuntimeError("キャプチャーカードを開けません")

    engine = eng.Engine(FakeOcr(lambda n: ""), grabber_factory=lambda cfg: Bad())
    events = run_until_stopped(engine, make_config())
    assert events[-1] == ("state", eng.STOPPED, "キャプチャーカードを開けません")


def test_frame_lost_stops(pag, monkeypatch):
    monkeypatch.setattr(eng, "FRAME_RETRY_INTERVAL", 0.01)

    class Lost(FakeGrabber):
        def latest_frame(self):
            return None

    engine = eng.Engine(FakeOcr(lambda n: ""), grabber_factory=lambda cfg: Lost())
    events = run_until_stopped(engine, make_config())
    assert events[-1][2] == "フレームを取得できないため停止"
    assert sum("再試行" in l for l in logs(events)) == 3


def test_number_format_switch_while_running(pag):
    # 開始時の設定(整数)で判定し、不正な形式への切り替えは無視する
    kw = lambda n: "NUM" if n in (2, 3) else "WAITING"
    ocr = FakeOcr(kw, number_fn=lambda n: "1,250")
    engine = eng.Engine(ocr, grabber_factory=lambda cfg: FakeGrabber())
    engine.set_number_format("decimal")
    cfg = make_config()
    cfg["number_format"] = "integer"
    events = run_until_stopped(engine, cfg, stop_when=lambda: ocr.kw_calls > 15)
    assert "".join(op[1] for op in pag.ops[4:8]) == "1250"
    assert any("数値の形式: 整数" in l for l in logs(events))
    engine.set_number_format("bogus")
    assert engine.number_format == "integer"


def test_blank_read_does_not_reset_and_misread_logged(pag):
    # SKY → 空 → SKY で確定する。一致しない文字は記録に出る
    seq = {1: "WAITING", 2: "SKY", 3: "", 4: "SKY", 5: "WAlTING", 6: "", 7: "WAITING"}
    kw = lambda n: seq.get(n, "XYZ")
    ocr = FakeOcr(kw)
    engine = eng.Engine(ocr, grabber_factory=lambda cfg: FakeGrabber())
    events = run_until_stopped(engine, make_config(), stop_when=lambda: ocr.kw_calls > 12)
    assert [op[0] for op in pag.ops] == ["click"]
    text = "\n".join(logs(events))
    assert "WAITINGに復帰" in text
    assert text.count("読み取り: 「XYZ」(一致なし)") == 1  # 変わったときだけ記録
