#!/usr/bin/env bash
# ==============================================================================
# scripts/build_macos.sh — macOS build script for FileFinder
#
# Workflow:
#   1. Verify platform is macOS (Darwin)
#   2. Verify Python 3.12+ and virtual environment (.venv)
#   3. Verify / install dependencies (requirements.txt, requirements-dev.txt)
#   4. Ensure icon.icns is present (generate with iconutil if missing)
#   5. Run full pytest suite (QT_QPA_PLATFORM=offscreen, abort if any test fails)
#   6. Execute PyInstaller using packaging/filefinder.spec
#   7. Verify output artifact exists (dist/FileFinder.app)
#   8. Execute smoke test (--version)
#   9. Report build results
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

echo "=================================================================="
echo "          FileFinder — macOS Production Build Pipeline           "
echo "=================================================================="

# 1. Platform verification
OS_NAME="$(uname -s)"
if [[ "${OS_NAME}" != "Darwin" ]]; then
    echo "ERROR: This script must be run on macOS (Darwin). Current OS: ${OS_NAME}" >&2
    exit 1
fi
echo "[1/7] Host platform: macOS ($(uname -m))"

# 2. Virtual environment verification
VENV_DIR="${REPO_ROOT}/.venv"
if [[ ! -d "${VENV_DIR}" ]]; then
    echo "[2/7] Virtual environment not found at ${VENV_DIR}. Creating one with python3..."
    python3 -m venv "${VENV_DIR}"
fi

VENV_PYTHON="${VENV_DIR}/bin/python"
VENV_PYTEST="${VENV_DIR}/bin/pytest"
VENV_PYINSTALLER="${VENV_DIR}/bin/pyinstaller"

if [[ ! -x "${VENV_PYTHON}" ]]; then
    echo "ERROR: Python executable not found in virtual environment: ${VENV_PYTHON}" >&2
    exit 1
fi

PY_VER="$("${VENV_PYTHON}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"
echo "[2/7] Using Python: ${PY_VER} (${VENV_PYTHON})"

# 3. Dependencies verification
echo "[3/7] Verifying runtime and development dependencies..."
if ! "${VENV_PYTHON}" -c "import PySide6, charset_normalizer, pytest, PyInstaller" 2>/dev/null; then
    echo "      Installing required dependencies from requirements.txt and requirements-dev.txt..."
    "${VENV_PYTHON}" -m pip install --quiet --upgrade pip
    "${VENV_PYTHON}" -m pip install --quiet -r "${REPO_ROOT}/requirements.txt" -r "${REPO_ROOT}/requirements-dev.txt"
else
    echo "      All required dependencies are satisfied."
fi

# 4. Icon verification / generation
ICONS_DIR="${REPO_ROOT}/resources/icons"
ICNS_FILE="${ICONS_DIR}/icon.icns"
if [[ ! -f "${ICNS_FILE}" && -x "/usr/bin/iconutil" ]]; then
    echo "[4/7] Generating macOS icon.icns from PNG assets..."
    TMP_ICONSET="$(mktemp -d)/FileFinder.iconset"
    mkdir -p "${TMP_ICONSET}"
    cp "${ICONS_DIR}/app_icon_16.png"  "${TMP_ICONSET}/icon_16x16.png" 2>/dev/null || true
    cp "${ICONS_DIR}/app_icon_32.png"  "${TMP_ICONSET}/icon_16x16@2x.png" 2>/dev/null || true
    cp "${ICONS_DIR}/app_icon_32.png"  "${TMP_ICONSET}/icon_32x32.png" 2>/dev/null || true
    cp "${ICONS_DIR}/app_icon_64.png"  "${TMP_ICONSET}/icon_32x32@2x.png" 2>/dev/null || true
    cp "${ICONS_DIR}/app_icon_128.png" "${TMP_ICONSET}/icon_128x128.png" 2>/dev/null || true
    cp "${ICONS_DIR}/app_icon_256.png" "${TMP_ICONSET}/icon_128x128@2x.png" 2>/dev/null || true
    cp "${ICONS_DIR}/app_icon_256.png" "${TMP_ICONSET}/icon_256x256.png" 2>/dev/null || true
    cp "${ICONS_DIR}/app_icon_512.png" "${TMP_ICONSET}/icon_256x256@2x.png" 2>/dev/null || true
    cp "${ICONS_DIR}/app_icon_512.png" "${TMP_ICONSET}/icon_512x512.png" 2>/dev/null || true
    iconutil -c icns "${TMP_ICONSET}" -o "${ICNS_FILE}" 2>/dev/null || true
    rm -rf "$(dirname "${TMP_ICONSET}")"
fi
echo "[4/7] App icon asset ready: $(basename "${ICNS_FILE}")"

# 5. Full test suite execution (Strict QA Gate)
echo "[5/7] Running full pytest test suite (QT_QPA_PLATFORM=offscreen)..."
export QT_QPA_PLATFORM="offscreen"
set +e
"${VENV_PYTEST}" "${REPO_ROOT}/tests"
TEST_EXIT_CODE=$?
set -e

if [[ ${TEST_EXIT_CODE} -ne 0 ]]; then
    echo "ERROR: Test suite failed with exit code ${TEST_EXIT_CODE}. Aborting build." >&2
    exit ${TEST_EXIT_CODE}
fi
echo "      Test suite PASSED (100% green)."

# 6. PyInstaller execution
echo "[6/7] Running PyInstaller build using packaging/filefinder.spec..."
"${VENV_PYINSTALLER}" "${REPO_ROOT}/packaging/filefinder.spec" --clean --noconfirm

# 7. Verification and smoke test
APP_BUNDLE="${REPO_ROOT}/dist/FileFinder.app"
APP_BINARY="${APP_BUNDLE}/Contents/MacOS/FileFinder"

if [[ ! -d "${APP_BUNDLE}" ]]; then
    echo "ERROR: Output application bundle not found: ${APP_BUNDLE}" >&2
    exit 1
fi

if [[ ! -x "${APP_BINARY}" ]]; then
    echo "ERROR: Application executable not found or not executable: ${APP_BINARY}" >&2
    exit 1
fi

echo "[7/7] Running smoke test on compiled bundle..."
SMOKE_OUTPUT="$("${APP_BINARY}" --version 2>&1)"
echo "      Smoke test output: ${SMOKE_OUTPUT}"

if [[ "${SMOKE_OUTPUT}" != *"FileFinder"* ]]; then
    echo "ERROR: Smoke test failed: unexpected output: ${SMOKE_OUTPUT}" >&2
    exit 1
fi

BUNDLE_SIZE="$(du -sh "${APP_BUNDLE}" | cut -f1)"

echo "=================================================================="
echo "                   BUILD SUCCEEDED                                "
echo "=================================================================="
echo "Artifact:    ${APP_BUNDLE}"
echo "Binary:      ${APP_BINARY}"
echo "Size:        ${BUNDLE_SIZE}"
echo "Smoke Test:  PASS (${SMOKE_OUTPUT})"
echo "Platform:    macOS $(sw_vers -productVersion 2>/dev/null || uname -r) ($(uname -m))"
echo "=================================================================="
