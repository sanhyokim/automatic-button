from app.diagnostics import hints


def test_black_image():
    h = hints({"results": {True: "", False: ""}, "brightness": 0.0, "contrast": 0.0, "use_det": True})
    assert any("真っ黒" in x for x in h)


def test_suggest_turn_off_det():
    h = hints({"results": {True: "", False: "SKY"}, "brightness": 120, "contrast": 50, "use_det": True})
    assert any("オフ" in x for x in h)


def test_ok_no_hint():
    assert hints({"results": {True: "SKY", False: "SKY"}, "brightness": 120, "contrast": 50, "use_det": True}) == []
