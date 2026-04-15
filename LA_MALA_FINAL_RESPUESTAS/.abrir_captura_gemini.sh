#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
BASE_DIR="$(pwd)"
export CAPTURA_GEMINI_RUNTIME_DIR="${BASE_DIR}/.runtime"

exec bash "${BASE_DIR}/.captura_gemini_usb/INICIAR.sh" "$@"
