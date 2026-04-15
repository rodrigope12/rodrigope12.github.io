#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
APP_DIR="$(pwd)"
TARGET_DIR="${HOME}/.local/share/captura_gemini_usb"
DESKTOP_FILE="${HOME}/.local/share/applications/captura-gemini-usb.desktop"

mkdir -p "${HOME}/.local/share"
mkdir -p "${HOME}/.local/share/applications"
rm -rf "${TARGET_DIR}"
mkdir -p "${TARGET_DIR}"

cp -a "${APP_DIR}/." "${TARGET_DIR}/"
rm -rf "${TARGET_DIR}/__pycache__" "${TARGET_DIR}/tests"

cat > "${DESKTOP_FILE}" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Captura Gemini USB
Comment=Captura pantalla, envia a Gemini y abre la respuesta
Exec=bash -lc "cd \"${TARGET_DIR}\" && bash ./run.sh"
Icon=accessories-text-editor
Terminal=true
Categories=Utility;
StartupNotify=true
EOF

chmod +x "${TARGET_DIR}/run.sh" "${TARGET_DIR}/install_local.sh" "${TARGET_DIR}/INICIAR.sh" "${TARGET_DIR}/INSTALAR.sh"

if command -v gio >/dev/null 2>&1; then
    gio set "${DESKTOP_FILE}" "metadata::trusted" yes >/dev/null 2>&1 || true
fi

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${HOME}/.local/share/applications" >/dev/null 2>&1 || true
fi

echo "Instalacion local completada."
echo "Lanzador creado en: ${DESKTOP_FILE}"
echo "Aplicacion copiada en: ${TARGET_DIR}"
echo "Abriendo la app instalada..."

exec bash "${TARGET_DIR}/run.sh"
