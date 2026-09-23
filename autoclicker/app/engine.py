"""状態遷移、監視、動作、避難動作、カーソルの退避(ワーカースレッド)。

GUI への通知はすべて queue.Queue を通す。ワーカースレッドから Tkinter を触らない。
"""
from __future__ import annotations

import copy
import queue
import threading
import time
import traceback
from datetime import datetime
from typing import Callable, Optional

from . import parser
from .config import find_rule, get_rules, validate_for_start
from .input_control import InputController, InputError, StopRequested
from .models import Region, Rule
from .ocr import OcrEngine, OcrError

STOPPED = "STOPPED"
STARTING = "STARTING"  # 開始準備中(キャプチャーを開いている間)。GUI表示用
MONITORING = "MONITORING"
EXECUTING = "EXECUTING"
WAIT_RETURN = "WAIT_RETURN"

FRAME_RETRY_COUNT = 3
FRAME_RETRY_INTERVAL = 1.0
OCR_ERROR_LOG_INTERVAL = 10.0


class EngineStop(Exception):
    """回復できない理由による停止。メッセージが停止の理由になる。"""


def timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


class Engine:
    def __init__(
        self,
        ocr: OcrEngine,
        grabber_factory: Optional[Callable[[dict], object]] = None,
        can_start: Optional[Callable[[], Optional[str]]] = None,
    ):
        self.ocr = ocr
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.stop_event = threading.Event()
        self._grabber_factory = grabber_factory or _default_grabber
        self._can_start = can_start
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._stop_reason: Optional[str] = None
        self._state = STOPPED
        self._ocr_error_times: dict[str, float] = {}
        self.input = InputController(self.stop_event)
        self.cfg: dict = {}
        self.grabber = None
        self.number_format = "integer"  # 動作中でもGUIから変更できる

    def set_number_format(self, fmt: str) -> None:
        """数値の形式を切り替える。次に数値を読み取るときから反映する。"""
        if fmt in ("integer", "decimal"):
            self.number_format = fmt

    # ------------------------------------------------------------ 公開API
    @property
    def state(self) -> str:
        return self._state

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def log(self, msg: str) -> None:
        self.events.put(("log", f"{timestamp()} {msg}"))

    def _set_state(self, state: str, reason: str = "") -> None:
        self._state = state
        self.events.put(("state", state, reason))

    def start(self, cfg: dict) -> bool:
        """設定を検証して開始する。検証に不合格なら記録に表示して False。"""
        if self.running:
            return False
        errors = validate_for_start(cfg)
        if self._can_start is not None:
            extra = self._can_start()
            if extra:
                errors.append(extra)
        if errors:
            self.log("開始できません:")
            for e in errors:
                self.log(f"  ・{e}")
            return False
        self.cfg = copy.deepcopy(cfg)
        self.set_number_format(cfg.get("number_format", "integer"))
        self.stop_event.clear()
        with self._lock:
            self._stop_reason = None
        self._ocr_error_times.clear()
        self._set_state(STARTING)
        self._thread = threading.Thread(target=self._run, name="engine", daemon=True)
        self._thread.start()
        return True

    def request_stop(self, reason: str) -> None:
        """どの状態からでも停止を指示する(どのスレッドから呼んでもよい)。"""
        if not self.running:
            return
        with self._lock:
            if self._stop_reason is None:
                self._stop_reason = reason
        self.stop_event.set()

    def join(self, timeout: float = 5.0) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def test_read(self, cfg: dict, region: Region) -> str:
        """読み取りテスト(停止の状態でのみ)。キャプチャーを一時的に開いて1回読む。"""
        if self.running:
            raise EngineStop("停止の状態でのみ使えます")
        det = cfg["detection"]
        grabber = self._grabber_factory(cfg)
        try:
            grabber.open()
            frame = grabber.latest_frame()
            if frame is None:
                raise EngineStop("フレームを取得できません")
            return self.ocr.read_region(frame, region, det["ocr_min_height"], det["ocr_use_det"])
        except OcrError as e:
            raise EngineStop(f"OCRエラー: {e}") from e
        except EngineStop:
            raise
        except Exception as e:
            raise EngineStop(str(e)) from e
        finally:
            try:
                grabber.close()
            except Exception:
                pass

    # ------------------------------------------------------------ ワーカー
    def _run(self) -> None:
        reason = ""
        try:
            self.log("開始準備中(キャプチャー・OCRの準備)")
            try:
                self.ocr.load()
            except OcrError as e:
                raise EngineStop(str(e)) from e
            self.input.check_stop()
            self.grabber = self._grabber_factory(self.cfg)
            try:
                self.grabber.open()
            except Exception as e:
                raise EngineStop(str(e)) from e
            self.input.check_stop()
            self.log("開始")
            self._main_loop()
        except StopRequested:
            with self._lock:
                reason = self._stop_reason or "停止の指示"
        except EngineStop as e:
            reason = str(e)
        except InputError as e:
            reason = f"マウス・キーボード操作でエラー: {e}"
        except Exception as e:
            reason = f"予期しないエラー: {type(e).__name__}: {e}"
            for line in traceback.format_exc().rstrip().splitlines()[-6:]:
                self.log(f"  {line}")
        finally:
            if self.grabber is not None:
                try:
                    self.grabber.close()
                except Exception:
                    pass
                self.grabber = None
            self.log(f"停止: {reason}")
            self._set_state(STOPPED, reason)

    def _main_loop(self) -> None:
        while True:
            self._set_state(MONITORING)
            rule = self._monitor()
            self._set_state(EXECUTING)
            self._execute(rule)
            self._set_state(WAIT_RETURN)
            self._wait_return()
            self.log("WAITINGに復帰(監視を再開)")

    # ---- 読み取り
    def _get_frame(self):
        for attempt in range(FRAME_RETRY_COUNT + 1):
            self.input.check_stop()
            frame = self.grabber.latest_frame()
            if frame is not None:
                return frame
            if attempt < FRAME_RETRY_COUNT:
                self.log(f"フレームを取得できません。再試行します({attempt + 1}/{FRAME_RETRY_COUNT})")
                self.input.interruptible_sleep(FRAME_RETRY_INTERVAL)
        raise EngineStop("フレームを取得できないため停止")

    def _read(self, region: Region) -> str:
        frame = self._get_frame()
        det = self.cfg["detection"]
        try:
            return self.ocr.read_region(frame, region, det["ocr_min_height"], det["ocr_use_det"])
        except OcrError as e:
            msg = str(e)
            now = time.monotonic()
            last = self._ocr_error_times.get(msg)
            if last is None or now - last >= OCR_ERROR_LOG_INTERVAL:
                self._ocr_error_times[msg] = now
                self.log(f"OCRエラー: {msg}")
            return ""

    def _sleep_until(self, t: float) -> None:
        self.input.interruptible_sleep(t - time.monotonic())

    # ---- 監視(MONITORING)
    def _monitor(self) -> Rule:
        region = Region.from_dict(self.cfg["keyword_region"])
        rules = get_rules(self.cfg)
        timing = self.cfg["timing"]
        need = self.cfg["detection"]["keyword_confirm_count"]
        waiting = self.cfg["waiting_text"]
        last_id: Optional[str] = None
        count = 0
        while True:
            t0 = time.monotonic()
            text = self._read(region)
            rule = None if parser.is_waiting(text, waiting) else parser.match_rule(text, rules)
            if rule is None:
                last_id, count = None, 0
            else:
                count = count + 1 if rule.id == last_id else 1
                last_id = rule.id
                if count >= need:
                    self.log(f"キーワード確定: {rule.display_name}({rule.pattern})")
                    return rule
            self._sleep_until(t0 + timing["poll_interval"])

    # ---- 動作(EXECUTING)
    def _execute(self, rule: Rule) -> None:
        timing = self.cfg["timing"]
        delay = self.input.rng.uniform(timing["reaction_delay_min"], timing["reaction_delay_max"])
        deadline = time.monotonic() + delay
        if rule.pattern == "B":
            # 数値の読み取りは反応待ち時間と並行して進める(FR-30)
            value = self._read_number(rule)
            if value is None:
                fallback = find_rule(self.cfg, self.cfg.get("fallback_rule_id"))
                if fallback is None or fallback.pattern not in ("A", "C"):
                    raise EngineStop("避難先のルールが見つからないため停止")
                self._sleep_until(deadline)
                self.log(f"避難動作を実行: {fallback.display_name}({fallback.pattern})")
                self._perform(fallback, None)
            else:
                self._sleep_until(deadline)
                self._perform(rule, value)
        else:
            self._sleep_until(deadline)
            self._perform(rule, None)
        self.log("動作が完了")
        self._step_delay()
        self._retreat()

    def _read_number(self, rule: Rule) -> Optional[str]:
        det = self.cfg["detection"]
        region = rule.region("number")
        max_reads = det["number_max_reads"]
        fmt = self.number_format
        self.log(f"数値の形式: {'整数' if fmt == 'integer' else '小数'}")
        reads: list[str] = []
        while True:
            t0 = time.monotonic()
            raw = self._read(region)
            reads.append(raw)
            ok, value = parser.check_number(raw, fmt)
            result = f"合格 → {value}" if ok else "不合格"
            self.log(f"数値の読み取り {len(reads)}/{max_reads}: 「{raw}」 {result}")
            decision = parser.decide_number(reads, fmt, max_reads, det["number_match_count"])
            if decision.status == parser.CONFIRMED:
                self.log(f"数値を確定: {decision.value}")
                return decision.value
            if decision.status == parser.FAILED:
                self.log("数値を確定できませんでした")
                return None
            self._sleep_until(t0 + det["number_read_interval"])

    def _step_delay(self) -> None:
        t = self.cfg["timing"]
        self.input.random_sleep(t["step_delay_min"], t["step_delay_max"])

    def _click(self, region: Region) -> None:
        t = self.cfg["timing"]
        self.input.click_region(
            region, self.cfg["detection"]["click_margin"], t["move_duration_min"], t["move_duration_max"]
        )

    def _perform(self, rule: Rule, value: Optional[str]) -> None:
        """パターンごとの操作(反応待ち時間のあと)。"""
        t = self.cfg["timing"]
        if rule.pattern == "A":
            self._click(rule.region("button1"))
        elif rule.pattern == "C":
            self._click(rule.region("button1"))
            self._step_delay()
            self._click(rule.region("button2"))
        elif rule.pattern == "B":
            self._click(rule.region("input_field"))
            self._step_delay()
            self.input.hotkey("ctrl", "a")
            self._step_delay()
            self.input.press("delete")
            self._step_delay()
            self.input.type_text(value or "", t["type_interval_min"], t["type_interval_max"])
            self._step_delay()
            self._click(rule.region("button1"))
        else:
            raise EngineStop(f"不明なパターン: {rule.pattern}")

    def _retreat(self) -> None:
        t = self.cfg["timing"]
        region = Region.from_dict(self.cfg["retreat_region"])
        self.input.move_into(
            region, self.cfg["detection"]["click_margin"], t["move_duration_min"], t["move_duration_max"]
        )
        self.log("カーソルを退避")

    # ---- WAITING復帰待ち(WAIT_RETURN)
    def _wait_return(self) -> None:
        region = Region.from_dict(self.cfg["keyword_region"])
        timing = self.cfg["timing"]
        need = self.cfg["detection"]["waiting_confirm_count"]
        waiting = self.cfg["waiting_text"]
        start = time.monotonic()
        count = 0
        while True:
            if time.monotonic() - start >= timing["waiting_timeout"]:
                raise EngineStop("WAITINGに戻らないため停止")
            t0 = time.monotonic()
            text = self._read(region)
            if parser.is_waiting(text, waiting):
                count += 1
                if count >= need:
                    return
            else:
                count = 0
            self._sleep_until(t0 + timing["poll_interval"])


def _default_grabber(cfg: dict):
    from .capture import make_grabber

    return make_grabber(cfg)
