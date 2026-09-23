"""キャプチャーカードの機器番号を調べる。

使い方: python find_capture.py
機器番号 0〜9 を順に開き、開けたものについて解像度を表示し、
映っている画面を capture_test_<番号>.png として保存する。
自分の画面が映っている画像の番号を、設定の「詳細」タブの「キャプチャーの機器番号」に入れる。
"""
from pathlib import Path

import cv2

OUT = Path(__file__).resolve().parent
APIS = [(name, getattr(cv2, name)) for name in ("CAP_DSHOW", "CAP_MSMF") if hasattr(cv2, name)]


def try_open(index, name, api):
    cap = cv2.VideoCapture(index, api)
    if not cap.isOpened():
        cap.release()
        return None
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    frame = None
    for _ in range(30):
        ok, f = cap.read()
        if ok and f is not None:
            frame = f
            break
    cap.release()
    return frame


def main():
    found = False
    for index in range(10):
        for name, api in APIS:
            frame = try_open(index, name, api)
            if frame is None:
                continue
            found = True
            h, w = frame.shape[:2]
            path = OUT / f"capture_test_{index}.png"
            cv2.imwrite(str(path), frame)
            mark = "  ← 1920×1080 OK" if (w, h) == (1920, 1080) else ""
            print(f"機器番号 {index}: 開けました({name}、{w}×{h}){mark}  画像: {path.name}")
            break
        else:
            print(f"機器番号 {index}: 開けません")
    if not found:
        print("\nどの機器番号でも開けませんでした。次を確認してください。")
        print("・キャプチャーカードがUSBに接続され、デバイスマネージャーの「カメラ」などに表示されているか")
        print("・OBS など、ほかのアプリがキャプチャーカードを使っていないか(使っていたら閉じる)")
        print("・Windowsの設定 → プライバシーとセキュリティ → カメラ で")
        print("  「カメラへのアクセス」と「デスクトップアプリがカメラにアクセスできるようにする」がオンか")


if __name__ == "__main__":
    main()
