from setuptools import setup
import importlib.util
import os
import platform
import subprocess
import sys
from pathlib import Path

APP = ["maat_notepad.py"]
ICON_FILE = "icon.icns" if Path("icon.icns").exists() else None
DATA_FILES = [ICON_FILE] if ICON_FILE else []
BUILD_ARCH = os.environ.get("MAAT_PY2APP_ARCH", "").strip() or platform.machine().lower()
ALLOW_PYTHON_313 = os.environ.get("MAAT_ALLOW_PYTHON_3_13", "").strip()


def _binary_arches(path: str) -> set[str]:
    try:
        out = subprocess.check_output(
            ["/usr/bin/lipo", "-archs", path],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return {item.strip() for item in out.split() if item.strip()}
    except Exception:
        return set()


def _is_forbidden_builder_python(path: str | None) -> bool:
    if not path:
        return False
    try:
        resolved = str(Path(path).resolve())
    except Exception:
        resolved = os.path.realpath(path)
    forbidden_prefixes = (
        "/usr/bin/",
        "/System/",
        "/Library/Developer/CommandLineTools/usr/bin/",
    )
    return resolved.startswith(forbidden_prefixes)


def _validate_build_environment():
    version_mm = f"{sys.version_info.major}.{sys.version_info.minor}"
    if version_mm == "3.13" and not ALLOW_PYTHON_313:
        raise SystemExit(
            "Python 3.13 wird fuer py2app hier standardmaessig vermieden.\n"
            "Bitte nutze bevorzugt Python 3.12, 3.11 oder 3.10\n"
            "oder setze bewusst MAAT_ALLOW_PYTHON_3_13=1."
        )

    if _is_forbidden_builder_python(sys.executable):
        raise SystemExit(
            "Dieses setup.py wurde mit Apples System-/CLT-Python gestartet:\n"
            f"  {sys.executable}\n\n"
            "Das fuehrt bei py2app hier schnell zu kaputten Bundles "
            "(z.B. fehlendes 'encodings').\n"
            "Nutze stattdessen einen echten Python.org-, Homebrew- oder pyenv-Python "
            "und starte den Build ueber build_intel_app.command oder build_arm_app.command."
        )

    if BUILD_ARCH not in {"x86_64", "arm64"}:
        raise SystemExit(
            f"Ungueltige Zielarchitektur: {BUILD_ARCH}\n"
            "Erlaubt sind nur: x86_64 oder arm64"
        )

    machine = platform.machine().lower()
    if machine != BUILD_ARCH:
        if BUILD_ARCH == "x86_64":
            hint = (
                "Intel-Build angefordert, aber dieses setup.py laeuft nicht unter x86_64.\n"
                "Starte den Build auf Apple-Silicon mit:\n"
                "  arch -x86_64 python3 setup.py py2app\n"
                "oder nutze build_intel_app.command."
            )
        else:
            hint = (
                "ARM-Build angefordert, aber dieses setup.py laeuft nicht unter arm64.\n"
                "Starte den Build nativ unter Apple-Silicon mit:\n"
                "  python3 setup.py py2app\n"
                "oder nutze build_arm_app.command."
            )
        raise SystemExit(hint)

    imaging_spec = importlib.util.find_spec("PIL._imaging")
    if not imaging_spec or not imaging_spec.origin:
        raise SystemExit(
            "Pillow ist fuer den App-Build nicht verfuegbar.\n"
            "Installiere es im Build-Venv neu, z.B. mit:\n"
            "  python -m pip install --upgrade pillow"
        )

    arches = _binary_arches(imaging_spec.origin)
    if arches and BUILD_ARCH not in arches:
        raise SystemExit(
            f"Pillow passt nicht zur Zielarchitektur {BUILD_ARCH}: {imaging_spec.origin}\n"
            f"Gefundene Architekturen: {', '.join(sorted(arches))}\n"
            "Installiere Pillow im passenden Build-Venv neu und starte den Build erneut."
        )


_validate_build_environment()

OPTIONS = {
    "argv_emulation": False,
    "no_chdir": True,
    "includes": ["tkinter", "_tkinter", "PIL", "PIL.Image", "PIL.ImageTk"],
    "packages": ["PIL"],
    "arch": BUILD_ARCH,
    "plist": {
        "CFBundleName": "MAAT Notepad",
        "CFBundleDisplayName": "MAAT Notepad",
        "CFBundleIdentifier": "com.christofkrieg.maatnotepad",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
    },
}

if ICON_FILE:
    OPTIONS["iconfile"] = ICON_FILE

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
)
