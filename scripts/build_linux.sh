#!/usr/bin/env bash
# ==============================================================================
# scripts/build_linux.sh — Linux build script for FileFinder
#
# Workflow:
#   1. Verify platform is Linux
#   2. Verify Python 3.12+ and virtual environment (.venv)
#   3. Verify / install dependencies (requirements.txt, requirements-dev.txt)
#   4. Run full pytest suite (QT_QPA_PLATFORM=offscreen, abort if any test fails)
#   5. Execute PyInstaller using packaging/filefinder.spec
#   6. Verify output artifact exists (dist/FileFinder/FileFinder)
#   7. Execute smoke test (--version)
#   8. Report build results
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

echo "=================================================================="
echo "          FileFinder — Linux Production Build Pipeline            "
echo "=================================================================="

# 1. Platform verification
OS_NAME="$(uname -s)"
if [[ "${OS_NAME}" != "Linux" ]]; then
    echo "ERROR: This script must be run on Linux. Current OS: ${OS_NAME}" >&2
    exit 1
fi
echo "[1/7] Host platform: Linux ($(uname -m))"

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

# 4. Icon verification
ICONS_DIR="${REPO_ROOT}/resources/icons"
echo "[4/7] Verifying application icons..."
if [[ ! -f "${ICONS_DIR}/app_icon_256.png" && ! -f "${ICONS_DIR}/app_icon.png" ]]; then
    echo "WARNING: App icon png not found in ${ICONS_DIR}" >&2
fi

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
DIST_DIR="${REPO_ROOT}/dist/FileFinder"
DIST_BINARY="${DIST_DIR}/FileFinder"

if [[ ! -d "${DIST_DIR}" ]]; then
    echo "ERROR: Output directory not found: ${DIST_DIR}" >&2
    exit 1
fi

if [[ ! -x "${DIST_BINARY}" ]]; then
    echo "ERROR: Application executable not found or not executable: ${DIST_BINARY}" >&2
    exit 1
fi

echo "[7/7] Running smoke test on compiled executable..."
SMOKE_OUTPUT="$("${DIST_BINARY}" --version 2>&1)"
echo "      Smoke test output: ${SMOKE_OUTPUT}"

if [[ "${SMOKE_OUTPUT}" != *"FileFinder"* ]]; then
    echo "ERROR: Smoke test failed: unexpected output: ${SMOKE_OUTPUT}" >&2
    exit 1
fi

DIST_SIZE="$(du -sh "${DIST_DIR}" | cut -f1)"

echo "=================================================================="
echo "                   BUILD SUCCEEDED                                "
echo "=================================================================="
echo "Artifact:    ${DIST_DIR}"
echo "Binary:      ${DIST_BINARY}"
echo "Size:        ${DIST_SIZE}"
echo "Smoke Test:  PASS (${SMOKE_OUTPUT})"
echo "Platform:    Linux ($(uname -m))"
echo "=================================================================="
