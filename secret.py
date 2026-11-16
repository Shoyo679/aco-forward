"""Keep the bot token encrypted with Windows DPAPI: only this Windows account on this PC can read it back.
The token is never shown in the dashboard or written to a log."""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _run(fn, data: bytes) -> bytes:
    out = _Blob()
    if not fn(ctypes.byref(_blob(data)), None, None, None, None, 0x01, ctypes.byref(out)):   # 0x01 = no UI
        raise OSError("Windows couldn't read or protect the token")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def protect(text: str) -> str:
    return base64.b64encode(_run(ctypes.windll.crypt32.CryptProtectData, text.encode())).decode()


def unprotect(stored: str) -> str:
    return _run(ctypes.windll.crypt32.CryptUnprotectData, base64.b64decode(stored)).decode()
