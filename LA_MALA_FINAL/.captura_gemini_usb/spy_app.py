import argparse
import base64
import json
import mimetypes
import os
import platform
import re
import select
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request

try:
    from PIL import ImageGrab
    PIL_IMPORT_ERROR = None
except Exception as exc:
    ImageGrab = None
    PIL_IMPORT_ERROR = exc

try:
    from pynput import keyboard
    PYNPUT_IMPORT_ERROR = None
except Exception as exc:
    keyboard = None
    PYNPUT_IMPORT_ERROR = exc

MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-3-pro-preview").strip() or "gemini-3-pro-preview"
RESULT_FILE = Path(tempfile.gettempdir()) / "informacion.txt"
LOCK_FILE = Path(tempfile.gettempdir()) / "captura_gemini_usb.lock"
GLOBAL_HOTKEY_DISPLAY = os.environ.get("CAPTURA_GEMINI_HOTKEY_LABEL", "Ctrl+Alt+G")
TERMINAL_HOTKEY_DISPLAY = "F8"
CAPTURE_MODE = os.environ.get("CAPTURA_GEMINI_CAPTURE_MODE", "watch").strip().lower() or "watch"
if CAPTURE_MODE not in {"watch", "direct"}:
    CAPTURE_MODE = "watch"
DELETE_AFTER_SEND = os.environ.get("CAPTURA_GEMINI_DELETE_AFTER_SEND", "1").strip() != "0"
WATCH_POLL_INTERVAL = 0.5
WATCH_FILE_READY_TIMEOUT = 10.0
WATCH_STABLE_INTERVAL = 0.75
SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

_processing_lock = threading.Lock()
F8_SEQUENCES = {"\x1b[19~"}
_last_f8_time = 0.0

try:
    import fcntl
except Exception:
    fcntl = None


def api_key() -> str:
    value = os.environ.get("GEMINI_API_KEY", "").strip()
    if not value:
        raise RuntimeError(
            "Falta la variable GEMINI_API_KEY. "
            "Exportala antes de iniciar la app."
        )
    return value


def configure_client() -> None:
    api_key()


def screenshot_watch_directories() -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        expanded = path.expanduser()
        key = str(expanded)
        if key in seen:
            return
        seen.add(key)
        candidates.append(expanded)

    raw_env = os.environ.get("CAPTURA_GEMINI_WATCH_DIR", "").strip()
    if raw_env:
        for raw_item in raw_env.split(os.pathsep):
            item = raw_item.strip()
            if item:
                add(Path(item))

    home = Path.home()
    for relative in (
        "Capturas de pantalla",
        "Pictures/Screenshots",
        "Imágenes/Capturas de pantalla",
        "Imagenes/Capturas de pantalla",
        "Pictures",
        "Imágenes",
        "Imagenes",
    ):
        add(home / relative)

    return candidates


def watch_directories_text() -> str:
    directories = screenshot_watch_directories()
    if not directories:
        return "  (sin carpetas configuradas)"
    return "\n".join(f"  - {path}" for path in directories)


def open_result_file() -> None:
    if not RESULT_FILE.exists():
        print(f"No existe aun el archivo de salida: {RESULT_FILE}")
        return

    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.Popen(["open", str(RESULT_FILE)])
        elif system == "Windows":
            os.startfile(str(RESULT_FILE))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(RESULT_FILE)])
    except Exception as exc:
        print(f"No se pudo abrir el editor automaticamente: {exc}")
        print(f"Abre manualmente: {RESULT_FILE}")


def write_result(text: str) -> None:
    RESULT_FILE.write_text(text.strip() + "\n", encoding="utf-8")
    open_result_file()


def runtime_diagnostics_text() -> str:
    lines = [
        "Diagnostico:",
        f"  sistema: {platform.system()}",
        f"  modo: {CAPTURE_MODE}",
        f"  sesion: {os.environ.get('XDG_SESSION_TYPE', 'desconocida')}",
        f"  desktop: {os.environ.get('XDG_CURRENT_DESKTOP', 'desconocido')}",
        f"  DISPLAY: {os.environ.get('DISPLAY', '(vacio)')}",
        f"  WAYLAND_DISPLAY: {os.environ.get('WAYLAND_DISPLAY', '(vacio)')}",
        f"  gdbus: {'si' if shutil.which('gdbus') else 'no'}",
        f"  gnome-screenshot: {'si' if shutil.which('gnome-screenshot') else 'no'}",
        f"  grim: {'si' if shutil.which('grim') else 'no'}",
        f"  scrot: {'si' if shutil.which('scrot') else 'no'}",
        f"  maim: {'si' if shutil.which('maim') else 'no'}",
        f"  import: {'si' if shutil.which('import') else 'no'}",
        f"  Pillow ImageGrab: {'si' if ImageGrab is not None else 'no'}",
        "  carpetas vigiladas:",
    ]
    lines.extend(f"    - {path}" for path in screenshot_watch_directories())
    return "\n".join(lines)


def write_error_result(exc: Exception) -> None:
    message = f"Error: {exc}\n\n{runtime_diagnostics_text()}"
    try:
        write_result(message)
    except Exception as write_exc:
        print(f"No se pudo escribir el resultado de error: {write_exc}")


def delete_image_file(image_path: Path) -> None:
    try:
        image_path.unlink(missing_ok=True)
        print(f"Archivo eliminado: {image_path}")
    except Exception as exc:
        print(f"No se pudo borrar la imagen enviada: {exc}")


def capture_with_system_tool(target: Path) -> Path | None:
    commands: list[list[str]] = []
    if platform.system() == "Linux":
        commands = [
            ["gnome-screenshot", "-f", str(target)],
            ["grim", str(target)],
            ["scrot", str(target)],
            ["maim", str(target)],
            ["import", "-window", "root", str(target)],
        ]
    elif platform.system() == "Darwin":
        commands = [["screencapture", "-x", str(target)]]

    for command in commands:
        if not shutil.which(command[0]):
            continue
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            if stderr:
                print(f"{command[0]} fallo: {stderr}")
            continue
        if target.exists() and target.stat().st_size > 0:
            return target
    return None


def capture_with_wayland_portal(target: Path) -> Path | None:
    if os.environ.get("XDG_SESSION_TYPE") != "wayland":
        return None
    print("Portal Wayland no implementado sin dbus de Python.")
    return None


def capture_with_gnome_shell(target: Path) -> Path | None:
    if os.environ.get("XDG_SESSION_TYPE") != "wayland":
        return None
    if "GNOME" not in os.environ.get("XDG_CURRENT_DESKTOP", ""):
        return None

    if not shutil.which("gdbus"):
        print("gdbus no esta disponible.")
        return None

    try:
        result = subprocess.run(
            [
                "gdbus",
                "call",
                "--session",
                "--dest",
                "org.gnome.Shell.Screenshot",
                "--object-path",
                "/org/gnome/Shell/Screenshot",
                "--method",
                "org.gnome.Shell.Screenshot.Screenshot",
                "false",
                "false",
                str(target),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        print(f"GNOME Shell Screenshot fallo: {detail}")
        return None
    except Exception as exc:
        print(f"GNOME Shell Screenshot fallo: {exc}")
        return None

    output = result.stdout.strip()
    match = re.search(r"\((true|false),\s*'([^']*)'\)", output)
    if not match:
        print(f"GNOME Shell Screenshot respuesta inesperada: {output}")
        return None

    success = match.group(1) == "true"
    filename = match.group(2)
    output_path = Path(filename) if filename else target
    if not success:
        print(f"GNOME Shell Screenshot devolvio false: {output}")
        return None
    if not output_path.exists():
        print(f"GNOME Shell Screenshot no produjo archivo: {output_path}")
        return None
    if output_path.stat().st_size <= 0:
        return None
    return output_path


def capture_with_pillow(target: Path) -> Path | None:
    if ImageGrab is None:
        print(f"Pillow ImageGrab no esta disponible: {PIL_IMPORT_ERROR}")
        return None
    try:
        image = ImageGrab.grab()
        image.save(target)
        return target if target.exists() and target.stat().st_size > 0 else None
    except Exception as exc:
        print(f"Pillow ImageGrab fallo: {exc}")
        return None


def capture_backends() -> list[tuple[str, object]]:
    is_gnome_wayland = (
        os.environ.get("XDG_SESSION_TYPE") == "wayland"
        and "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "")
    )
    if is_gnome_wayland:
        return [
            ("gnome-shell", capture_with_gnome_shell),
            ("system-tool", capture_with_system_tool),
            ("wayland-portal", capture_with_wayland_portal),
            ("pillow", capture_with_pillow),
        ]
    return [
        ("system-tool", capture_with_system_tool),
        ("gnome-shell", capture_with_gnome_shell),
        ("wayland-portal", capture_with_wayland_portal),
        ("pillow", capture_with_pillow),
    ]


def capture_to_file() -> tuple[Path, str]:
    temp_path = Path(tempfile.gettempdir()) / f"gemini_capture_{int(time.time())}.png"
    print("Capturando ahora...")

    for backend_name, backend in capture_backends():
        output_path = backend(temp_path)
        if output_path is not None:
            return output_path, backend_name

    raise RuntimeError(
        "No se pudo tomar la captura. "
        "Instala gnome-screenshot, grim o scrot, o usa el modo con Fn+Impr para guardar la imagen."
    )


def existing_watch_snapshot(directories: list[Path]) -> dict[str, float]:
    snapshot: dict[str, float] = {}
    for directory in directories:
        if not directory.is_dir():
            continue
        try:
            children = list(directory.iterdir())
        except OSError:
            continue

        for child in children:
            if not child.is_file() or child.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
                continue
            try:
                snapshot[str(child.resolve())] = child.stat().st_mtime
            except OSError:
                continue
    return snapshot


def wait_for_file_ready(image_path: Path, timeout: float = WATCH_FILE_READY_TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    last_size = -1
    stable_since = 0.0

    while time.monotonic() < deadline:
        try:
            stat = image_path.stat()
        except OSError:
            time.sleep(0.2)
            continue

        if stat.st_size <= 0:
            time.sleep(0.2)
            continue

        if stat.st_size == last_size:
            if time.monotonic() - stable_since >= WATCH_STABLE_INTERVAL:
                return True
        else:
            last_size = stat.st_size
            stable_since = time.monotonic()
        time.sleep(0.2)

    try:
        return image_path.exists() and image_path.stat().st_size > 0
    except OSError:
        return False


def wait_for_next_saved_image(
    *,
    timeout: float | None = None,
    known_files: dict[str, float] | None = None,
    minimum_mtime: float | None = None,
    announce_wait: bool = True,
) -> Path:
    directories = screenshot_watch_directories()
    if known_files is None:
        known_files = existing_watch_snapshot(directories)
    if minimum_mtime is None:
        minimum_mtime = time.time() - 1.0

    if announce_wait:
        print("Esperando la siguiente captura guardada por el sistema...")
        print("Carpetas vigiladas:")
        print(watch_directories_text())
        print("Haz la captura con Fn+Impr o ImprPant y guardala.")

    deadline = None if timeout is None else time.monotonic() + timeout

    while True:
        for directory in directories:
            if not directory.is_dir():
                continue
            try:
                children = list(directory.iterdir())
            except OSError:
                continue

            pending: list[tuple[float, Path]] = []
            for child in children:
                if not child.is_file() or child.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
                    continue
                try:
                    stat = child.stat()
                    key = str(child.resolve())
                except OSError:
                    continue

                if key in known_files:
                    continue
                known_files[key] = stat.st_mtime
                if stat.st_mtime < minimum_mtime:
                    continue
                pending.append((stat.st_mtime, child))

            pending.sort(key=lambda item: item[0])
            for _, child in pending:
                if wait_for_file_ready(child):
                    print(f"Archivo de captura detectado: {child}")
                    return child

        if deadline is not None and time.monotonic() >= deadline:
            raise RuntimeError("No aparecio una captura nueva en el tiempo esperado.")

        time.sleep(WATCH_POLL_INTERVAL)
        directories = screenshot_watch_directories()


def gemini_endpoint() -> str:
    return f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent"


def extract_text_from_gemini_response(payload: dict) -> str:
    texts: list[str] = []
    for candidate in payload.get("candidates", []):
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            text = part.get("text", "").strip()
            if text:
                texts.append(text)

    if texts:
        return "\n\n".join(texts)

    prompt_feedback = payload.get("promptFeedback", {})
    block_reason = prompt_feedback.get("blockReason")
    if block_reason:
        raise RuntimeError(f"Gemini bloqueo la solicitud: {block_reason}")

    raise RuntimeError("Gemini no devolvio texto util.")


def analyze_image(image_path: Path) -> str:
    configure_client()
    image_bytes = image_path.read_bytes()
    mime_type = mimetypes.guess_type(str(image_path))[0] or "image/png"
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": base64.b64encode(image_bytes).decode("ascii"),
                        }
                    },
                ]
            }
        ]
    }
    request = urllib_request.Request(
        gemini_endpoint(),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key(),
        },
        method="POST",
    )

    try:
        with urllib_request.urlopen(request, timeout=90) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Gemini devolvio HTTP {exc.code}: {detail}") from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"No se pudo conectar con Gemini: {exc.reason}") from exc

    return extract_text_from_gemini_response(response_payload)


def process_existing_image(image_path: Path, *, delete_after_send: bool = DELETE_AFTER_SEND) -> None:
    if not _processing_lock.acquire(blocking=False):
        print("Ya hay una captura en proceso. Espera a que termine.")
        return

    lock_handle = None
    try:
        if fcntl is not None:
            lock_handle = LOCK_FILE.open("w", encoding="utf-8")
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("Ya hay una captura global en proceso. Espera a que termine.")
                return

        print(f"Usando imagen guardada: {image_path}")
        print(f"Enviando imagen a Gemini con el modelo {MODEL_NAME}...")
        result = analyze_image(image_path)
        write_result(result)
        print(f"Respuesta guardada en: {RESULT_FILE}")
        if delete_after_send:
            delete_image_file(image_path)
    except Exception as exc:
        print(f"Error: {exc}")
        write_error_result(exc)
    finally:
        if lock_handle is not None:
            try:
                if fcntl is not None:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            lock_handle.close()
        _processing_lock.release()


def process_capture() -> None:
    if not _processing_lock.acquire(blocking=False):
        print("Ya hay una captura en proceso. Espera a que termine.")
        return

    image_path = None
    lock_handle = None
    try:
        if fcntl is not None:
            lock_handle = LOCK_FILE.open("w", encoding="utf-8")
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("Ya hay una captura global en proceso. Espera a que termine.")
                return

        print("Preparando captura directa...")
        image_path, backend_name = capture_to_file()
        print(f"Captura guardada temporalmente en: {image_path}")
        print(f"Backend de captura usado: {backend_name}")
        print(f"Enviando imagen a Gemini con el modelo {MODEL_NAME}...")
        result = analyze_image(image_path)
        write_result(result)
        print(f"Respuesta guardada en: {RESULT_FILE}")
    except Exception as exc:
        print(f"Error: {exc}")
        write_error_result(exc)
    finally:
        if image_path and image_path.exists():
            image_path.unlink(missing_ok=True)
        if lock_handle is not None:
            try:
                if fcntl is not None:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            lock_handle.close()
        _processing_lock.release()


def trigger_capture() -> None:
    threading.Thread(target=process_capture, daemon=True).start()


def watch_saved_images(stop_event: threading.Event) -> None:
    known_files = existing_watch_snapshot(screenshot_watch_directories())
    minimum_mtime = time.time() - 1.0
    announce_wait = True

    while not stop_event.is_set():
        try:
            image_path = wait_for_next_saved_image(
                timeout=1.0,
                known_files=known_files,
                minimum_mtime=minimum_mtime,
                announce_wait=announce_wait,
            )
        except RuntimeError:
            announce_wait = False
            continue

        announce_wait = True
        process_existing_image(image_path, delete_after_send=DELETE_AFTER_SEND)
        if not stop_event.is_set():
            print("")
            print("La app sigue esperando la siguiente captura guardada.")


def _on_global_press(key: object) -> None:
    global _last_f8_time

    if keyboard is None:
        return
    if key != keyboard.Key.f8:
        return

    now = time.monotonic()
    if now - _last_f8_time < 0.5:
        return
    _last_f8_time = now

    print("")
    print("F8 global detectado.")
    trigger_capture()


def start_hotkey_listener() -> object | None:
    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        print("Sesion Wayland detectada.")
        print(f"Atajo global GNOME configurado: {GLOBAL_HOTKEY_DISPLAY}")
        print(f"Tambien puedes usar {TERMINAL_HOTKEY_DISPLAY} con la terminal enfocada.")
        return None

    if keyboard is None:
        print(f"No se pudo cargar pynput: {PYNPUT_IMPORT_ERROR}")
        print(f"El atajo global {TERMINAL_HOTKEY_DISPLAY} no estara disponible en esta sesion.")
        return None

    try:
        listener = keyboard.Listener(on_press=_on_global_press)
        listener.start()
        print(f"Atajo global activo: {TERMINAL_HOTKEY_DISPLAY}")
        return listener
    except Exception as exc:
        print(f"No se pudo activar el atajo global {TERMINAL_HOTKEY_DISPLAY}: {exc}")
        if os.environ.get("WAYLAND_DISPLAY"):
            print("Tu sesion parece usar Wayland. Alli los atajos globales suelen estar bloqueados.")
        print(f"Puedes usar {TERMINAL_HOTKEY_DISPLAY} con la terminal enfocada o el comando 'r'.")
        return None


def _read_escape_sequence() -> str:
    sequence = "\x1b"
    deadline = time.monotonic() + 0.05
    while time.monotonic() < deadline:
        ready, _, _ = select.select([sys.stdin], [], [], 0.01)
        if not ready:
            break
        sequence += sys.stdin.read(1)
        if sequence in F8_SEQUENCES:
            break
    return sequence


def _handle_buffer_command(buffer: str) -> str:
    command = buffer.strip().lower()
    if not command:
        return ""
    if command in {"q", "quit", "salir"}:
        raise EOFError
    if command in {"r", "run", "captura"}:
        trigger_capture()
    elif command in {"w", "watch", "esperar"}:
        print("La app vigila automaticamente estas carpetas:")
        print(watch_directories_text())
    elif command in {"o", "open", "abrir"}:
        open_result_file()
    else:
        print("Comando no reconocido. Usa F8, r, w, o o q.")
    return ""


def command_loop() -> None:
    if not sys.stdin.isatty():
        while True:
            command = input("> ").strip().lower()
            if command in {"q", "quit", "salir"}:
                break
            if command in {"r", "run", "captura"}:
                trigger_capture()
                continue
            if command in {"w", "watch", "esperar"}:
                print("La app vigila automaticamente estas carpetas:")
                print(watch_directories_text())
                continue
            if command in {"o", "open", "abrir"}:
                open_result_file()
                continue
            if command:
                print("Comando no reconocido. Usa F8, r, w, o o q.")
        return

    if platform.system() == "Windows":
        while True:
            command = input("> ").strip().lower()
            if command in {"q", "quit", "salir"}:
                break
            if command in {"r", "run", "captura"}:
                trigger_capture()
                continue
            if command in {"w", "watch", "esperar"}:
                print("La app vigila automaticamente estas carpetas:")
                print(watch_directories_text())
                continue
            if command in {"o", "open", "abrir"}:
                open_result_file()
                continue
            if command:
                print("Comando no reconocido. Usa F8, r, w, o o q.")
        return

    import termios
    import tty

    fd = sys.stdin.fileno()
    original_settings = termios.tcgetattr(fd)
    buffer = ""

    try:
        tty.setcbreak(fd)
        print("> ", end="", flush=True)
        while True:
            ready, _, _ = select.select([sys.stdin], [], [], 0.1)
            if not ready:
                continue

            char = sys.stdin.read(1)
            if char == "\x03":
                raise KeyboardInterrupt
            if char == "\x04":
                raise EOFError
            if char == "\x1b":
                sequence = _read_escape_sequence()
                if sequence in F8_SEQUENCES:
                    print("")
                    print("F8 detectado en la terminal.")
                    trigger_capture()
                    print("> " + buffer, end="", flush=True)
                continue
            if char in {"\r", "\n"}:
                print("")
                buffer = _handle_buffer_command(buffer)
                print("> ", end="", flush=True)
                continue
            if char in {"\x7f", "\b"}:
                if buffer:
                    buffer = buffer[:-1]
                    print("\b \b", end="", flush=True)
                continue

            buffer += char
            print(char, end="", flush=True)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, original_settings)


def print_intro() -> None:
    print("=======================================================")
    print("           Captura Visible + Gemini (Debian)          ")
    print("=======================================================")
    print("La app se ejecuta de forma visible en esta terminal.")
    print("La respuesta se guarda en informacion.txt y se abre")
    print("con el editor de texto del sistema.")
    print("")
    if CAPTURE_MODE == "watch":
        print("Modo recomendado sin admin:")
        print("  1. Deja esta ventana abierta.")
        print("  2. Toma la captura con Fn+Impr o ImprPant.")
        print("  3. Guarda la imagen y la app la detecta sola.")
        print("")
        print("Carpetas vigiladas:")
        print(watch_directories_text())
        print("")
    else:
        print("Modo actual: captura directa desde la app.")
        print("")
    print(f"Atajo global configurado en GNOME: {GLOBAL_HOTKEY_DISPLAY}")
    print(f"Atajo con la terminal enfocada: {TERMINAL_HOTKEY_DISPLAY} (captura directa)")
    print("")
    print("Comandos:")
    print("  r + Enter  -> intentar captura directa ahora")
    print("  w + Enter  -> mostrar carpetas vigiladas")
    print("  o + Enter  -> abrir el ultimo archivo de salida")
    print("  q + Enter  -> salir")
    print("")


def print_capture_diagnostics() -> None:
    print(runtime_diagnostics_text())


def main() -> None:
    try:
        api_key()
    except RuntimeError as exc:
        print(exc)
        return

    print_intro()
    listener = start_hotkey_listener()
    watch_stop_event: threading.Event | None = None
    watch_thread: threading.Thread | None = None

    if CAPTURE_MODE == "watch":
        watch_stop_event = threading.Event()
        watch_thread = threading.Thread(target=watch_saved_images, args=(watch_stop_event,), daemon=True)
        watch_thread.start()

    try:
        command_loop()
    except KeyboardInterrupt:
        print("")
        print("Interrumpido por el usuario.")
    except EOFError:
        print("")
        print("Saliendo...")
    finally:
        if watch_stop_event is not None:
            watch_stop_event.set()
        if listener is not None:
            listener.stop()
        if watch_thread is not None:
            watch_thread.join(timeout=1.0)


def main_self_test_capture() -> int:
    image_path = None
    try:
        image_path, backend_name = capture_to_file()
        print(f"CAPTURE_OK backend={backend_name} path={image_path} size={image_path.stat().st_size}")
        return 0
    except Exception as exc:
        print(f"CAPTURE_ERROR {exc}")
        print_capture_diagnostics()
        return 1


def main_self_test_watch() -> int:
    try:
        image_path = wait_for_next_saved_image(
            timeout=120.0,
            known_files=existing_watch_snapshot(screenshot_watch_directories()),
            minimum_mtime=time.time() - 1.0,
            announce_wait=True,
        )
        print(f"WATCH_OK path={image_path} size={image_path.stat().st_size}")
        return 0
    except Exception as exc:
        print(f"WATCH_ERROR {exc}")
        print_capture_diagnostics()
        return 1


def main_analyze_file(image_path_arg: str) -> None:
    try:
        api_key()
    except RuntimeError as exc:
        print(exc)
        return

    image_path = Path(image_path_arg).expanduser()
    if not image_path.exists() or not image_path.is_file():
        print(f"No existe el archivo indicado: {image_path}")
        return

    process_existing_image(image_path, delete_after_send=DELETE_AFTER_SEND)


def main_capture_once() -> None:
    try:
        api_key()
    except RuntimeError as exc:
        print(exc)
        return

    if CAPTURE_MODE == "watch":
        try:
            image_path = wait_for_next_saved_image(
                known_files=existing_watch_snapshot(screenshot_watch_directories()),
                minimum_mtime=time.time() - 1.0,
                announce_wait=True,
            )
        except Exception as exc:
            print(f"Error: {exc}")
            write_error_result(exc)
            return
        process_existing_image(image_path, delete_after_send=DELETE_AFTER_SEND)
        return

    process_capture()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "--capture-once",
        action="store_true",
        help="Envia una sola captura a Gemini. En modo watch espera el siguiente archivo guardado.",
    )
    parser.add_argument(
        "--self-test-capture",
        action="store_true",
        help="Prueba solo la captura de pantalla y conserva el archivo temporal para inspeccion.",
    )
    parser.add_argument(
        "--self-test-watch",
        action="store_true",
        help="Espera la siguiente imagen guardada en la carpeta de capturas y confirma que fue detectada.",
    )
    parser.add_argument(
        "--analyze-file",
        metavar="RUTA",
        help="Analiza una imagen ya guardada, sin tomar una captura nueva.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args(sys.argv[1:])
    if args.self_test_capture:
        raise SystemExit(main_self_test_capture())
    if args.self_test_watch:
        raise SystemExit(main_self_test_watch())
    if args.analyze_file:
        main_analyze_file(args.analyze_file)
    elif args.capture_once:
        main_capture_once()
    else:
        main()
