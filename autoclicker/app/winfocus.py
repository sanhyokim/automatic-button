"""クリック先のウィンドウを前面にする(Windows のみ。ほかの環境では何もしない)。

前面にないアプリは、最初のクリックを「ウィンドウを前面にする」ためだけに使い、
ボタンのクリックとして扱わないことがある。クリックの前に前面にしておく。
"""
from __future__ import annotations

import sys

GA_ROOT = 2


def activate_window_at(x: int, y: int) -> bool:
    """(x, y) にあるウィンドウが前面でなければ前面にする。前面にした場合は True。"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.WindowFromPoint.restype = wintypes.HWND
        user32.WindowFromPoint.argtypes = [wintypes.POINT]
        user32.GetAncestor.restype = wintypes.HWND
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]

        hwnd = user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
        if not hwnd:
            return False
        root = user32.GetAncestor(hwnd, GA_ROOT) or hwnd
        fg = user32.GetForegroundWindow()
        if fg == root:
            return False
        # 前面のウィンドウの入力スレッドに一時的につなぐと、SetForegroundWindow が通りやすい
        cur_tid = kernel32.GetCurrentThreadId()
        fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        attached = bool(fg_tid) and fg_tid != cur_tid and user32.AttachThreadInput(cur_tid, fg_tid, True)
        try:
            ok = bool(user32.SetForegroundWindow(root))
        finally:
            if attached:
                user32.AttachThreadInput(cur_tid, fg_tid, False)
        return ok
    except Exception:
        return False
