import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"


def data_dir() -> Path:
    override = os.environ.get("GBOT_HOME")
    if override:
        return Path(override)
    if IS_WINDOWS:
        return (
            Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
            / "grokbot-cli"
        )
    return Path.home() / ".config" / "groken"


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data: bytes, decrypt: bool) -> bytes:
    if not IS_WINDOWS:
        raise RuntimeError("DPAPI requires Windows")
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(data)
    source = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = _Blob()
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [
        ctypes.POINTER(_Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_Blob),
    ]
    function.restype = wintypes.BOOL
    # UI forbidden; no machine-scope flag, so only the current user can decrypt.
    if not function(
        ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(result.data)


def protect(data: bytes) -> bytes:
    return _dpapi(data, False)


def unprotect(blob: bytes) -> bytes:
    return _dpapi(blob, True)


def app_install_dirs() -> list[Path]:
    paths: list[Path] = []
    if value := os.environ.get("GBOT_APP_DIR"):
        paths.append(Path(value))
    if value := os.environ.get("ProgramFiles"):
        paths.append(Path(value) / "Grok Bot")
    if value := os.environ.get("LOCALAPPDATA"):
        paths.append(Path(value) / "Programs" / "Grok Bot")
    return paths


class _FixedFileInfo(ctypes.Structure):
    _fields_ = [
        (name, wintypes.DWORD)
        for name in (
            "signature",
            "structure_version",
            "file_ms",
            "file_ls",
            "product_ms",
            "product_ls",
            "flags_mask",
            "flags",
            "os",
            "type",
            "subtype",
            "date_ms",
            "date_ls",
        )
    ]


def exe_version(path: Path) -> str | None:
    if not IS_WINDOWS:
        return None
    try:
        version = ctypes.WinDLL("version", use_last_error=True)
        version.GetFileVersionInfoSizeW.argtypes = [
            wintypes.LPCWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        version.GetFileVersionInfoW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        version.GetFileVersionInfoW.restype = wintypes.BOOL
        version.VerQueryValueW.argtypes = [
            ctypes.c_void_p,
            wintypes.LPCWSTR,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.UINT),
        ]
        version.VerQueryValueW.restype = wintypes.BOOL
        unused = wintypes.DWORD()
        size = version.GetFileVersionInfoSizeW(str(path), ctypes.byref(unused))
        if not size:
            return None
        buffer = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(str(path), 0, size, buffer):
            return None
        pointer = ctypes.c_void_p()
        length = wintypes.UINT()
        if not version.VerQueryValueW(
            buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)
        ):
            return None
        if not pointer.value or length.value < ctypes.sizeof(_FixedFileInfo):
            return None
        info = ctypes.cast(pointer, ctypes.POINTER(_FixedFileInfo)).contents
        if info.signature != 0xFEEF04BD:
            return None
        return f"{info.file_ms >> 16}.{info.file_ms & 0xFFFF}.{info.file_ls >> 16}"
    except (OSError, ValueError, AttributeError):
        return None
