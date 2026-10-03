"""Arquivo de sessão criptografado.

No Windows usa DPAPI (CryptProtectData): o arquivo só pode ser lido pelo mesmo
usuário do Windows nesta máquina. Copiar o arquivo para outro PC não serve de nada.
Em outros sistemas grava JSON com permissão 600.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

_lock = threading.RLock()

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_Blob), wintypes.LPCWSTR, ctypes.POINTER(_Blob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob),
    ]
    _crypt32.CryptProtectData.restype = wintypes.BOOL
    _crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob),
    ]
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p

    _UI_FORBIDDEN = 0x1
    _ENTROPY = b"avatarize/session/v1"

    def _blob(data: bytes) -> tuple[_Blob, ctypes.Array]:
        buf = ctypes.create_string_buffer(data, len(data))
        return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    def _take(out: _Blob) -> bytes:
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            _kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))

    def _protect(data: bytes) -> bytes:
        src, _keep_src = _blob(data)
        ent, _keep_ent = _blob(_ENTROPY)
        out = _Blob()
        if not _crypt32.CryptProtectData(ctypes.byref(src), "Avatarize", ctypes.byref(ent),
                                         None, None, _UI_FORBIDDEN, ctypes.byref(out)):
            raise ctypes.WinError(ctypes.get_last_error())
        return _take(out)

    def _unprotect(data: bytes) -> bytes:
        src, _keep_src = _blob(data)
        ent, _keep_ent = _blob(_ENTROPY)
        out = _Blob()
        if not _crypt32.CryptUnprotectData(ctypes.byref(src), None, ctypes.byref(ent),
                                           None, None, _UI_FORBIDDEN, ctypes.byref(out)):
            raise ctypes.WinError(ctypes.get_last_error())
        return _take(out)

else:
    def _protect(data: bytes) -> bytes:
        return data

    def _unprotect(data: bytes) -> bytes:
        return data


class SecureFile:
    """Dicionário JSON persistido de forma criptografada. Seguro entre threads."""

    def __init__(self, path: Path):
        self.path = path

    def _read(self) -> dict:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return {}
        try:
            data = json.loads(_unprotect(raw).decode("utf-8"))
        except Exception:
            # Corrompido ou criado por outro usuário do Windows: trata como "sem login".
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict) -> None:
        blob = _protect(json.dumps(data).encode("utf-8"))
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_bytes(blob)
        if sys.platform != "win32":
            os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def load(self) -> dict:
        with _lock:
            return self._read()

    def set(self, key: str, value) -> None:
        with _lock:
            data = self._read()
            data[key] = value
            self._write(data)

    def delete(self) -> None:
        with _lock:
            self.path.unlink(missing_ok=True)
