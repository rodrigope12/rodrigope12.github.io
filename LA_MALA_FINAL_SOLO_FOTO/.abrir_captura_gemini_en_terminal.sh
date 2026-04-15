#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
BASE_DIR="$(pwd)"
CMD=(bash "${BASE_DIR}/.abrir_captura_gemini.sh")

if [[ "$#" -gt 0 ]]; then
    CMD+=("$@")
fi

if [[ "${CAPTURA_GEMINI_FORCE_CURRENT_TERMINAL:-0}" == "1" || -t 0 || -t 1 ]]; then
    exec "${CMD[@]}"
fi

build_terminal_script() {
    local quoted_cmd
    printf -v quoted_cmd '%q ' "${CMD[@]}"
    quoted_cmd="${quoted_cmd% }"
    printf '%s' "${quoted_cmd}; status=\$?; echo; if [[ \$status -ne 0 ]]; then echo 'El lanzador termino con error.'; fi; read -r -p 'Presiona Enter para cerrar...' _; exit \$status"
}

TERMINAL_SCRIPT="$(build_terminal_script)"

if command -v gnome-terminal >/dev/null 2>&1; then
    exec gnome-terminal -- bash -lc "${TERMINAL_SCRIPT}"
fi

if command -v kgx >/dev/null 2>&1; then
    exec kgx -- bash -lc "${TERMINAL_SCRIPT}"
fi

if command -v x-terminal-emulator >/dev/null 2>&1; then
    exec x-terminal-emulator -e bash -lc "${TERMINAL_SCRIPT}"
fi

if command -v xterm >/dev/null 2>&1; then
    exec xterm -e bash -lc "${TERMINAL_SCRIPT}"
fi

echo "No se encontro una terminal grafica compatible."
echo "Abre manualmente este archivo en una terminal:"
echo "${BASE_DIR}/.abrir_captura_gemini.sh"
exit 1
