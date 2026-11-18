"""Soltar archivos desde el Explorador de Windows sobre una ventana Tk (solo ctypes).

Se usa WM_DROPFILES: DragAcceptFiles + subclase del WndProc de la ventana superior.
En otros sistemas `enable_file_drop` no hace nada y devuelve False.
"""
from __future__ import annotations

import sys
from typing import Callable

WM_DROPFILES = 0x0233
GWL_WNDPROC = -4
MSGFLT_ALLOW = 1
WM_COPYGLOBALDATA = 0x0049

_keep = []  # evita que el recolector libere el callback


def enable_file_drop(root, callback: Callable[[list[str], int, int], None]) -> bool:
    """callback(rutas, x_root, y_root) se invoca en el hilo de Tk."""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    user32, shell32 = ctypes.windll.user32, ctypes.windll.shell32
    root.update_idletasks()
    hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()

    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint,
                                 ctypes.c_size_t, ctypes.c_ssize_t)
    user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
                                       ctypes.c_size_t, ctypes.c_ssize_t]
    user32.CallWindowProcW.restype = ctypes.c_ssize_t
    user32.GetParent.restype = ctypes.c_void_p
    shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_uint]
    shell32.DragQueryFileW.restype = ctypes.c_uint
    shell32.DragFinish.argtypes = [ctypes.c_void_p]

    def wndproc(h, msg, wparam, lparam):
        if msg == WM_DROPFILES:
            hdrop = wparam
            n = shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
            files = []
            for i in range(n):
                length = shell32.DragQueryFileW(hdrop, i, None, 0)
                buf = ctypes.create_unicode_buffer(length + 1)
                shell32.DragQueryFileW(hdrop, i, buf, length + 1)
                files.append(buf.value)
            shell32.DragFinish(hdrop)
            pt = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            root.after(0, lambda: callback(files, pt.x, pt.y))
            return 0
        return user32.CallWindowProcW(old_proc, h, msg, wparam, lparam)

    proc = WNDPROC(wndproc)
    _keep.append(proc)
    old_proc = user32.SetWindowLongPtrW(hwnd, GWL_WNDPROC, ctypes.cast(proc, ctypes.c_void_p))
    if not old_proc:
        return False
    # permite soltar aunque la app corra con distinto nivel de integridad
    try:
        for m in (WM_DROPFILES, WM_COPYGLOBALDATA):
            user32.ChangeWindowMessageFilterEx(hwnd, m, MSGFLT_ALLOW, None)
    except Exception:  # noqa: BLE001
        pass
    shell32.DragAcceptFiles(ctypes.c_void_p(hwnd), True)
    return True
