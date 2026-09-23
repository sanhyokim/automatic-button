import random

from app.input_control import bezier_path, ease_in_out, random_point_in_region
from app.models import Region, Rule


# T-06
def test_random_point_inside_with_margin():
    rng = random.Random(1)
    r = Region(100, 200, 80, 24)
    xs, ys = set(), set()
    for _ in range(10000):
        x, y = random_point_in_region(r, 2, rng)
        assert r.x + 2 <= x <= r.x + r.w - 1 - 2
        assert r.y + 2 <= y <= r.y + r.h - 1 - 2
        xs.add(x)
        ys.add(y)
    assert len(xs) > 50 and len(ys) > 10  # ランダムに散らばっている


def test_random_point_small_region_uses_center():
    rng = random.Random(2)
    r = Region(10, 20, 4, 3)
    for _ in range(100):
        assert random_point_in_region(r, 2, rng) == r.center


def test_bezier_path_ends_at_target():
    rng = random.Random(3)
    pts = bezier_path((0, 0), (500, 300), 40, rng)
    assert len(pts) == 40
    assert pts[-1] == (500, 300)
    assert ease_in_out(0) == 0 and abs(ease_in_out(1) - 1) < 1e-9
    assert bezier_path((5, 5), (5, 5), 10, rng)[-1] == (5, 5)


def test_region_helpers():
    r = Region(0, 0, 10, 10)
    assert r.intersects(Region(5, 5, 10, 10))
    assert not r.intersects(Region(10, 0, 5, 5))  # 辺が接するだけ
    assert Region(-5, -5, 10, 10).clamp(1920, 1080) == Region(0, 0, 5, 5)
    assert Region(1915, 1075, 10, 10).clamp(1920, 1080) == Region(1915, 1075, 5, 5)
    assert Region(2000, 0, 10, 10).clamp(1920, 1080) is None
    assert Region.from_dict({"x": 1, "y": 2, "w": 3, "h": 4}) == Region(1, 2, 3, 4)
    assert Region.from_dict(None) is None
    assert Region.from_dict({"x": 1}) is None


def test_rule_roundtrip():
    rule = Rule(name="SKY", keyword="SKY", pattern="C")
    rule.regions["button1"] = Region(1, 2, 3, 4)
    d = rule.to_dict()
    back = Rule.from_dict(d)
    assert back == rule
    assert back.list_label() == "SKY | C"
