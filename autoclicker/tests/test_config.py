import json

from app.config import (
    DEFAULT_CONFIG,
    load_config,
    retreat_overlaps,
    save_config,
    validate_for_start,
    validate_rule,
    validate_settings,
)
from app.models import Region, Rule


def region(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


# T-07
def test_missing_file_creates_defaults(tmp_path):
    path = tmp_path / "config.json"
    cfg, msgs = load_config(path)
    assert cfg == DEFAULT_CONFIG
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == DEFAULT_CONFIG
    assert msgs


def test_broken_file_backed_up(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{ broken", encoding="utf-8")
    cfg, msgs = load_config(path)
    assert cfg == DEFAULT_CONFIG
    assert (tmp_path / "config.json.bak").read_text(encoding="utf-8") == "{ broken"
    assert json.loads(path.read_text(encoding="utf-8")) == DEFAULT_CONFIG
    assert any("bak" in m for m in msgs)


def test_non_dict_file_backed_up(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("[1, 2]", encoding="utf-8")
    cfg, _ = load_config(path)
    assert cfg == DEFAULT_CONFIG
    assert (tmp_path / "config.json.bak").exists()


def test_missing_items_filled(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "timing": {"poll_interval": 0.8},
                "waiting_text": "READY",
                "rules": [{"keyword": "SKY", "pattern": "A"}],
            }
        ),
        encoding="utf-8",
    )
    cfg, _ = load_config(path)
    assert cfg["timing"]["poll_interval"] == 0.8
    assert cfg["timing"]["reaction_delay_max"] == 4.0
    assert cfg["detection"] == DEFAULT_CONFIG["detection"]
    assert cfg["waiting_text"] == "READY"
    assert cfg["capture"]["device_index"] == 0
    rule = cfg["rules"][0]
    assert rule["id"] and rule["regions"]["button1"] is None


def test_wrong_types_replaced(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"timing": 5, "detection": {"ocr_use_det": "yes", "number_max_reads": "5"}}))
    cfg, _ = load_config(path)
    assert cfg["timing"] == DEFAULT_CONFIG["timing"]
    assert cfg["detection"]["ocr_use_det"] is True
    assert cfg["detection"]["number_max_reads"] == 5


def test_save_is_atomic_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    cfg, _ = load_config(path)
    cfg["waiting_text"] = "待機"
    save_config(path, cfg)
    again, _ = load_config(path)
    assert again["waiting_text"] == "待機"
    assert [p.name for p in tmp_path.iterdir()] == ["config.json"]


# T-08
def test_retreat_overlap():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    cfg["keyword_region"] = region(100, 100, 50, 20)
    rule = Rule(name="NUM", keyword="NUM", pattern="B")
    rule.regions["number"] = Region(500, 500, 60, 20)
    cfg["rules"] = [rule.to_dict()]

    cfg["retreat_region"] = region(0, 0, 50, 50)
    assert retreat_overlaps(cfg) == []
    cfg["retreat_region"] = region(140, 110, 50, 50)
    assert retreat_overlaps(cfg) == ["キーワード範囲"]
    cfg["retreat_region"] = region(550, 510, 50, 50)
    assert retreat_overlaps(cfg) == ["ルール「NUM」の数値範囲"]
    cfg["retreat_region"] = region(150, 100, 50, 50)  # 辺が接するだけ
    assert retreat_overlaps(cfg) == []


# 検証
def valid_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    cfg["keyword_region"] = region(0, 0, 100, 30)
    cfg["retreat_region"] = region(1800, 1000, 100, 50)
    a = Rule(name="SKY", keyword="SKY", pattern="A")
    a.regions["button1"] = Region(10, 10, 50, 20)
    b = Rule(name="NUM", keyword="NUM", pattern="B")
    b.regions.update(number=Region(1, 1, 5, 5), input_field=Region(2, 2, 5, 5), button1=Region(3, 3, 5, 5))
    cfg["rules"] = [a.to_dict(), b.to_dict()]
    cfg["fallback_rule_id"] = a.id
    return cfg


def test_validate_for_start_ok():
    assert validate_for_start(valid_config()) == []


def test_validate_for_start_errors():
    cfg = valid_config()
    cfg["keyword_region"] = None
    cfg["retreat_region"] = None
    cfg["fallback_rule_id"] = None
    errs = validate_for_start(cfg)
    assert any("キーワード範囲" in e for e in errs)
    assert any("退避エリア" in e for e in errs)
    assert any("避難先" in e for e in errs)

    cfg = valid_config()
    cfg["fallback_rule_id"] = cfg["rules"][1]["id"]  # パターンB
    assert any("パターンAまたはC" in e for e in validate_for_start(cfg))
    cfg["fallback_rule_id"] = "missing"
    assert any("見つかりません" in e for e in validate_for_start(cfg))

    cfg = valid_config()
    cfg["rules"] = []
    assert any("ルールが1つも" in e for e in validate_for_start(cfg))


def test_validate_settings():
    cfg = valid_config()
    assert validate_settings(cfg) == []
    cfg["timing"]["step_delay_min"] = 2.0
    cfg["detection"]["number_match_count"] = 6
    cfg["timing"]["poll_interval"] = -1
    errs = validate_settings(cfg)
    assert any("操作間待ち時間" in e for e in errs)
    assert any("一致回数" in e for e in errs)
    assert any("監視の間隔" in e for e in errs)


def test_validate_rule():
    other = Rule(name="SKY", keyword="SKY", pattern="A")
    r = Rule(name="x", keyword=" s k y ", pattern="C")
    errs = validate_rule(r, [other], "WAITING")
    assert any("重複" in e for e in errs)
    assert any("ボタン1" in e for e in errs) and any("ボタン2" in e for e in errs)
    assert any("キーワードが空" in e for e in validate_rule(Rule(keyword=" "), []))
    assert any("待機表示" in e for e in validate_rule(Rule(keyword="waiting"), [], "WAITING"))


def test_number_format_default_and_invalid(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"number_format": "hex"}), encoding="utf-8")
    cfg, _ = load_config(path)
    assert cfg["number_format"] == "integer"
    path.write_text(json.dumps({"number_format": "decimal"}), encoding="utf-8")
    assert load_config(path)[0]["number_format"] == "decimal"


def test_capture_source_default_and_invalid(tmp_path):
    from app.capture import FrameGrabber, ScreenGrabber, make_grabber

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"capture": {"device_index": 0}}), encoding="utf-8")
    cfg, _ = load_config(path)
    assert cfg["capture"]["source"] == "screen"  # 既存の設定ファイルでも画面の取り込みになる
    assert isinstance(make_grabber(cfg), ScreenGrabber)
    cfg["capture"]["source"] = "card"
    assert isinstance(make_grabber(cfg), FrameGrabber)
    path.write_text(json.dumps({"capture": {"source": "usb"}}), encoding="utf-8")
    assert load_config(path)[0]["capture"]["source"] == "screen"


def test_pick_primary_monitor():
    from app.capture import pick_primary

    allmon = {"left": -1920, "top": 0, "width": 3840, "height": 1080}
    second = {"left": -1920, "top": 0, "width": 1920, "height": 1080}
    primary = {"left": 0, "top": 0, "width": 1920, "height": 1080}
    assert pick_primary([allmon, second, primary]) is primary  # 1番目がメインでない場合
    assert pick_primary([allmon, primary, second]) is primary
    assert pick_primary([allmon]) is None
