"""Windows folders as Windows itself has them, never from the environment a caller can set."""

import sys
import uuid
from pathlib import Path


# FOLDERID_RoamingAppData: what %APPDATA% normally names, taken from the shell, which follows the user's
# registry (and any folder redirection) but not the environment.
_ROAMING_APP_DATA = uuid.UUID("{3EB685DB-65F9-4CF6-A03A-E3EF65729F3D}")
# FOLDERID_LocalAppData, FOLDERID_ProgramFiles and FOLDERID_ProgramFilesX86: where browsers are installed.
_LOCAL_APP_DATA = uuid.UUID("{F1B32785-6FBA-4FCF-9D55-7B8E7F157091}")
_PROGRAM_FILES = uuid.UUID("{905E63B6-C1BF-494E-B29C-65B732D3D21A}")
_PROGRAM_FILES_X86 = uuid.UUID("{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}")


def roaming_app_data() -> Path | None:
    """Return the user's roaming AppData folder on Windows, or None elsewhere or when Windows does not say."""
    return _known_folder(_ROAMING_APP_DATA)


def install_folders() -> tuple[Path, ...]:
    """Return the folders programs are installed in on Windows: Program Files, its x86 twin and the user's local
    AppData, as Windows has them, each once. Empty elsewhere."""
    found: list[Path] = []
    for folder in (_PROGRAM_FILES, _PROGRAM_FILES_X86, _LOCAL_APP_DATA):
        path = _known_folder(folder)
        if path is not None and path not in found:
            found.append(path)
    return tuple(found)


def _known_folder(known: uuid.UUID) -> Path | None:
    if sys.platform != "win32":
        return None
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    class GUID(ctypes.Structure):
        _fields_ = (
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", wintypes.BYTE * 8),
        )

    folder = GUID.from_buffer_copy(known.bytes_le)
    found = ctypes.c_wchar_p()
    try:
        windll = ctypes.windll  # type: ignore[attr-defined]
        if windll.shell32.SHGetKnownFolderPath(ctypes.byref(folder), 0, None, ctypes.byref(found)) != 0:
            return None
        return Path(found.value) if found.value else None
    except OSError:
        return None
    finally:
        if found:
            ctypes.windll.ole32.CoTaskMemFree(found)  # type: ignore[attr-defined]


def system_directory() -> Path | None:
    """Return Windows' System32 folder, as Windows has it, or None elsewhere."""
    if sys.platform != "win32":
        return None
    import ctypes  # noqa: PLC0415

    buffer = ctypes.create_unicode_buffer(260)
    try:
        length = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))  # type: ignore[attr-defined]
    except OSError:
        return None
    return Path(buffer.value) if 0 < length < len(buffer) else None
