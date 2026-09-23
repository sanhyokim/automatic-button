"""読み取りテストの結果から、考えられる原因と対処を出す(GUIに依存しない)。"""
from __future__ import annotations


def hints(info: dict) -> list[str]:
    """結果から考えられる原因と対処を返す(GUIに依存しない)。"""
    out: list[str] = []
    res = info.get("results", {})
    det_text, rec_text = res.get(True, ""), res.get(False, "")
    brightness, contrast = info.get("brightness"), info.get("contrast")
    if brightness is not None and brightness < 8 and (contrast or 0) < 4:
        out.append(
            "画像が真っ黒です。対象のアプリが画面の取り込みを禁止している可能性があります。"
            "「詳細」タブの取り込み方法を「キャプチャーカード」にしてください"
        )
    elif contrast is not None and contrast < 4:
        out.append("画像がほぼ一色で、文字が写っていません。範囲の位置を確認してください")
    if info.get("use_det", True) and not det_text and rec_text:
        out.append("「文字検出なし」では読めています。「詳細」タブの「文字検出を使う」をオフにしてください")
    if not info.get("use_det", True) and not rec_text and det_text:
        out.append("「文字検出あり」では読めています。「詳細」タブの「文字検出を使う」をオンにしてください")
    if not det_text and not rec_text and not out:
        out.append("どちらでも読めません。範囲を文字の周りに少し余裕を持たせて設定し直してください")
    for use_det, err in info.get("errors", {}).items():
        out.append(f"OCRエラー({'検出あり' if use_det else '検出なし'}): {err}")
    return out
