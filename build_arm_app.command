#!/bin/zsh
set -euo pipefail

cd -- "$(dirname "$0")"

VENV_DIR=".build_venv_arm64"
HAS_ARM64_HARDWARE="$("/usr/sbin/sysctl" -in hw.optional.arm64 2>/dev/null || echo 0)"
ALLOW_PYTHON_313="${MAAT_ALLOW_PYTHON_3_13:-}"

is_forbidden_python() {
  local candidate="$1"
  [[ "$candidate" == /usr/bin/* ]] && return 0
  [[ "$candidate" == /System/* ]] && return 0
  [[ "$candidate" == /Library/Developer/CommandLineTools/usr/bin/* ]] && return 0
  return 1
}

python_mm() {
  local candidate="$1"
  "$candidate" - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
}

resolve_python_bin() {
  local -a candidates=()
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    candidates+=("$PYTHON_BIN")
  fi
  candidates+=(
    /Library/Frameworks/Python.framework/Versions/3.12/bin/python3
    /Library/Frameworks/Python.framework/Versions/3.11/bin/python3
    /Library/Frameworks/Python.framework/Versions/3.10/bin/python3
    /Library/Frameworks/Python.framework/Versions/3.13/bin/python3
    /opt/homebrew/bin/python3
    /usr/local/bin/python3
  )

  local candidate resolved version_mm
  for candidate in "${candidates[@]}"; do
    [[ -n "$candidate" ]] || continue
    if [[ ! -x "$candidate" ]]; then
      continue
    fi
    resolved="$(python3 - "$candidate" <<'PY'
import os, sys
print(os.path.realpath(sys.argv[1]))
PY
    )"
    if is_forbidden_python "$resolved"; then
      continue
    fi
    version_mm="$(python_mm "$resolved" 2>/dev/null || echo '')"
    if [[ "$version_mm" == "3.13" && -z "$ALLOW_PYTHON_313" ]]; then
      continue
    fi
    echo "$resolved"
    return 0
  done

  echo ""
  return 1
}

if [[ "$HAS_ARM64_HARDWARE" != "1" ]]; then
  echo "ARM-Build ist nur auf Apple-Silicon-Macs verfuegbar."
  echo "Zum Schliessen Enter druecken."
  read -r _
  exit 1
fi

PYTHON_BIN="$(resolve_python_bin)"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "Kein geeigneter Build-Python gefunden."
  echo "Bitte installiere bevorzugt Python 3.12, 3.11 oder 3.10 (Python.org/Homebrew)."
  echo "Python 3.13 wird fuer py2app hier standardmaessig vermieden."
  echo "Wenn du 3.13 trotzdem testen willst: MAAT_ALLOW_PYTHON_3_13=1 ./build_arm_app.command"
  echo "Zum Schliessen Enter druecken."
  read -r _
  exit 1
fi

ARCH_PREFIX=(arch -arm64)

echo "MAAT Notepad ARM-Build"
echo "Arbeitsordner: $PWD"
echo "Python: $PYTHON_BIN"
echo "Empfehlung: py2app-Builds mit Python 3.12/3.11 sind derzeit am stabilsten."
echo

"${ARCH_PREFIX[@]}" "$PYTHON_BIN" -m venv "$VENV_DIR"
VENV_PY="$PWD/$VENV_DIR/bin/python"

"${ARCH_PREFIX[@]}" "$VENV_PY" -m pip install --upgrade pip setuptools wheel
"${ARCH_PREFIX[@]}" "$VENV_PY" -m pip install --upgrade py2app pillow

export MAAT_PY2APP_ARCH=arm64

echo
echo "Baue ARM-App..."
"${ARCH_PREFIX[@]}" "$VENV_PY" setup.py py2app

echo
echo "Fertig: dist/MAAT Notepad.app"
echo "Zum Schliessen Enter druecken."
read -r _
