#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
APP_DIR="$(pwd)"
SELF_TEST_CAPTURE=0
SELF_TEST_WATCH=0
CAPTURE_ONCE=0
GNOME_BINDING="${CAPTURA_GEMINI_GNOME_BINDING:-<Primary><Alt>g}"
HOTKEY_LABEL="${CAPTURA_GEMINI_HOTKEY_LABEL:-Ctrl+Alt+G}"
CAPTURE_MODE="${CAPTURA_GEMINI_CAPTURE_MODE:-watch}"
export TMPDIR="${TMPDIR:-/tmp}"
RESULT_FILE="${TMPDIR}/informacion.txt"
PYTHON_BIN="python3"

for arg in "$@"; do
    if [[ "$arg" == "--self-test-capture" ]]; then
        SELF_TEST_CAPTURE=1
    fi
    if [[ "$arg" == "--self-test-watch" ]]; then
        SELF_TEST_WATCH=1
    fi
    if [[ "$arg" == "--capture-once" ]]; then
        CAPTURE_ONCE=1
    fi
done

if [[ "$CAPTURE_MODE" != "watch" && "$CAPTURE_MODE" != "direct" ]]; then
    CAPTURE_MODE="watch"
fi

export CAPTURA_GEMINI_GNOME_BINDING="$GNOME_BINDING"
export CAPTURA_GEMINI_HOTKEY_LABEL="$HOTKEY_LABEL"
export CAPTURA_GEMINI_CAPTURE_MODE="$CAPTURE_MODE"

show_note() {
    local message="$1"
    printf '%s\n' "$message" > "$RESULT_FILE"
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$RESULT_FILE" >/dev/null 2>&1 || true
    fi
}

save_api_key_env() {
    local model_value="${GEMINI_MODEL:-gemini-3-pro-preview}"
    printf 'GEMINI_API_KEY=%s\n' "$GEMINI_API_KEY" > .env
    printf 'GEMINI_MODEL=%s\n' "$model_value" >> .env
}

validate_api_key() {
    local candidate="$1"
    GEMINI_API_KEY_TO_VALIDATE="$candidate" "$PYTHON_BIN" - <<'PY'
import json
import os
from urllib import error as urllib_error
from urllib import request as urllib_request

key = os.environ.get("GEMINI_API_KEY_TO_VALIDATE", "").strip()
if not key or key == "__SET_ME__":
    raise SystemExit(10)

request = urllib_request.Request(
    "https://generativelanguage.googleapis.com/v1beta/models",
    headers={"x-goog-api-key": key},
    method="GET",
)

try:
    with urllib_request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if isinstance(payload, dict) and "models" in payload:
        raise SystemExit(0)
    raise SystemExit(20)
except urllib_error.HTTPError as exc:
    detail = exc.read().decode("utf-8", errors="replace").lower()
    hints = (
        "api key",
        "api_key",
        "credential",
        "credentials",
        "unregistered caller",
        "unregistered callers",
        "authentication",
        "auth",
    )
    if exc.code in {400, 401, 403} and any(hint in detail for hint in hints):
        raise SystemExit(10)
    raise SystemExit(20)
except urllib_error.URLError:
    raise SystemExit(20)
PY
}

prompt_for_valid_api_key() {
    while true; do
        printf "Pega tu GEMINI_API_KEY: "
        read -r GEMINI_API_KEY
        GEMINI_API_KEY="${GEMINI_API_KEY//$'
'/}"
        export GEMINI_API_KEY

        if validate_api_key "$GEMINI_API_KEY"; then
            save_api_key_env
            return 0
        fi

        local status=$?
        if [[ "$status" -eq 10 ]]; then
            echo "La clave no fue aceptada por Gemini. Intenta otra vez."
            continue
        fi

        echo "No se pudo validar la clave ahora mismo. Revisa internet o intenta otra vez."
        echo "Si quieres salir, presiona Ctrl+C."
    done
}

ensure_valid_api_key_for_launch() {
    if [[ -z "${GEMINI_API_KEY:-}" || "${GEMINI_API_KEY:-}" == "__SET_ME__" ]]; then
        if [[ "$CAPTURE_ONCE" -eq 1 ]]; then
            show_note "Falta GEMINI_API_KEY.

Abre primero el lanzador principal para guardar tu clave y registrar el atajo global ${HOTKEY_LABEL}."
            return 1
        fi
        prompt_for_valid_api_key
        return 0
    fi

    if validate_api_key "$GEMINI_API_KEY"; then
        return 0
    fi

    local status=$?
    if [[ "$status" -eq 10 ]]; then
        if [[ "$CAPTURE_ONCE" -eq 1 ]]; then
            show_note "La GEMINI_API_KEY guardada no fue aceptada por Gemini.

Abre el lanzador principal, pega la clave correcta y se guardara de nuevo."
            return 1
        fi
        echo "La GEMINI_API_KEY guardada no fue aceptada por Gemini."
        prompt_for_valid_api_key
        return 0
    fi

    echo "No se pudo validar la GEMINI_API_KEY guardada ahora mismo. Se intentara usar tal como esta."
    return 0
}

append_unique() {


    local value="$1"
    local item
    for item in "${AUTO_INSTALL_PACKAGES[@]:-}"; do
        if [[ "$item" == "$value" ]]; then
            return 0
        fi
    done
    AUTO_INSTALL_PACKAGES+=("$value")
}

is_gnome_wayland() {
    [[ "${XDG_CURRENT_DESKTOP:-}" == *GNOME* && "${XDG_SESSION_TYPE:-}" == "wayland" ]]
}

has_capture_backend() {
    command -v gnome-screenshot >/dev/null 2>&1 \
        || command -v grim >/dev/null 2>&1 \
        || command -v scrot >/dev/null 2>&1 \
        || command -v maim >/dev/null 2>&1 \
        || command -v import >/dev/null 2>&1
}

needs_direct_capture_backend() {
    [[ "$SELF_TEST_CAPTURE" -eq 1 || "$CAPTURE_MODE" == "direct" ]]
}

report_missing_dependencies() {
    local pkg_list="$1"
    local message="Faltan herramientas para la captura directa:

${pkg_list}

Puedes seguir usando la app sin permisos de administrador:
1. Abre el lanzador principal.
2. Toma la captura con Fn+Impr o ImprPant.
3. Guarda la imagen y la app la detecta sola.

Si tambien quieres captura directa desde la app, un administrador debe ejecutar:
sudo apt-get update
sudo apt-get install -y --no-install-recommends ${pkg_list}"

    if [[ "$CAPTURE_ONCE" -eq 1 || "$SELF_TEST_CAPTURE" -eq 1 ]]; then
        show_note "$message"
    fi

    echo "$message"
}

install_with_apt() {
    local pkg_list="$1"
    local install_cmd="apt-get update && apt-get install -y --no-install-recommends ${pkg_list}"

    if [[ "${CAPTURA_GEMINI_ALLOW_SYSTEM_INSTALL:-0}" != "1" ]]; then
        return 1
    fi

    if ! command -v apt-get >/dev/null 2>&1; then
        return 1
    fi

    echo "Instalando herramientas del sistema: ${pkg_list}"
    echo "Puede pedir tu contrasena de administrador."

    if [[ "$(id -u)" -eq 0 ]]; then
        /bin/bash -lc "$install_cmd"
        return $?
    fi

    if command -v pkexec >/dev/null 2>&1; then
        pkexec /bin/bash -lc "$install_cmd"
        return $?
    fi

    if command -v sudo >/dev/null 2>&1; then
        sudo /bin/bash -lc "$install_cmd"
        return $?
    fi

    return 1
}

ensure_system_dependencies() {
    AUTO_INSTALL_PACKAGES=()

    if ! needs_direct_capture_backend; then
        return 0
    fi

    if is_gnome_wayland; then
        if ! command -v gnome-screenshot >/dev/null 2>&1 \
            && ! command -v grim >/dev/null 2>&1 \
            && ! command -v scrot >/dev/null 2>&1; then
            append_unique "gnome-screenshot"
        fi
    elif ! has_capture_backend; then
        append_unique "gnome-screenshot"
    fi

    if [[ "${#AUTO_INSTALL_PACKAGES[@]}" -eq 0 ]]; then
        return 0
    fi

    local pkg_list
    pkg_list="${AUTO_INSTALL_PACKAGES[*]}"

    if [[ "$CAPTURE_ONCE" -eq 1 || "$SELF_TEST_CAPTURE" -eq 1 ]]; then
        report_missing_dependencies "$pkg_list"
        return 1
    fi

    if ! install_with_apt "$pkg_list"; then
        local fail_message="No se pudieron instalar automaticamente estas herramientas:

${pkg_list}

Puedes seguir usando el modo sin admin:
- abre la app
- toma la captura con Fn+Impr
- guarda la imagen y la app la detecta sola

Si despues quieres captura directa, en Debian o Ubuntu ejecuta:
sudo apt-get update
sudo apt-get install -y --no-install-recommends ${pkg_list}

Luego vuelve a abrir este lanzador."
        show_note "$fail_message"
        echo "$fail_message"
        return 1
    fi

    return 0
}

if ! command -v python3 >/dev/null 2>&1; then
    if [[ "$CAPTURE_ONCE" -eq 1 || "$SELF_TEST_CAPTURE" -eq 1 || "$SELF_TEST_WATCH" -eq 1 ]]; then
        show_note "No se encontro python3.

Instala Python 3 en esta computadora para usar Captura Gemini."
    fi
    echo "No se encontro python3."
    echo "En Debian instala Python 3 antes de continuar."
    exit 1
fi

if [[ "$SELF_TEST_CAPTURE" -eq 0 && "$SELF_TEST_WATCH" -eq 0 ]]; then
    if [[ -z "${GEMINI_API_KEY:-}" && -f .env ]]; then
        set -a
        source .env
        set +a
    fi

    if [[ -z "${GEMINI_API_KEY:-}" && -f gemini_api_key.txt ]]; then
        GEMINI_API_KEY="$(head -n 1 gemini_api_key.txt)"
        export GEMINI_API_KEY
    fi

    if ! ensure_valid_api_key_for_launch; then
        exit 1
    fi
fi

if ! ensure_system_dependencies; then
    exit 1
fi

if [[ "$SELF_TEST_CAPTURE" -eq 0 && "$SELF_TEST_WATCH" -eq 0 && -z "${GEMINI_API_KEY:-}" ]]; then
    if [[ "$CAPTURE_ONCE" -eq 1 ]]; then
        show_note "Falta GEMINI_API_KEY.

Abre primero el lanzador principal para guardar tu clave y registrar el atajo global ${HOTKEY_LABEL}."
    fi
    echo "Falta GEMINI_API_KEY."
    exit 1
fi

if [[ "$CAPTURE_ONCE" -eq 0 && "$SELF_TEST_WATCH" -eq 0 && "${XDG_CURRENT_DESKTOP:-}" == *GNOME* ]] && command -v gsettings >/dev/null 2>&1; then
    KEY_PATH="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/captura-gemini-usb/"
    BASE_SCHEMA="org.gnome.settings-daemon.plugins.media-keys"
    KEY_SCHEMA="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:${KEY_PATH}"
    COMMAND="$(python3 - "$APP_DIR" <<'PY'
import shlex
import sys

app_dir = sys.argv[1]
inner = f"cd {shlex.quote(app_dir)} && bash ./run.sh --capture-once"
print(f"bash -lc {shlex.quote(inner)}")
PY
)"

    CURRENT_LIST="$(gsettings get "${BASE_SCHEMA}" custom-keybindings 2>/dev/null || printf '@as []')"
    UPDATED_LIST="$(python3 - "$CURRENT_LIST" "$KEY_PATH" <<'PY'
import ast
import sys

raw = sys.argv[1].strip()
if raw.startswith("@as "):
    raw = raw[4:]
items = ast.literal_eval(raw)
path = sys.argv[2]
if path not in items:
    items.append(path)
print(str(items))
PY
)"

    gsettings set "${BASE_SCHEMA}" custom-keybindings "${UPDATED_LIST}" >/dev/null 2>&1 || true
    gsettings set "${KEY_SCHEMA}" name "Captura Gemini USB" >/dev/null 2>&1 || true
    gsettings set "${KEY_SCHEMA}" command "${COMMAND}" >/dev/null 2>&1 || true
    gsettings set "${KEY_SCHEMA}" binding "${GNOME_BINDING}" >/dev/null 2>&1 || true
fi

exec "$PYTHON_BIN" "$APP_DIR/spy_app.py" "$@"
