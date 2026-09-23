"""設定の読み書き、初期値、検証(GUI・外部機器に依存しない)。"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

from .models import NUMBER_FORMATS, PATTERNS, REGION_LABELS, REQUIRED_REGIONS, Region, Rule
from .parser import normalize

CONFIG_FILENAME = "config.json"

DEFAULT_CONFIG: dict = {
    "version": 1,
    "capture": {
        # "screen" = このPCの画面を直接取り込む(キャプチャーカードを占有しない)
        # "card"   = キャプチャーカードから取り込む
        "source": "screen",
        "monitor": 1,
        "device_index": 0,
        "width": 1920,
        "height": 1080,
        "fps": 60,
        # 空文字列なら設定しない。1080p60 が出ない機器では "MJPG" を指定する
        "fourcc": "",
    },
    "keyword_region": None,
    "retreat_region": None,
    "waiting_text": "WAITING",
    "fallback_rule_id": None,
    # パターンBで読み取る数値の形式。メインウィンドウでいつでも切り替えられる
    "number_format": "integer",
    "timing": {
        "poll_interval": 0.5,
        "reaction_delay_min": 1.0,
        "reaction_delay_max": 4.0,
        "step_delay_min": 0.5,
        "step_delay_max": 1.0,
        "move_duration_min": 0.2,
        "move_duration_max": 0.5,
        "type_interval_min": 0.05,
        "type_interval_max": 0.15,
        "waiting_timeout": 60.0,
    },
    "detection": {
        "keyword_confirm_count": 2,
        "waiting_confirm_count": 2,
        "number_max_reads": 5,
        "number_match_count": 3,
        "number_read_interval": 0.3,
        "ocr_min_height": 64,
        "ocr_use_det": True,
        "click_margin": 2,
    },
    "gui": {
        "log_max_lines": 200,
    },
    "rules": [],
}

# (最小のキー, 最大のキー, 表示名)
TIMING_RANGES = (
    ("reaction_delay_min", "reaction_delay_max", "反応待ち時間"),
    ("step_delay_min", "step_delay_max", "操作間待ち時間"),
    ("move_duration_min", "move_duration_max", "マウス移動時間"),
    ("type_interval_min", "type_interval_max", "入力の間隔"),
)
TIMING_SINGLES = (
    ("poll_interval", "監視の間隔"),
    ("waiting_timeout", "WAITING復帰のタイムアウト"),
)
# (キー, 表示名, 最小値)
DETECTION_INTS = (
    ("keyword_confirm_count", "キーワード確定の回数", 1),
    ("waiting_confirm_count", "WAITING確定の回数", 1),
    ("number_max_reads", "数値の最大読み取り回数", 1),
    ("number_match_count", "確定に必要な一致回数", 1),
    ("ocr_min_height", "OCRの最小の高さ", 1),
    ("click_margin", "クリックの余白", 0),
)


def app_dir() -> Path:
    """実行ファイル(exe化後)または main.py のあるフォルダー。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    main = sys.modules.get("__main__")
    main_file = getattr(main, "__file__", None)
    if main_file:
        return Path(main_file).resolve().parent
    return Path(__file__).resolve().parent.parent


def default_config_path() -> Path:
    return app_dir() / CONFIG_FILENAME


def default_config() -> dict:
    return copy.deepcopy(DEFAULT_CONFIG)


def _merge(default, loaded):
    """初期値に読み込んだ値を重ねる。型が合わない部分は初期値を使う。"""
    if isinstance(default, dict):
        if not isinstance(loaded, dict):
            return copy.deepcopy(default)
        out = {}
        for key, dval in default.items():
            out[key] = _merge(dval, loaded[key]) if key in loaded else copy.deepcopy(dval)
        for key, lval in loaded.items():
            if key not in out:
                out[key] = lval  # 未知の項目はそのまま残す
        return out
    if default is None:
        return loaded
    if isinstance(default, bool):
        return loaded if isinstance(loaded, bool) else default
    if isinstance(default, (int, float)):
        if isinstance(loaded, (int, float)) and not isinstance(loaded, bool):
            return loaded
        return default
    if isinstance(default, str):
        return loaded if isinstance(loaded, str) else default
    if isinstance(default, list):
        return loaded if isinstance(loaded, list) else copy.deepcopy(default)
    return loaded


def normalize_config(loaded: dict) -> tuple[dict, list[str]]:
    """読み込んだ辞書を初期値で補い、範囲とルールの形を整える。"""
    messages: list[str] = []
    cfg = _merge(DEFAULT_CONFIG, loaded)
    for key in ("keyword_region", "retreat_region"):
        region = Region.from_dict(cfg.get(key))
        if cfg.get(key) is not None and region is None:
            messages.append(f"設定の {key} が正しくないため未設定にしました")
        cfg[key] = region.to_dict() if region else None
    rules = []
    for i, raw in enumerate(cfg.get("rules") or []):
        try:
            rules.append(Rule.from_dict(raw).to_dict())
        except ValueError:
            messages.append(f"設定の {i + 1} 番目のルールが読めないため削除しました")
    cfg["rules"] = rules
    if cfg.get("number_format") not in NUMBER_FORMATS:
        cfg["number_format"] = "integer"
    if cfg["capture"].get("source") not in ("screen", "card"):
        cfg["capture"]["source"] = "screen"
    if cfg.get("fallback_rule_id") is not None and not isinstance(cfg["fallback_rule_id"], str):
        cfg["fallback_rule_id"] = None
    return cfg, messages


def load_config(path: Path) -> tuple[dict, list[str]]:
    """設定を読み込む。(設定, 動作の記録に出すメッセージ) を返す。

    - ファイルがない: 初期値で作る
    - 読み込みに失敗: config.json.bak に退避して初期値で起動
    - 項目が足りない: 初期値で補う
    """
    path = Path(path)
    messages: list[str] = []
    if not path.exists():
        cfg = default_config()
        try:
            save_config(path, cfg)
            messages.append("設定ファイルがないため初期値で作成しました")
        except OSError as e:
            messages.append(f"設定ファイルを作成できません: {e}")
        return cfg, messages
    try:
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict):
            raise ValueError("設定ファイルの形式が正しくありません")
    except (OSError, ValueError) as e:
        bak = path.with_name(path.name + ".bak")
        try:
            os.replace(path, bak)
            messages.append(f"設定ファイルを読めないため {bak.name} に退避し、初期値で起動しました({e})")
        except OSError as e2:
            messages.append(f"設定ファイルを読めず、退避もできません: {e2}")
        cfg = default_config()
        try:
            save_config(path, cfg)
        except OSError:
            pass
        return cfg, messages
    cfg, msgs = normalize_config(loaded)
    messages.extend(msgs)
    return cfg, messages


def save_config(path: Path, cfg: dict) -> None:
    """一時ファイルに書いてから置き換える。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------- 検証


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_settings(cfg: dict) -> list[str]:
    """時間・検出の設定値の検証(GUI-16、8.2節)。エラーの一覧を返す。"""
    errors: list[str] = []
    timing = cfg.get("timing", {})
    for kmin, kmax, label in TIMING_RANGES:
        vmin, vmax = timing.get(kmin), timing.get(kmax)
        if not _is_number(vmin) or not _is_number(vmax):
            errors.append(f"{label}が数値ではありません")
            continue
        if vmin < 0 or vmax < 0:
            errors.append(f"{label}は0以上にしてください")
        if vmin > vmax:
            errors.append(f"{label}の最小が最大より大きくなっています")
    for key, label in TIMING_SINGLES:
        v = timing.get(key)
        if not _is_number(v):
            errors.append(f"{label}が数値ではありません")
        elif v < 0:
            errors.append(f"{label}は0以上にしてください")

    det = cfg.get("detection", {})
    for key, label, minimum in DETECTION_INTS:
        v = det.get(key)
        if not isinstance(v, int) or isinstance(v, bool):
            errors.append(f"{label}が整数ではありません")
        elif v < minimum:
            errors.append(f"{label}は{minimum}以上にしてください")
    v = det.get("number_read_interval")
    if not _is_number(v):
        errors.append("数値の読み取り間隔が数値ではありません")
    elif v < 0:
        errors.append("数値の読み取り間隔は0以上にしてください")
    mc, mr = det.get("number_match_count"), det.get("number_max_reads")
    if isinstance(mc, int) and isinstance(mr, int) and mc > mr:
        errors.append("確定に必要な一致回数が最大読み取り回数より大きくなっています")
    if not isinstance(det.get("ocr_use_det"), bool):
        errors.append("ocr_use_det が true/false ではありません")

    if cfg.get("capture", {}).get("source") not in ("screen", "card"):
        errors.append("取り込み方法が正しくありません")
    dev = cfg.get("capture", {}).get("device_index")
    if not isinstance(dev, int) or isinstance(dev, bool) or dev < 0:
        errors.append("キャプチャーの機器番号は0以上の整数にしてください")

    lines = cfg.get("gui", {}).get("log_max_lines")
    if not isinstance(lines, int) or isinstance(lines, bool) or lines < 1:
        errors.append("動作の記録の最大行数は1以上の整数にしてください")

    if cfg.get("number_format") not in NUMBER_FORMATS:
        errors.append("数値の形式が正しくありません")
    if not normalize(cfg.get("waiting_text")):
        errors.append("待機表示の文字が空です")
    return errors


def validate_rule(rule: Rule, other_rules: list[Rule], waiting_text: str = "") -> list[str]:
    """ルールの保存時の検証(8.1節、GUI-24)。other_rules は自分以外のルール。"""
    errors: list[str] = []
    key = normalize(rule.keyword)
    if not key:
        errors.append("キーワードが空です")
    else:
        for other in other_rules:
            if other.id != rule.id and normalize(other.keyword) == key:
                errors.append(f"キーワードがルール「{other.display_name}」と重複しています")
                break
        if waiting_text and key == normalize(waiting_text):
            errors.append("キーワードが待機表示の文字と同じです")
    if rule.pattern not in PATTERNS:
        errors.append("パターンが選ばれていません")
        return errors
    for rkey in REQUIRED_REGIONS[rule.pattern]:
        if rule.regions.get(rkey) is None:
            errors.append(f"{REGION_LABELS[rkey]}が設定されていません")
    return errors


def get_rules(cfg: dict) -> list[Rule]:
    return [Rule.from_dict(r) for r in cfg.get("rules", [])]


def find_rule(cfg: dict, rule_id: Optional[str]) -> Optional[Rule]:
    if not rule_id:
        return None
    for r in get_rules(cfg):
        if r.id == rule_id:
            return r
    return None


def validate_for_start(cfg: dict) -> list[str]:
    """開始時の検証(8.2節)。キャプチャーカードの確認はエンジンが行う。"""
    errors: list[str] = []
    if Region.from_dict(cfg.get("keyword_region")) is None:
        errors.append("キーワード範囲が設定されていません")
    if Region.from_dict(cfg.get("retreat_region")) is None:
        errors.append("退避エリアが設定されていません")
    rules = get_rules(cfg)
    if not rules:
        errors.append("ルールが1つもありません")
    for rule in rules:
        others = [r for r in rules if r.id != rule.id]
        for e in validate_rule(rule, others, cfg.get("waiting_text", "")):
            errors.append(f"ルール「{rule.display_name}」: {e}")
    if any(r.pattern == "B" for r in rules):
        fid = cfg.get("fallback_rule_id")
        fb = find_rule(cfg, fid)
        if not fid:
            errors.append("パターンBのルールがあるため、避難先の設定が必要です")
        elif fb is None:
            errors.append("避難先のルールが見つかりません")
        elif fb.pattern not in ("A", "C"):
            errors.append("避難先にはパターンAまたはCのルールを指定してください")
    errors.extend(validate_settings(cfg))
    return errors


def retreat_overlaps(cfg: dict) -> list[str]:
    """退避エリアと重なっている読み取り範囲の名前の一覧(GUI-17)。"""
    retreat = Region.from_dict(cfg.get("retreat_region"))
    if retreat is None:
        return []
    hits: list[str] = []
    kw = Region.from_dict(cfg.get("keyword_region"))
    if kw is not None and retreat.intersects(kw):
        hits.append("キーワード範囲")
    for rule in get_rules(cfg):
        num = rule.regions.get("number")
        if rule.pattern == "B" and num is not None and retreat.intersects(num):
            hits.append(f"ルール「{rule.display_name}」の数値範囲")
    return hits
