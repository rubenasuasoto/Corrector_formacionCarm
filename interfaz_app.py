from __future__ import annotations

import argparse
import csv
import hashlib
import os
import json
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
import webbrowser
import tkinter as tk
from tkinter import filedialog
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    pystray = None
    Image = None
    ImageDraw = None


ROOT = Path(__file__).resolve().parent
APP_CONFIG_PATH = ROOT / ".corrector_app.json"
DEFAULT_PENDIENTES_DIR = Path(r"C:\temp\vscodec\pendientes")
DEFAULT_TEMPORAL_DIR = Path(r"C:\temp\vscodec\temporal")
PENDIENTES_DIR = DEFAULT_PENDIENTES_DIR
TEMPORAL_DIR = DEFAULT_TEMPORAL_DIR
PROMPTS_DIR = TEMPORAL_DIR / "prompts_codex"
COMBINED_JSON = PROMPTS_DIR / "correcciones_codex_combinadas.json"
REVISION_CSV = TEMPORAL_DIR / "revision_pendiente.csv"
AGENTE_LOG = ROOT / "logs_correcciones" / "agente.log"
AUDIT_LOG = ROOT / "respuestas_extraidas" / "auditoria.jsonl"
SUBIDA_PUBLICADA_JSON = ROOT / "respuestas_extraidas" / "subida_carm_publicada.json"
SUBIDA_ASISTIDA_JSON = ROOT / "respuestas_extraidas" / "subida_carm_asistida.json"
ENV_PATH = ROOT / ".env"
CARM_STORAGE_STATE = ROOT / "cache_carm" / "carm_storage_state.json"
ALLOWED_UNITS = {f"ud{i:02d}" for i in range(1, 16)}
ALLOWED_MAX_ENTREGAS = {"0", *{str(i) for i in range(1, 21)}}
ALLOWED_ACTIVITIES = {f"ud{unit:02d}cp{case:02d}" for unit in range(1, 16) for case in range(1, 16)}
ALLOWED_CONTEXT_PATHS = {
    str(ROOT / "tmp_prueba" / "manual_ud01.txt"),
}
UNIT_RE = re.compile(r"^ud\d{2}$")
ACTIVITY_RE = re.compile(r"^ud\d{2}cp\d{2}$")
COURSE_URL_RE = re.compile(r"^https://formacion\.carm\.es/course/view\.php\?id=\d+$")
TRAY_ICON = None
AUTO_CORRECT_AFTER_SCAN = False
AUTO_CORRECT_ARGS = ["--flujo-correccion-carm", "--max-entregas-por-prompt", "6"]
DEFAULT_SCAN_INTERVAL_MINUTES = 60
API_TOKEN = secrets.token_urlsafe(32)
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
PORT_FALLBACK_ATTEMPTS = 30


def load_app_config() -> dict:
    if not APP_CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(APP_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_app_config(config: dict) -> None:
    current = load_app_config()
    current.update(config)
    APP_CONFIG_PATH.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")


def auto_scan_interval_minutes() -> int:
    config = load_app_config()
    try:
        value = int(config.get("auto_scan_interval_minutes", DEFAULT_SCAN_INTERVAL_MINUTES))
    except (TypeError, ValueError):
        value = DEFAULT_SCAN_INTERVAL_MINUTES
    return max(0, min(value, 1440))


def _normalize_dir(path: str | Path, fallback: Path) -> Path:
    raw = str(path or "").strip()
    if not raw:
        return fallback
    return Path(raw).expanduser()


def ensure_work_dirs() -> None:
    for path in (PENDIENTES_DIR, TEMPORAL_DIR, PROMPTS_DIR, ROOT / "cache_carm", ROOT / "logs_correcciones"):
        path.mkdir(parents=True, exist_ok=True)


def configure_work_dirs(pendientes: str | Path | None = None, temporal: str | Path | None = None, persist: bool = False) -> None:
    global PENDIENTES_DIR, TEMPORAL_DIR, PROMPTS_DIR, COMBINED_JSON, REVISION_CSV
    current = load_app_config()
    PENDIENTES_DIR = _normalize_dir(pendientes or current.get("pendientes_dir"), DEFAULT_PENDIENTES_DIR)
    TEMPORAL_DIR = _normalize_dir(temporal or current.get("temporal_dir"), DEFAULT_TEMPORAL_DIR)
    PROMPTS_DIR = TEMPORAL_DIR / "prompts_codex"
    COMBINED_JSON = PROMPTS_DIR / "correcciones_codex_combinadas.json"
    REVISION_CSV = TEMPORAL_DIR / "revision_pendiente.csv"
    ensure_work_dirs()
    if persist:
        save_app_config({"pendientes_dir": str(PENDIENTES_DIR), "temporal_dir": str(TEMPORAL_DIR)})


def save_automation_config(interval_minutes: str | int) -> int:
    try:
        interval = int(interval_minutes)
    except (TypeError, ValueError):
        raise ValueError("El intervalo debe ser un numero de minutos.")
    if interval < 0 or interval > 1440:
        raise ValueError("El intervalo debe estar entre 0 y 1440 minutos. Usa 0 para desactivar.")
    save_app_config({"auto_scan_interval_minutes": interval})
    return interval


def json_options() -> list[dict]:
    paths = [COMBINED_JSON]
    if PROMPTS_DIR.exists():
        paths.extend(sorted(PROMPTS_DIR.glob("*_correccion.json")))
    seen: set[str] = set()
    options: list[dict] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        options.append({"path": key, "label": path.name, "exists": path.exists()})
    return options


def allowed_json_paths() -> set[str]:
    allowed = {item["path"] for item in json_options()}
    allowed.update(
        str(PROMPTS_DIR / name)
        for name in (
            "prompt_ud01cp01_correccion.json",
            "prompt_ud01cp02_correccion.json",
            "prompt_ud02cp03_correccion.json",
        )
    )
    return allowed


configure_work_dirs()


def redact_text(text: object) -> str:
    value = str(text or "")
    value = re.sub(r"[\w.\-+%]+@[\w.\-]+\.[A-Za-z]{2,}", "[email-redactado]", value)
    value = re.sub(r"(sesskey=)[^&\"'>\s]+", r"\1[redactado]", value, flags=re.I)
    value = re.sub(r"(password|contrasena|contraseña|api[_-]?key|token|authorization|cookie)(\s*[=:]\s*)[^&\"'>\s]+", r"\1\2[redactado]", value, flags=re.I)
    return value


def pseudonym(value: object, prefix: str = "persona") -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return f"{prefix}_desconocida"
    digest = hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:10]
    return f"{prefix}_{digest}"


def audit_ui_event(action: str, result: str = "ok", **details: object) -> None:
    safe: dict[str, str] = {}
    for key, value in details.items():
        key_lower = key.lower()
        if key_lower in {"usuario", "alumno", "email", "correo"}:
            safe[f"{key}_ref"] = pseudonym(value)
        elif key_lower in {"contrasena", "password", "token", "cookie", "api_key"}:
            safe[key] = "[redactado]"
        else:
            safe[key] = redact_text(value)
    event = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "origen": "interfaz_app",
        "accion": action,
        "resultado": result,
        "detalles": safe,
    }
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass


def notify(title: str, message: str) -> None:
    text = message[:240]
    if TRAY_ICON is not None:
        try:
            TRAY_ICON.notify(text, title)
            return
        except Exception:
            pass
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-WindowStyle",
                "Hidden",
                "-Command",
                (
                    "[reflection.assembly]::loadwithpartialname('System.Windows.Forms') | Out-Null; "
                    "$n=New-Object System.Windows.Forms.NotifyIcon; "
                    "$n.Icon=[System.Drawing.SystemIcons]::Information; "
                    "$n.Visible=$true; "
                    f"$n.ShowBalloonTip(8000, {json.dumps(title)}, {json.dumps(text)}, 'Info'); "
                    "Start-Sleep -Seconds 9; $n.Dispose()"
                ),
            ],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=12,
        )
    except Exception:
        pass


def read_env_values() -> dict[str, str]:
    valores: dict[str, str] = {}
    if not ENV_PATH.exists():
        return valores
    for line in ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        valores[key.strip()] = value.strip().strip('"').strip("'")
    return valores


def write_env_values(updates: dict[str, str | None]) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines() if ENV_PATH.exists() else []
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            output.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in updates:
            seen.add(key)
            value = updates[key]
            if value is None:
                continue
            output.append(f"{key}={value}")
        else:
            output.append(line)
    for key, value in updates.items():
        if key not in seen and value is not None:
            output.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def carm_credentials_present() -> bool:
    env = read_env_values()
    return bool(env.get("CARM_USUARIO") and env.get("CARM_CONTRASENA"))


def auth_status() -> dict:
    return {
        "configured": carm_credentials_present(),
        "session_saved": CARM_STORAGE_STATE.exists(),
    }


def verify_carm_credentials(usuario: str, contrasena: str) -> tuple[bool, str]:
    env = os.environ.copy()
    env["CARM_USUARIO"] = usuario
    env["CARM_CONTRASENA"] = contrasena
    env["CARM_HEADLESS"] = "1"
    proc = subprocess.run(
        [sys.executable, "corrector_agente.py", "--comprobar-login-carm"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    ok = proc.returncode == 0 and " - ERROR - " not in proc.stdout
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    return ok, lines[-1] if lines else ("Credenciales verificadas." if ok else "No se pudo verificar CARM.")


def save_carm_credentials(usuario: str, contrasena: str) -> tuple[bool, str]:
    usuario = usuario.strip()
    contrasena = contrasena.strip()
    if not usuario or not contrasena:
        return False, "Usuario y contrasena son obligatorios."
    ok, message = verify_carm_credentials(usuario, contrasena)
    if not ok:
        if CARM_STORAGE_STATE.exists():
            CARM_STORAGE_STATE.unlink()
        return False, message
    write_env_values(
        {
            "CARM_USUARIO": usuario,
            "CARM_CONTRASENA": contrasena,
            "CARM_RECORDAR_CUENTA": "1",
        }
    )
    return True, "Credenciales CARM guardadas y verificadas."


def logout_carm() -> None:
    write_env_values({"CARM_USUARIO": "", "CARM_CONTRASENA": ""})
    if CARM_STORAGE_STATE.exists():
        CARM_STORAGE_STATE.unlink()


def current_course_url() -> str:
    return read_env_values().get("CARM_COURSE_URL") or "https://formacion.carm.es/course/view.php?id=1592"


def course_id_from_url(url: str) -> str:
    match = re.search(r"[?&]id=(\d+)", url)
    return match.group(1) if match else ""


def course_url_from_id(course_id: str) -> str:
    course_id = str(course_id or "").strip()
    if not course_id.isdigit():
        raise ValueError("El ID del curso debe ser numerico.")
    return f"https://formacion.carm.es/course/view.php?id={course_id}"


def save_course_url(url_or_id: str) -> str:
    value = str(url_or_id or "").strip()
    if value.isdigit():
        value = course_url_from_id(value)
    if not COURSE_URL_RE.fullmatch(value):
        raise ValueError("Introduce una URL de curso CARM valida o solo el ID numerico del curso.")
    write_env_values({"CARM_COURSE_URL": value})
    return value


def choose_directory(initial_dir: str | None = None) -> str:
    initial = Path(initial_dir or "").expanduser() if initial_dir else TEMPORAL_DIR
    if not initial.exists():
        initial = initial.parent if initial.parent.exists() else ROOT
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askdirectory(
            title="Elige carpeta de trabajo",
            initialdir=str(initial),
            mustexist=False,
        )
        return selected or ""
    finally:
        root.destroy()


def revisar_publicacion_segura() -> None:
    if not REVISION_CSV.exists():
        raise ValueError("No existe revision_pendiente.csv. Prepara e importa correcciones antes de publicar.")

    with REVISION_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))

    if not rows:
        raise ValueError("revision_pendiente.csv no contiene filas revisables.")

    estados_bloqueantes = {
        "revision_manual_necesaria",
        "error",
        "error_descarga",
        "sin_archivo_detectado",
        "sin_entrega",
    }
    bloqueadas = [
        row
        for row in rows
        if (row.get("estado") or "").strip().lower() in estados_bloqueantes
    ]
    if bloqueadas:
        muestra = ", ".join(
            f"{row.get('alumno', 'alumno')}:{row.get('actividad', '')}:{row.get('estado', '')}"
            for row in bloqueadas[:5]
        )
        raise ValueError(
            f"Publicacion bloqueada: hay {len(bloqueadas)} fila(s) con revision manual o error. {muestra}"
        )


class TaskRunner:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.process: subprocess.Popen[str] | None = None
        self.action = ""
        self.started_at = 0.0
        self.exit_code: int | None = None
        self.lines: list[str] = []
        self.error_notified = False
        self.manual_notified = False
        self.permission_error = False
        self.scan_blocked_by_permissions = False
        self.last_detection_at = 0.0

    def start(self, action: str, args: list[str]) -> tuple[bool, str]:
        with self.lock:
            if self.process and self.process.poll() is None:
                return False, "Ya hay un proceso en marcha."

            self.action = action
            self.started_at = time.time()
            self.exit_code = None
            self.lines = [f"$ {sys.executable} corrector_agente.py {' '.join(args)}"]
            self.error_notified = False
            self.manual_notified = False
            self.permission_error = False
            env = os.environ.copy()
            if action in {"detect_course", "auto_correct", "check_playwright"}:
                env["CARM_HEADLESS"] = "1"
            self.process = subprocess.Popen(
                [sys.executable, "corrector_agente.py", *args],
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            threading.Thread(target=self._read_output, daemon=True).start()
            return True, "Proceso iniciado."

    def _read_output(self) -> None:
        proc = self.process
        if not proc or not proc.stdout:
            return
        for line in proc.stdout:
            clean = line.rstrip()
            with self.lock:
                self.lines.append(clean)
                self.lines = self.lines[-700:]
            self._notify_line(clean)
        code = proc.wait()
        should_auto_correct = False
        should_retry_scan = False
        has_error = False
        with self.lock:
            self.exit_code = code
            self.lines.append(f"[proceso terminado con codigo {code}]")
            has_error = any(" - ERROR - " in line or line.startswith("ERROR") for line in self.lines)
            self.permission_error = any(self._is_permission_error(line) for line in self.lines)
            if self.action == "detect_course" and self.permission_error:
                self.scan_blocked_by_permissions = True
            if self.action in {"detect_course", "check_playwright"} and code == 0 and not has_error:
                self.last_detection_at = time.time()
            if self.action == "check_playwright" and code == 0 and not has_error and self.scan_blocked_by_permissions:
                self.scan_blocked_by_permissions = False
                should_retry_scan = True
            should_auto_correct = (
                AUTO_CORRECT_AFTER_SCAN
                and self.action == "detect_course"
                and code == 0
                and not has_error
            )
        if has_error:
            if self.permission_error:
                notify("Corrector CARM", "Windows bloqueo Playwright/Chromium. Ejecuta la app con permisos permitidos.")
            else:
                notify("Corrector CARM", "Hay errores en la ultima tarea. Abre la interfaz para revisar el log.")
        elif self.action == "auto_correct":
            notify("Corrector CARM", "Correccion automatica terminada. Revisa el CSV antes de publicar.")
        if should_retry_scan:
            notify("Corrector CARM", "Permisos de navegador recuperados. Repito el escaneo de CARM.")
            threading.Timer(1.0, lambda: self.start("detect_course", ["--cachear-curso", "--refrescar-cache"])).start()
        if should_auto_correct:
            notify("Corrector CARM", "CARM revisado. Empiezo a preparar correcciones automaticamente.")
            threading.Timer(1.0, lambda: self.start("auto_correct", AUTO_CORRECT_ARGS)).start()

    def _notify_line(self, line: str) -> None:
        lowered = line.lower()
        if (" - error - " in lowered or lowered.startswith("error")) and not self.error_notified:
            self.error_notified = True
            notify("Corrector CARM - error", line)
        manual_markers = (
            "requiere revisión manual",
            "requiere revision manual",
            "entrega marcada para revisión manual",
            "entrega marcada para revision manual",
            "no se pudo extraer texto",
            "formato no textual",
            "formato no reconocido",
        )
        if any(marker in lowered for marker in manual_markers) and not self.manual_notified:
            self.manual_notified = True
            notify("Corrector CARM - revision manual", line)

    @staticmethod
    def _is_permission_error(line: str) -> bool:
        lowered = line.lower()
        return (
            "winerror 5" in lowered
            or "permissionerror" in lowered
            or "acceso denegado" in lowered
        )

    def stop(self) -> bool:
        with self.lock:
            if not self.process or self.process.poll() is not None:
                return False
            self.process.terminate()
            self.lines.append("[detencion solicitada]")
            return True

    def snapshot(self) -> dict:
        with self.lock:
            running = bool(self.process and self.process.poll() is None)
            has_error = any(" - ERROR - " in line or line.startswith("ERROR") for line in self.lines)
            permission_error = self.permission_error or any(self._is_permission_error(line) for line in self.lines)
            return {
                "running": running,
                "action": self.action,
                "started_at": self.started_at,
                "elapsed": round(time.time() - self.started_at, 1) if self.started_at else 0,
                "exit_code": self.exit_code,
                "has_error": has_error,
                "permission_error": permission_error,
                "scan_blocked_by_permissions": self.scan_blocked_by_permissions,
                "last_detection_at": self.last_detection_at,
                "lines": self.lines[-220:],
            }


RUNNER = TaskRunner()


def read_json_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if not length:
        return {}
    raw = handler.rfile.read(length).decode("utf-8")
    return json.loads(raw or "{}")


def send_json(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def valid_api_token(handler: BaseHTTPRequestHandler) -> bool:
    return secrets.compare_digest(handler.headers.get("X-Corrector-Token", ""), API_TOKEN)


def require_api_token(handler: BaseHTTPRequestHandler) -> bool:
    if valid_api_token(handler):
        return True
    send_json(handler, {"ok": False, "message": "Token local no valido."}, HTTPStatus.FORBIDDEN)
    return False


def create_local_server(host: str, port: int) -> tuple[ThreadingHTTPServer, int, list[int]]:
    attempted: list[int] = []
    if port == 0:
        server = ThreadingHTTPServer((host, 0), Handler)
        return server, int(server.server_address[1]), attempted
    for candidate in range(port, port + PORT_FALLBACK_ATTEMPTS):
        attempted.append(candidate)
        try:
            server = ThreadingHTTPServer((host, candidate), Handler)
            return server, candidate, attempted
        except OSError:
            continue
    tried = ", ".join(str(item) for item in attempted)
    raise OSError(f"No se pudo abrir la interfaz local. Puertos probados: {tried}.")


def file_info(path: Path) -> dict:
    return {
        "path": str(path),
        "exists": path.exists(),
        "modified": path.stat().st_mtime if path.exists() else 0,
        "size": path.stat().st_size if path.exists() else 0,
    }


def pending_publication_state() -> dict:
    combined = file_info(COMBINED_JSON)
    revision = file_info(REVISION_CSV)
    published = file_info(SUBIDA_PUBLICADA_JSON)
    assisted = file_info(SUBIDA_ASISTIDA_JSON)
    rows = 0
    blocking = 0
    if REVISION_CSV.exists():
        try:
            with REVISION_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
                data = list(csv.DictReader(handle, delimiter=";"))
            rows = len(data)
            estados_bloqueantes = {"revision_manual_necesaria", "error", "error_descarga", "sin_archivo_detectado", "sin_entrega"}
            blocking = sum(1 for row in data if (row.get("estado") or "").strip().lower() in estados_bloqueantes)
        except Exception:
            blocking = 1
    base_modified = max(combined["modified"], revision["modified"])
    pending = bool(combined["exists"] and revision["exists"] and rows and published["modified"] < base_modified)
    return {
        "pending": pending,
        "rows": rows,
        "blocking": blocking,
        "ready_for_assisted_upload": pending and blocking == 0,
        "combined": combined,
        "revision_csv": revision,
        "published": published,
        "assisted": assisted,
    }


def notify_pending_publication() -> None:
    pending = pending_publication_state()
    if not pending["pending"]:
        return
    if pending["blocking"]:
        notify(
            "Corrector CARM",
            f"Hay {pending['rows']} calificaciones preparadas, pero {pending['blocking']} requieren revision antes de subir.",
        )
        return
    notify(
        "Corrector CARM",
        f"Hay {pending['rows']} calificaciones revisadas pendientes de subir. Abre la interfaz para iniciar subida asistida.",
    )


def latest_log_lines(path: Path, limit: int = 80) -> list[str]:
    if not path.exists():
        return []
    try:
        return [redact_text(line) for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]]
    except Exception as exc:
        return [f"No se pudo leer el log: {exc}"]


def _cache_paths() -> list[Path]:
    cache_dir = ROOT / "cache_carm"
    if not cache_dir.exists():
        return []
    return sorted(cache_dir.glob("curso_*.sqlite"), key=lambda p: p.stat().st_mtime, reverse=True)


def _cache_path_for_current_course() -> Path | None:
    course_id = course_id_from_url(current_course_url())
    if not course_id:
        return None
    path = ROOT / "cache_carm" / f"curso_{course_id}.sqlite"
    return path if path.exists() else None


def detected_courses() -> list[dict]:
    cursos: list[dict] = []
    for path in _cache_paths():
        course_id = path.stem.replace("curso_", "", 1)
        url = course_url_from_id(course_id) if course_id.isdigit() else ""
        titulo = ""
        updated = path.stat().st_mtime
        try:
            with sqlite3.connect(path) as con:
                row = con.execute(
                    "SELECT url, COALESCE(titulo, ''), COALESCE(actualizado_en, '') FROM curso LIMIT 1"
                ).fetchone()
                if row:
                    url = row[0] or url
                    titulo = row[1] or ""
        except sqlite3.Error:
            pass
        cursos.append(
            {
                "id": course_id,
                "url": url,
                "titulo": titulo or f"Curso {course_id}",
                "cache_path": str(path),
                "modified": updated,
                "current": course_id == course_id_from_url(current_course_url()),
            }
        )
    return cursos


def course_options() -> dict:
    units: dict[str, str] = {}
    activities: dict[str, dict] = {}
    cache_path = ""
    cache_modified = 0.0
    didactic_units = 0
    preferred = _cache_path_for_current_course()
    paths = [preferred] if preferred else []
    paths.extend(path for path in _cache_paths() if path not in paths)
    for path in paths[:1]:
        if path is None:
            continue
        cache_path = str(path)
        cache_modified = path.stat().st_mtime
        try:
            with sqlite3.connect(path) as con:
                for codigo, nombre, contenido in con.execute(
                    "SELECT codigo, COALESCE(nombre, ''), COALESCE(contenido_imprimible, '') FROM unidad ORDER BY codigo"
                ).fetchall():
                    codigo = str(codigo or "").strip().lower()
                    if UNIT_RE.fullmatch(codigo):
                        units[codigo] = str(nombre or codigo.upper())
                        if str(contenido or "").strip():
                            didactic_units += 1
                for codigo, unidad, nombre, tipo in con.execute(
                    "SELECT codigo, COALESCE(unidad_codigo, ''), COALESCE(nombre, ''), COALESCE(tipo, '') FROM actividad ORDER BY CASE WHEN tipo = 'obligatorio' THEN 0 ELSE 1 END, codigo"
                ).fetchall():
                    codigo = str(codigo or "").strip().lower()
                    unidad = str(unidad or "").strip().lower()
                    if ACTIVITY_RE.fullmatch(codigo):
                        if not UNIT_RE.fullmatch(unidad):
                            unidad = codigo[:4]
                        units.setdefault(unidad, unidad.upper())
                        activities[codigo] = {
                            "codigo": codigo,
                            "unidad": unidad,
                            "nombre": str(nombre or codigo.upper()),
                            "tipo": str(tipo or ""),
                        }
        except sqlite3.Error:
            continue
        break

    if not activities:
        activities = {}

    return {
        "source": "cache_didactica" if cache_path else "fallback",
        "course_url": current_course_url(),
        "course_id": course_id_from_url(current_course_url()),
        "detected_courses": detected_courses(),
        "cache_path": cache_path,
        "cache_modified": cache_modified,
        "didactic_units": didactic_units,
        "units": [{"codigo": codigo, "nombre": nombre} for codigo, nombre in sorted(units.items())],
        "activities": sorted(
            activities.values(),
            key=lambda item: (0 if item.get("tipo") == "obligatorio" else 1, item["codigo"]),
        ),
    }


def project_state() -> dict:
    prompts = sorted(PROMPTS_DIR.glob("prompt_*.md")) if PROMPTS_DIR.exists() else []
    corrections = sorted(PROMPTS_DIR.glob("*_correccion.json")) if PROMPTS_DIR.exists() else []
    return {
        "combined": file_info(COMBINED_JSON),
        "revision_csv": file_info(REVISION_CSV),
        "pendientes_dir": str(PENDIENTES_DIR),
        "prompts_dir": str(PROMPTS_DIR),
        "temporal_dir": str(TEMPORAL_DIR),
        "auto_scan_interval_minutes": auto_scan_interval_minutes(),
        "json_options": json_options(),
        "prompts": [file_info(p) for p in prompts],
        "corrections": [file_info(p) for p in corrections],
        "agent_log": latest_log_lines(AGENTE_LOG),
        "pending_publication": pending_publication_state(),
    }


def allowed_units() -> set[str]:
    options = course_options()
    return {item["codigo"] for item in options["units"]}


def allowed_activities() -> set[str]:
    options = course_options()
    return {item["codigo"] for item in options["activities"]}


def require_allowed(value: str, allowed: set[str], label: str) -> str:
    if value not in allowed:
        raise ValueError(f"{label} no permitido.")
    return value


HTML = r"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Corrector CARM</title>
  <style>
    :root {
      --bg: #eef2ef;
      --panel: #ffffff;
      --ink: #1d2524;
      --muted: #66736f;
      --line: #d9ded8;
      --green: #1f7a5b;
      --green-soft: #e8f4ee;
      --amber: #a86200;
      --red: #b42318;
      --blue: #2f5f95;
      --blue-soft: #eaf1f8;
      --surface: #f7f9f7;
      --shadow: 0 10px 30px rgba(16, 24, 40, .07);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: "Segoe UI", Arial, sans-serif;
      font-size: 14px;
    }
    header {
      min-height: 68px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
      padding: 12px 24px;
      border-bottom: 1px solid var(--line);
      background: rgba(251, 252, 250, .96);
      position: sticky;
      top: 0;
      z-index: 10;
      backdrop-filter: blur(10px);
    }
    h1 { font-size: 20px; margin: 0; font-weight: 700; letter-spacing: 0; }
    h2 { font-size: 15px; margin: 0; font-weight: 700; letter-spacing: 0; }
    h3 { font-size: 13px; margin: 0; font-weight: 700; letter-spacing: 0; }
    main {
      display: grid;
      grid-template-columns: minmax(360px, 460px) minmax(0, 1fr);
      gap: 18px;
      padding: 18px;
      max-width: 1440px;
      margin: 0 auto;
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 16px;
    }
    .brand { display: flex; align-items: center; gap: 12px; min-width: 260px; }
    .brand-mark {
      width: 38px;
      height: 38px;
      border-radius: 8px;
      background: var(--green);
      color: #fff;
      display: grid;
      place-items: center;
      font-weight: 800;
      box-shadow: 0 10px 18px rgba(31, 122, 91, .2);
    }
    .brand small { display: block; color: var(--muted); margin-top: 2px; }
    .topbar-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
    .workflow {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 14px;
    }
    .step {
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      padding: 11px;
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 10px;
      align-items: center;
      min-width: 0;
    }
    .step-num {
      width: 28px;
      height: 28px;
      border-radius: 999px;
      display: grid;
      place-items: center;
      background: #eef1f0;
      color: var(--muted);
      font-weight: 800;
      font-size: 12px;
    }
    .step.done .step-num { background: var(--green-soft); color: var(--green); }
    .step.active .step-num { background: var(--blue-soft); color: var(--blue); }
    .step small { color: var(--muted); display: block; margin-top: 2px; }
    .stack { display: grid; gap: 12px; }
    .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .split { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
    .section-head { margin-bottom: 12px; }
    .section-head p { margin: 4px 0 0; color: var(--muted); font-size: 12px; line-height: 1.45; }
    label { color: var(--muted); font-size: 12px; display: block; margin-bottom: 4px; }
    input, select {
      width: 100%;
      height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 6px 8px;
      background: #fff;
      color: var(--ink);
    }
    input:focus, select:focus {
      outline: 2px solid rgba(47, 95, 149, .18);
      border-color: var(--blue);
    }
    .field { flex: 1 1 130px; min-width: 0; }
    button {
      height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--ink);
      padding: 0 12px;
      cursor: pointer;
      font-weight: 600;
    }
    button:hover:not(:disabled) { border-color: #b8c3bd; background: #f9fbfa; }
    button.primary:hover:not(:disabled) { background: #19694e; border-color: #19694e; }
    button.primary { background: var(--green); border-color: var(--green); color: #fff; }
    button.warn { background: #fff8ea; color: var(--amber); border-color: #e7c98b; }
    button.danger { background: #fff1f0; color: var(--red); border-color: #f0b8b2; }
    button.icon {
      width: 34px;
      padding: 0;
      display: inline-grid;
      place-items: center;
      font-size: 17px;
    }
    button:disabled { opacity: .55; cursor: not-allowed; }
    .button-row { display: grid; grid-template-columns: 1fr auto; gap: 8px; margin-top: 12px; }
    .button-row.two { grid-template-columns: 1fr 1fr; }
    .button-row.three { grid-template-columns: 1fr 1fr 1fr; }
    .badge {
      display: inline-flex;
      align-items: center;
      height: 24px;
      padding: 0 8px;
      border-radius: 999px;
      background: var(--green-soft);
      color: var(--green);
      font-size: 12px;
      font-weight: 700;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 28px;
      padding: 4px 8px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #fff;
      color: var(--muted);
      font-size: 12px;
    }
    .badge.idle { background: #eef1f0; color: var(--muted); }
    .badge.err { background: #fff1f0; color: var(--red); }
    .system-notice {
      display: none;
      max-width: 1440px;
      margin: 12px auto 0;
      padding: 0 18px;
    }
    .system-notice.open { display: block; }
    .system-notice > div {
      border: 1px solid #e7c98b;
      background: #fff8ea;
      color: #5f3b00;
      border-radius: 8px;
      padding: 10px 12px;
      line-height: 1.45;
    }
    .path {
      font-family: Consolas, "Courier New", monospace;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px;
      overflow-wrap: anywhere;
      color: #31413d;
      line-height: 1.45;
    }
    .list { display: grid; gap: 6px; }
    .item {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      align-items: center;
      padding: 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--surface);
    }
    .item span { min-width: 0; overflow-wrap: anywhere; }
    .item > small { white-space: nowrap; }
    .item small, .muted { color: var(--muted); }
    .summary-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 12px;
    }
    .metric {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
    }
    .metric strong { display: block; font-size: 20px; margin-bottom: 2px; }
    .metric span { color: var(--muted); font-size: 12px; }
    .activity-panel {
      display: grid;
      grid-template-rows: auto minmax(320px, 1fr);
      min-height: calc(100vh - 104px);
    }
    pre {
      min-height: 420px;
      max-height: calc(100vh - 210px);
      overflow: auto;
      margin: 0;
      padding: 12px;
      background: #17211f;
      color: #d7eee5;
      border-radius: 8px;
      font-family: Consolas, "Courier New", monospace;
      font-size: 12px;
      line-height: 1.45;
      white-space: pre-wrap;
    }
    .grid2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
    .check { display: flex; align-items: center; gap: 8px; color: var(--muted); }
    .check input { width: auto; height: auto; }
    .modal-backdrop {
      position: fixed;
      inset: 0;
      z-index: 20;
      display: none;
      align-items: flex-start;
      justify-content: center;
      padding: 72px 16px 24px;
      background: rgba(20, 29, 27, .38);
    }
    .modal-backdrop.open { display: flex; }
    .modal-backdrop.locked {
      background: rgba(20, 29, 27, .72);
      backdrop-filter: blur(3px);
    }
    body.auth-locked main,
    body.auth-locked header .topbar-actions {
      filter: grayscale(.35);
      pointer-events: none;
      user-select: none;
    }
    .modal {
      width: min(760px, 100%);
      max-height: calc(100vh - 96px);
      overflow: auto;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 18px 52px rgba(16, 24, 40, .22);
      padding: 14px;
    }
    .hint {
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }
    .advanced-fields { display: none; }
    .advanced-fields.active { display: grid; gap: 10px; }
    .folder-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: end;
    }
    @media (max-width: 900px) {
      main { grid-template-columns: 1fr; }
      .grid2 { grid-template-columns: 1fr; }
      .workflow { grid-template-columns: 1fr; }
      .summary-grid { grid-template-columns: 1fr; }
      header { align-items: flex-start; flex-direction: column; }
      .topbar-actions { justify-content: flex-start; }
      .button-row, .button-row.two, .button-row.three { grid-template-columns: 1fr; }
      .folder-row { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <div class="brand-mark">C</div>
      <div>
        <h1>Corrector CARM</h1>
        <small>Panel local de preparacion, revision y subida</small>
      </div>
    </div>
    <div class="topbar-actions">
      <span id="courseSummary" class="pill"></span>
      <span id="statusBadge" class="badge idle">Parado</span>
      <button id="refreshBtn">Actualizar</button>
      <button id="logoutBtn">Borrar credenciales CARM</button>
      <button id="settingsBtn" class="icon" title="Configuracion" aria-label="Configuracion">⚙</button>
    </div>
  </header>
  <div id="systemNotice" class="system-notice" role="status" aria-live="polite">
    <div id="systemNoticeText"></div>
  </div>
  <main>
    <div class="stack">
      <div class="workflow" aria-label="Flujo principal">
        <div class="step active" id="stepPrepare">
          <div class="step-num">1</div>
          <div><strong>Preparar</strong><small>CARM y Codex</small></div>
        </div>
        <div class="step" id="stepReview">
          <div class="step-num">2</div>
          <div><strong>Revisar</strong><small>JSON y CSV</small></div>
        </div>
        <div class="step" id="stepPublish">
          <div class="step-num">3</div>
          <div><strong>Subir</strong><small>Notas y feedback</small></div>
        </div>
      </div>

      <section>
        <div class="section-head">
          <h2>Preparar correcciones</h2>
          <p>Elige una unidad o un caso concreto y genera las salidas revisables.</p>
        </div>
        <div class="row">
          <div class="field">
            <label for="prepareMode">Filtro</label>
            <select id="prepareMode">
              <option value="unit">Unidad completa</option>
              <option value="activity">Caso practico</option>
            </select>
          </div>
          <div class="field" id="activityField">
            <label for="actividad">Caso practico</label>
            <select id="actividad"></select>
          </div>
        </div>
        <div class="row">
          <div class="field">
            <label for="unidad">Unidad</label>
            <select id="unidad"></select>
          </div>
          <div class="field">
            <label for="maxEntregas">Entregas por prompt</label>
            <select id="maxEntregas">
              <option value="0">Todos los pendientes</option>
              <option value="3">3</option>
              <option value="4">4</option>
              <option value="5">5</option>
              <option value="6" selected>6</option>
              <option value="8">8</option>
              <option value="10">10</option>
              <option value="12">12</option>
            </select>
          </div>
        </div>
        <div class="button-row">
          <button class="primary" id="prepareBtn">Preparar con Codex</button>
          <button class="danger" id="stopBtn">Detener</button>
        </div>
      </section>

      <section>
        <div class="section-head">
          <h2>Subida a CARM</h2>
          <p>Previsualiza primero. La subida asistida rellena campos y espera tu guardado manual.</p>
        </div>
        <label for="jsonPath">JSON de correcciones</label>
        <select id="jsonPath">
          <option value="C:\temp\vscodec\temporal\prompts_codex\correcciones_codex_combinadas.json">correcciones_codex_combinadas.json</option>
          <option value="C:\temp\vscodec\temporal\prompts_codex\prompt_ud01cp01_correccion.json">prompt_ud01cp01_correccion.json</option>
          <option value="C:\temp\vscodec\temporal\prompts_codex\prompt_ud01cp02_correccion.json">prompt_ud01cp02_correccion.json</option>
          <option value="C:\temp\vscodec\temporal\prompts_codex\prompt_ud02cp03_correccion.json">prompt_ud02cp03_correccion.json</option>
        </select>
        <div class="button-row three">
          <button id="previewBtn">Previsualizar</button>
          <button class="primary" id="assistPublishBtn">Subida asistida</button>
          <button class="warn" id="publishBtn">Publicar</button>
        </div>
        <label class="check" style="margin-top:10px">
          <input type="checkbox" id="publishCheck">
          Confirmo que he revisado las correcciones
        </label>
      </section>

      <section>
        <div class="section-head">
          <h2>Estado de salidas</h2>
          <p>Estos archivos son la base de la revision antes de subir a CARM.</p>
        </div>
        <div class="summary-grid">
          <div class="metric">
            <strong id="promptCount">0</strong>
            <span>prompts listos</span>
          </div>
          <div class="metric">
            <strong id="correctionCount">0</strong>
            <span>JSON de correccion</span>
          </div>
        </div>
        <div class="stack">
          <div>
            <label>JSON combinado</label>
            <div id="combinedPath" class="path"></div>
          </div>
          <div>
            <label>CSV de revisión</label>
            <div id="revisionPath" class="path"></div>
          </div>
        </div>
      </section>

      <section>
        <div class="section-head">
          <h2>Archivos recientes</h2>
          <p>Prompts enviados y respuestas JSON recibidas.</p>
        </div>
        <div class="stack">
          <div>
            <label>Prompts</label>
            <div id="promptsList" class="list"></div>
          </div>
          <div>
            <label>Correcciones</label>
            <div id="correctionsList" class="list"></div>
          </div>
        </div>
      </section>
    </div>

    <section class="activity-panel">
      <div class="split">
        <div class="section-head">
          <h2>Actividad</h2>
          <p>Registro de ejecucion y avisos del backend.</p>
        </div>
        <span id="elapsed" class="muted"></span>
      </div>
      <pre id="logBox"></pre>
    </section>
  </main>

  <div id="authModal" class="modal-backdrop" aria-hidden="true">
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="authTitle">
      <div class="split">
        <h2 id="authTitle">Configurar CARM</h2>
        <span id="authSubtitle" class="muted">Acceso requerido</span>
      </div>
      <div class="stack" style="margin-top:12px">
        <p class="hint">Introduce tus credenciales de CARM. La app las comprobara en CARM antes de guardarlas localmente.</p>
        <div class="grid2">
          <div>
            <label for="carmUser">Usuario CARM</label>
            <input id="carmUser" autocomplete="username">
          </div>
          <div>
            <label for="carmPass">Contrasena CARM</label>
            <input id="carmPass" type="password" autocomplete="current-password">
          </div>
        </div>
        <div class="path" id="authMessage">Pendiente de configurar.</div>
        <div class="row">
          <button class="primary" id="saveAuthBtn">Verificar y guardar</button>
        </div>
      </div>
    </div>
  </div>

  <div id="settingsModal" class="modal-backdrop" aria-hidden="true">
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="settingsTitle">
      <div class="split">
        <h2 id="settingsTitle">Configuracion</h2>
        <button id="closeSettingsBtn" class="icon" title="Cerrar" aria-label="Cerrar">×</button>
      </div>
      <div class="stack" style="margin-top:12px">
        <section style="box-shadow:none">
          <div class="section-head">
            <h2>Carpetas de trabajo</h2>
            <p>La app crea estas carpetas si no existen. Puedes cambiarlas con el explorador de Windows.</p>
          </div>
          <div class="stack">
            <div class="folder-row">
              <div>
                <label for="pendientesDir">Entregas descargadas</label>
                <input id="pendientesDir">
              </div>
              <button id="pickPendientesBtn" type="button">Elegir...</button>
            </div>
            <div class="folder-row">
              <div>
                <label for="temporalDir">Salidas y correcciones</label>
                <input id="temporalDir">
              </div>
              <button id="pickTemporalBtn" type="button">Elegir...</button>
            </div>
            <div class="path" id="foldersMessage">Usando carpetas por defecto.</div>
            <div class="row">
              <button class="primary" id="saveFoldersBtn" type="button">Guardar carpetas</button>
            </div>
          </div>
        </section>

        <section style="box-shadow:none">
          <div class="section-head">
            <h2>Curso CARM</h2>
            <p>Cambia el curso activo si tienes varias caches o si vas a corregir otro curso.</p>
          </div>
          <div class="stack">
            <div>
              <label for="courseUrl">URL o ID del curso</label>
              <input id="courseUrl" placeholder="https://formacion.carm.es/course/view.php?id=1592">
            </div>
            <div>
              <label for="detectedCourse">Cursos detectados en cache</label>
              <select id="detectedCourse"></select>
            </div>
            <div class="path" id="courseMessage">Curso pendiente de cargar.</div>
            <div class="row">
              <button class="primary" id="saveCourseBtn" type="button">Guardar curso</button>
              <button id="useDetectedCourseBtn" type="button">Usar detectado</button>
            </div>
            <div class="grid2">
              <div>
                <label for="autoScanInterval">Autodetectar cada (minutos)</label>
                <input id="autoScanInterval" type="number" min="0" max="1440" step="5">
              </div>
              <div>
                <label>&nbsp;</label>
                <button id="saveAutomationBtn" type="button">Guardar automatizacion</button>
              </div>
            </div>
            <p class="hint">Usa 0 para desactivar el refresco periodico. Al iniciar, la app tambien puede actualizar datos si no usas `--no-startup-scan`.</p>
          </div>
        </section>

        <div>
          <label for="advancedAction">Comando</label>
          <select id="advancedAction">
            <option value="detect_course">Actualizar datos didacticos desde CARM</option>
            <option value="check_playwright">Comprobar permisos de navegador</option>
            <option value="diagnose">Diagnosticar CARM</option>
            <option value="diagnose_evidence">Diagnosticar CARM con evidencias</option>
            <option value="list_carm">Listar entregas pendientes</option>
            <option value="cache_course">Cachear curso</option>
            <option value="prepare_carm_codex">Preparar prompts desde CARM</option>
            <option value="prepare_carm_codex_activity">Preparar prompts de un caso desde CARM</option>
            <option value="prepare_local_prompts">Preparar prompts desde archivos locales</option>
            <option value="import_codex">Importar JSON de Codex</option>
            <option value="delete_cache">Borrar cache del curso</option>
          </select>
          <p id="advancedHint" class="hint"></p>
        </div>

        <div id="fieldsUnidad" class="advanced-fields">
          <div class="grid2">
            <div>
              <label for="advancedUnidad">Unidad</label>
              <select id="advancedUnidad"></select>
            </div>
            <div>
              <label for="advancedMaxEntregas">Entregas por prompt</label>
              <select id="advancedMaxEntregas">
                <option value="0">Todos los pendientes</option>
                <option value="3">3</option>
                <option value="4">4</option>
                <option value="5">5</option>
                <option value="6" selected>6</option>
                <option value="8">8</option>
                <option value="10">10</option>
                <option value="12">12</option>
              </select>
            </div>
          </div>
        </div>

        <div id="fieldsActivity" class="advanced-fields">
          <div>
            <label for="advancedActividad">Caso practico</label>
            <select id="advancedActividad"></select>
          </div>
        </div>

        <div id="fieldsLocal" class="advanced-fields">
          <div>
            <label for="contextPath">Archivo de contexto de unidad</label>
            <select id="contextPath">
              <option value="C:\Users\ruben\Desktop\agente\tmp_prueba\manual_ud01.txt">tmp_prueba\manual_ud01.txt</option>
            </select>
          </div>
          <div>
            <label for="localActivity">Actividad</label>
            <select id="localActivity">
              <option value="ud01cp01">ud01cp01</option>
            </select>
          </div>
        </div>

        <div id="fieldsImport" class="advanced-fields">
          <div>
            <label for="importJsonPath">JSON devuelto por Codex/ChatGPT</label>
            <select id="importJsonPath">
              <option value="C:\temp\vscodec\temporal\prompts_codex\correcciones_codex_combinadas.json">correcciones_codex_combinadas.json</option>
              <option value="C:\temp\vscodec\temporal\prompts_codex\prompt_ud01cp01_correccion.json">prompt_ud01cp01_correccion.json</option>
              <option value="C:\temp\vscodec\temporal\prompts_codex\prompt_ud01cp02_correccion.json">prompt_ud01cp02_correccion.json</option>
              <option value="C:\temp\vscodec\temporal\prompts_codex\prompt_ud02cp03_correccion.json">prompt_ud02cp03_correccion.json</option>
            </select>
          </div>
        </div>

        <div class="path" id="advancedCommandPreview"></div>
        <div class="row">
          <button class="primary" id="runAdvancedBtn">Ejecutar comando</button>
          <button id="cancelSettingsBtn">Cancelar</button>
        </div>
      </div>
    </div>
  </div>

  <script>
    const $ = (id) => document.getElementById(id);
    const API_TOKEN = "__LOCAL_API_TOKEN__";
    const advancedHints = {
      diagnose: 'Entra en CARM, genera diagnostico limpio y no descarga entregas.',
      check_playwright: 'Comprueba que Windows permite abrir Playwright/Chromium e iniciar sesion en CARM.',
      diagnose_evidence: 'Guarda HTML/capturas redactadas para depurar selectores. Usalo solo si necesitas evidencias.',
      detect_course: 'Entra en CARM y actualiza la cache didactica con unidades, casos practicos, enunciados y contenido estable.',
      list_carm: 'Lista entregas que requieren calificacion sin descargar archivos.',
      cache_course: 'Actualiza la cache local de recursos estables del curso.',
      prepare_carm_codex: 'Descarga desde CARM y genera prompts para Codex sin llamar a la API.',
      prepare_carm_codex_activity: 'Descarga y prepara prompts solo para el caso practico elegido.',
      prepare_local_prompts: 'Lee entregas ya descargadas y genera prompts usando un archivo de contexto local.',
      import_codex: 'Importa un JSON de correcciones y crea salidas revisables por alumno.',
      delete_cache: 'Borra la cache SQLite local del curso.'
    };
    const advancedLabels = {
      diagnose: '--diagnosticar-carm',
      check_playwright: '--comprobar-login-carm',
      diagnose_evidence: '--diagnosticar-carm --guardar-evidencias',
      detect_course: '--cachear-curso --refrescar-cache',
      list_carm: '--solo-listar-carm --unidad <unidad>',
      cache_course: '--cachear-curso --unidad <unidad>',
      prepare_carm_codex: '--preparar-carm-codex --unidad <unidad> --max-entregas-por-prompt <n>',
      prepare_carm_codex_activity: '--preparar-carm-codex --actividad <caso> --max-entregas-por-prompt <n>',
      prepare_local_prompts: '--contexto-unidad <archivo> --preparar-prompts-codex --actividad-codigo <actividad>',
      import_codex: '--importar-correcciones-codex <json>',
      delete_cache: '--borrar-cache-curso'
    };
    let courseOptions = {units: [], activities: []};
    let authState = {configured: false, session_saved: false};

    function showSystemNotice(message) {
      $('systemNoticeText').textContent = message;
      $('systemNotice').classList.add('open');
    }

    function clearSystemNotice() {
      $('systemNotice').classList.remove('open');
      $('systemNoticeText').textContent = '';
    }

    async function api(path, options = {}) {
      let res;
      try {
        res = await fetch(path, {
          ...options,
          headers: {
            'Content-Type': 'application/json',
            'X-Corrector-Token': API_TOKEN,
            ...(options.headers || {})
          }
        });
      } catch (err) {
        showSystemNotice('No se puede conectar con el servidor local. Puede haberse cerrado la app o haber cambiado el puerto; vuelve a abrir el panel desde la consola o la bandeja.');
        throw err;
      }
      let payload = {};
      try {
        payload = await res.json();
      } catch (err) {
        payload = {ok: false, message: `Respuesta local no valida (${res.status}).`};
      }
      if (res.status === 403 && String(payload.message || '').toLowerCase().includes('token')) {
        if (!sessionStorage.getItem('correctorTokenReloaded')) {
          sessionStorage.setItem('correctorTokenReloaded', '1');
          window.location.reload();
          return new Promise(() => {});
        }
        showSystemNotice('La sesion local del panel ha caducado. Recarga la pagina para recibir un token nuevo.');
        throw new Error(payload.message || 'Token local no valido.');
      }
      if (res.status === 401 || payload.auth_required) {
        authState = {configured: false, session_saved: false};
        setAuthLocked(true);
        return {...payload, ok: false};
      }
      if (res.ok) {
        sessionStorage.removeItem('correctorTokenReloaded');
        clearSystemNotice();
      }
      return payload;
    }

    function fmtFile(file) {
      const name = file.path.split(/[\\/]/).pop();
      const kb = file.exists ? Math.max(1, Math.round(file.size / 1024)) + ' KB' : 'no existe';
      return `<div class="item"><span>${name}<br><small>${file.path}</small></span><small>${kb}</small></div>`;
    }

    function optionHtml(value, label) {
      return `<option value="${value}">${label}</option>`;
    }

    function jsonOptionHtml(item) {
      const suffix = item.exists ? '' : ' · pendiente';
      return optionHtml(item.path, `${item.label}${suffix}`);
    }

    function courseOptionHtml(item) {
      const suffix = item.current ? ' · actual' : '';
      return optionHtml(item.url, `${item.id} · ${item.titulo}${suffix}`);
    }

    function activityLabel(act) {
      const tipo = act.tipo ? ` · ${act.tipo}` : '';
      return `${act.codigo} · ${act.nombre}${tipo}`;
    }

    function fillSelect(select, html, current = '') {
      select.innerHTML = html;
      if (current && [...select.options].some((opt) => opt.value === current)) select.value = current;
    }

    function activitiesForUnit(unit) {
      return courseOptions.activities.filter((item) => item.unidad === unit);
    }

    async function loadOptions() {
      courseOptions = await api('/api/options');
      const unitHtml = courseOptions.units.length
        ? courseOptions.units.map((unit) => optionHtml(unit.codigo, `${unit.codigo} · ${unit.nombre}`)).join('')
        : '<option value="">Sin unidades detectadas</option>';
      fillSelect($('unidad'), unitHtml, $('unidad').value || 'ud01');
      fillSelect($('advancedUnidad'), unitHtml, $('advancedUnidad').value || $('unidad').value);
      updateActivityOptions();
      updateAdvancedActivityOptions();
      const source = courseOptions.source === 'cache_didactica'
        ? (courseOptions.didactic_units < courseOptions.units.length ? 'cache parcial' : 'cache didactica')
        : 'valores base';
      $('courseSummary').textContent = `${courseOptions.units.length} unidades · ${courseOptions.activities.length} casos · ${source}`;
    }

    async function loadAuth() {
      authState = await api('/api/auth');
      $('logoutBtn').disabled = !authState.configured;
      setAuthLocked(!authState.configured);
      return authState;
    }

    function updateActivityOptions() {
      const unit = $('unidad').value;
      const activities = activitiesForUnit(unit);
      const source = activities;
      fillSelect(
        $('actividad'),
        source.length
          ? source.map((act) => optionHtml(act.codigo, activityLabel(act))).join('')
          : '<option value="">Sin casos detectados para esta unidad</option>',
        $('actividad').value
      );
      $('activityField').style.display = $('prepareMode').value === 'activity' ? '' : 'none';
    }

    function updateAdvancedActivityOptions() {
      fillSelect(
        $('advancedActividad'),
        courseOptions.activities.length
          ? courseOptions.activities.map((act) => optionHtml(act.codigo, activityLabel(act))).join('')
          : '<option value="">Sin casos detectados</option>',
        $('advancedActividad').value || $('actividad').value
      );
      fillSelect(
        $('localActivity'),
        courseOptions.activities.length
          ? courseOptions.activities.map((act) => optionHtml(act.codigo, act.codigo)).join('')
          : '<option value="">Sin casos detectados</option>',
        $('localActivity').value || $('actividad').value
      );
    }

    function setBusy(running) {
      const locked = running || !authState.configured;
      const hasUnits = courseOptions.units.length > 0;
      const hasSelectedActivity = $('prepareMode').value !== 'activity' || Boolean($('actividad').value);
      $('prepareBtn').disabled = locked || !hasUnits || !hasSelectedActivity;
      $('previewBtn').disabled = locked;
      $('assistPublishBtn').disabled = locked || !$('publishCheck').checked;
      $('publishBtn').disabled = locked || !$('publishCheck').checked;
      $('stopBtn').disabled = !running;
      $('runAdvancedBtn').disabled = locked;
    }

    function setWorkflow(status, state) {
      const hasReviewFiles = state.combined.exists && state.revision_csv.exists;
      $('stepPrepare').className = 'step ' + (hasReviewFiles ? 'done' : 'active');
      $('stepReview').className = 'step ' + (hasReviewFiles ? 'active' : '');
      $('stepPublish').className = 'step ' + ($('publishCheck').checked ? 'active' : '');
      if (status.running) {
        $('stepPrepare').className = 'step active';
        $('stepReview').className = 'step';
        $('stepPublish').className = 'step';
      }
    }

    function toggleAuth(open) {
      $('authModal').classList.toggle('open', open);
      $('authModal').setAttribute('aria-hidden', open ? 'false' : 'true');
    }

    function setAuthLocked(locked) {
      document.body.classList.toggle('auth-locked', locked);
      $('authModal').classList.toggle('locked', locked);
      toggleAuth(locked);
      $('authSubtitle').textContent = locked ? 'Acceso requerido' : 'Credenciales configuradas';
      if (locked) {
        $('authMessage').textContent = 'Introduce y verifica credenciales CARM para usar el panel.';
        showSystemNotice('Panel bloqueado: faltan credenciales CARM verificadas.');
      }
    }

    function toggleSettings(open) {
      $('settingsModal').classList.toggle('open', open);
      $('settingsModal').setAttribute('aria-hidden', open ? 'false' : 'true');
      if (open) updateAdvancedForm();
    }

    function updateAdvancedForm() {
      const action = $('advancedAction').value;
      $('advancedHint').textContent = advancedHints[action] || '';
      $('fieldsUnidad').classList.toggle('active', ['list_carm', 'cache_course', 'prepare_carm_codex'].includes(action));
      $('fieldsActivity').classList.toggle('active', action === 'prepare_carm_codex_activity');
      $('fieldsLocal').classList.toggle('active', action === 'prepare_local_prompts');
      $('fieldsImport').classList.toggle('active', action === 'import_codex');
      $('advancedCommandPreview').textContent = `corrector_agente.py ${advancedLabels[action] || ''}`;
    }

    async function pickDirectory(targetInput) {
      const result = await api('/api/pick-directory', {
        method: 'POST',
        body: JSON.stringify({initial_dir: $(targetInput).value})
      });
      if (!result.ok) {
        if (result.message) alert(result.message);
        return;
      }
      if (result.path) $(targetInput).value = result.path;
    }

    async function saveFolders() {
      $('saveFoldersBtn').disabled = true;
      $('foldersMessage').textContent = 'Guardando carpetas...';
      const result = await api('/api/config/folders', {
        method: 'POST',
        body: JSON.stringify({
          pendientes_dir: $('pendientesDir').value,
          temporal_dir: $('temporalDir').value
        })
      });
      $('foldersMessage').textContent = result.message || (result.ok ? 'Carpetas guardadas.' : 'No se pudieron guardar.');
      $('saveFoldersBtn').disabled = false;
      await refresh();
    }

    async function saveCourse(urlOrId) {
      $('saveCourseBtn').disabled = true;
      $('courseMessage').textContent = 'Guardando curso...';
      const result = await api('/api/config/course', {
        method: 'POST',
        body: JSON.stringify({course: urlOrId || $('courseUrl').value})
      });
      $('courseMessage').textContent = result.message || (result.ok ? 'Curso guardado.' : 'No se pudo guardar.');
      $('saveCourseBtn').disabled = false;
      if (result.ok) await refresh();
    }

    async function saveAutomation() {
      $('saveAutomationBtn').disabled = true;
      $('courseMessage').textContent = 'Guardando automatizacion...';
      const result = await api('/api/config/automation', {
        method: 'POST',
        body: JSON.stringify({auto_scan_interval_minutes: $('autoScanInterval').value})
      });
      $('courseMessage').textContent = result.message || (result.ok ? 'Automatizacion guardada.' : 'No se pudo guardar.');
      $('saveAutomationBtn').disabled = false;
      await refresh();
    }

    async function refresh() {
      await loadAuth();
      if (!authState.configured) {
        setBusy(false);
        return;
      }
      const status = await api('/api/status');
      const state = await api('/api/state');
      await loadOptions();
      $('pendientesDir').value = state.pendientes_dir;
      $('temporalDir').value = state.temporal_dir;
      $('autoScanInterval').value = state.auto_scan_interval_minutes;
      const jsonHtml = state.json_options.map(jsonOptionHtml).join('');
      fillSelect($('jsonPath'), jsonHtml, $('jsonPath').value);
      fillSelect($('importJsonPath'), jsonHtml, $('importJsonPath').value);
      $('courseUrl').value = courseOptions.course_url || '';
      const detectedHtml = courseOptions.detected_courses.length
        ? courseOptions.detected_courses.map(courseOptionHtml).join('')
        : '<option value="">Sin cursos detectados todavia</option>';
      fillSelect($('detectedCourse'), detectedHtml, courseOptions.course_url || '');
      $('useDetectedCourseBtn').disabled = !courseOptions.detected_courses.length;
      $('courseMessage').textContent = courseOptions.cache_path
        ? `Curso ${courseOptions.course_id} · cache: ${courseOptions.cache_path}`
        : `Curso ${courseOptions.course_id || 'sin ID'} · sin cache didactica. Ejecuta "Actualizar datos didacticos desde CARM".`;
      const badge = $('statusBadge');
      const failed = status.has_error || (status.exit_code && status.exit_code !== 0);
      badge.className = 'badge ' + (status.running ? '' : (failed ? 'err' : 'idle'));
      badge.textContent = status.running ? 'Ejecutando' : (status.permission_error ? 'Permisos Windows' : (failed ? 'Error' : 'Parado'));
      $('elapsed').textContent = status.running ? `${status.action} · ${status.elapsed}s` : '';
      $('logBox').textContent = (status.lines || []).join('\n') || (state.agent_log || []).join('\n');
      $('logBox').scrollTop = $('logBox').scrollHeight;
      if (state.pending_publication && state.pending_publication.pending) {
        const pending = state.pending_publication;
        const extra = pending.blocking
          ? `Hay ${pending.blocking} incidencia(s); revisa el CSV antes de subir.`
          : 'Puedes usar Subida asistida para rellenar CARM y guardar manualmente.';
        showSystemNotice(`Hay ${pending.rows} calificacion(es) preparadas pendientes de subir. ${extra}`);
      }
      $('combinedPath').textContent = `${state.combined.path} · ${state.combined.exists ? 'listo' : 'pendiente'}`;
      $('revisionPath').textContent = `${state.revision_csv.path} · ${state.revision_csv.exists ? 'listo' : 'pendiente'}`;
      $('promptsList').innerHTML = state.prompts.length ? state.prompts.map(fmtFile).join('') : '<span class="muted">Sin prompts</span>';
      $('correctionsList').innerHTML = state.corrections.length ? state.corrections.map(fmtFile).join('') : '<span class="muted">Sin correcciones</span>';
      $('promptCount').textContent = state.prompts.length;
      $('correctionCount').textContent = state.corrections.length;
      setWorkflow(status, state);
      setBusy(status.running);
    }

    async function safeRefresh() {
      try {
        await refresh();
      } catch (err) {
        console.warn('No se pudo refrescar el panel local', err);
      }
    }

    async function run(action, body = {}) {
      if (!authState.configured) {
        setAuthLocked(true);
        return;
      }
      const result = await api('/api/run', {method: 'POST', body: JSON.stringify({action, ...body})});
      if (!result.ok) alert(result.message || 'No se pudo iniciar');
      await refresh();
    }

    $('prepareBtn').onclick = () => run('prepare', {
      modo: $('prepareMode').value,
      unidad: $('unidad').value,
      actividad: $('actividad').value,
      max_entregas: $('maxEntregas').value
    });
    $('previewBtn').onclick = () => run('preview', {json_path: $('jsonPath').value});
    $('assistPublishBtn').onclick = () => {
      if (!$('publishCheck').checked) return alert('Marca la confirmación antes de iniciar la subida asistida.');
      run('assist_publish', {json_path: $('jsonPath').value});
    };
    $('publishBtn').onclick = () => {
      if (!$('publishCheck').checked) return alert('Marca la confirmación antes de publicar.');
      run('publish', {json_path: $('jsonPath').value});
    };
    $('stopBtn').onclick = async () => { await api('/api/stop', {method:'POST'}); await safeRefresh(); };
    $('refreshBtn').onclick = safeRefresh;
    $('logoutBtn').onclick = async () => {
      if (!confirm('Esto vaciara CARM_USUARIO/CARM_CONTRASENA en .env y borrara la sesion recordada. Tendras que volver a introducir credenciales para usar el panel. Continuar?')) return;
      const result = await api('/api/auth/logout', {method:'POST'});
      $('authMessage').textContent = result.message || 'Sesion cerrada.';
      await refresh();
    };
    $('saveAuthBtn').onclick = async () => {
      $('saveAuthBtn').disabled = true;
      $('authMessage').textContent = 'Verificando credenciales en CARM...';
      const result = await api('/api/auth/save', {
        method: 'POST',
        body: JSON.stringify({usuario: $('carmUser').value, contrasena: $('carmPass').value})
      });
      $('authMessage').textContent = result.message || (result.ok ? 'Guardado.' : 'No se pudo guardar.');
      $('saveAuthBtn').disabled = false;
      if (result.ok) {
        $('carmPass').value = '';
        setAuthLocked(false);
        await refresh();
      }
    };
    $('settingsBtn').onclick = () => toggleSettings(true);
    $('closeSettingsBtn').onclick = () => toggleSettings(false);
    $('cancelSettingsBtn').onclick = () => toggleSettings(false);
    $('authModal').onclick = (event) => {
      if (event.target === $('authModal') && !authState.configured) {
        $('authMessage').textContent = 'Debes verificar CARM antes de entrar al panel.';
      }
    };
    $('settingsModal').onclick = (event) => {
      if (event.target === $('settingsModal')) toggleSettings(false);
    };
    $('pickPendientesBtn').onclick = () => pickDirectory('pendientesDir');
    $('pickTemporalBtn').onclick = () => pickDirectory('temporalDir');
    $('saveFoldersBtn').onclick = saveFolders;
    $('saveCourseBtn').onclick = () => saveCourse();
    $('saveAutomationBtn').onclick = saveAutomation;
    $('useDetectedCourseBtn').onclick = () => {
      if (!$('detectedCourse').value) return;
      saveCourse($('detectedCourse').value);
    };
    $('detectedCourse').onchange = () => {
      if ($('detectedCourse').value) $('courseUrl').value = $('detectedCourse').value;
    };
    $('advancedAction').onchange = updateAdvancedForm;
    $('runAdvancedBtn').onclick = () => {
      const action = $('advancedAction').value;
      if (action === 'delete_cache' && !confirm('Borrar la cache local del curso?')) return;
      toggleSettings(false);
      run(action, {
        unidad: $('advancedUnidad').value,
        actividad: $('advancedActividad').value,
        max_entregas: $('advancedMaxEntregas').value,
        contexto_unidad: $('contextPath').value,
        actividad_codigo: $('localActivity').value,
        json_path: $('importJsonPath').value
      });
    };
    $('publishCheck').onchange = safeRefresh;
    $('prepareMode').onchange = updateActivityOptions;
    $('unidad').onchange = updateActivityOptions;
    $('advancedUnidad').onchange = updateAdvancedActivityOptions;
    updateAdvancedForm();
    setInterval(safeRefresh, 3000);
    safeRefresh();
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            data = HTML.replace("__LOCAL_API_TOKEN__", API_TOKEN).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if parsed.path.startswith("/api/") and not require_api_token(self):
            return
        if parsed.path == "/api/auth":
            send_json(self, auth_status())
            return
        if not carm_credentials_present():
            if parsed.path == "/api/status":
                send_json(self, {"running": False, "auth_required": True, "lines": ["Configura credenciales CARM para usar el panel."]})
                return
            send_json(self, {"ok": False, "auth_required": True, "message": "Credenciales CARM requeridas."}, HTTPStatus.UNAUTHORIZED)
            return
        if parsed.path == "/api/status":
            send_json(self, RUNNER.snapshot())
            return
        if parsed.path == "/api/state":
            send_json(self, project_state())
            return
        if parsed.path == "/api/options":
            send_json(self, course_options())
            return
        send_json(self, {"error": "not_found"}, 404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not require_api_token(self):
            return
        if parsed.path == "/api/auth/save":
            try:
                body = read_json_body(self)
                ok, message = save_carm_credentials(
                    str(body.get("usuario") or ""),
                    str(body.get("contrasena") or ""),
                )
                audit_ui_event("guardar_credenciales_carm", "ok" if ok else "error", usuario=body.get("usuario", ""))
                send_json(self, {"ok": ok, "message": message}, 200 if ok else 400)
            except Exception as exc:
                audit_ui_event("guardar_credenciales_carm", "error", error=exc)
                send_json(self, {"ok": False, "message": str(exc)}, 400)
            return
        if not carm_credentials_present() and parsed.path != "/api/auth/logout":
            send_json(self, {"ok": False, "auth_required": True, "message": "Credenciales CARM requeridas."}, HTTPStatus.UNAUTHORIZED)
            return
        if parsed.path == "/api/stop":
            audit_ui_event("detener_tarea", action=RUNNER.action)
            send_json(self, {"ok": RUNNER.stop()})
            return
        if parsed.path == "/api/auth/logout":
            RUNNER.stop()
            logout_carm()
            audit_ui_event("cerrar_sesion_carm")
            send_json(self, {"ok": True, "message": "Sesion CARM cerrada. Vuelve a introducir credenciales."})
            return
        if parsed.path == "/api/pick-directory":
            try:
                body = read_json_body(self)
                path = choose_directory(str(body.get("initial_dir") or ""))
                send_json(self, {"ok": True, "path": path})
            except Exception as exc:
                send_json(self, {"ok": False, "message": str(exc)}, 400)
            return
        if parsed.path == "/api/config/folders":
            try:
                body = read_json_body(self)
                configure_work_dirs(
                    pendientes=str(body.get("pendientes_dir") or ""),
                    temporal=str(body.get("temporal_dir") or ""),
                    persist=True,
                )
                audit_ui_event("configurar_carpetas", pendientes_dir=PENDIENTES_DIR, temporal_dir=TEMPORAL_DIR)
                send_json(
                    self,
                    {
                        "ok": True,
                        "message": "Carpetas guardadas y creadas si no existian.",
                        "pendientes_dir": str(PENDIENTES_DIR),
                        "temporal_dir": str(TEMPORAL_DIR),
                    },
                )
            except Exception as exc:
                send_json(self, {"ok": False, "message": str(exc)}, 400)
            return
        if parsed.path == "/api/config/course":
            try:
                body = read_json_body(self)
                url = save_course_url(str(body.get("course") or ""))
                audit_ui_event("configurar_curso", course_id=course_id_from_url(url))
                send_json(
                    self,
                    {
                        "ok": True,
                        "message": f"Curso activo guardado: {course_id_from_url(url)}. Actualiza datos didacticos para cargar sus unidades.",
                        "course_url": url,
                    },
                )
            except Exception as exc:
                send_json(self, {"ok": False, "message": str(exc)}, 400)
            return
        if parsed.path == "/api/config/automation":
            try:
                body = read_json_body(self)
                interval = save_automation_config(body.get("auto_scan_interval_minutes", DEFAULT_SCAN_INTERVAL_MINUTES))
                message = (
                    "Autodeteccion periodica desactivada."
                    if interval == 0
                    else f"Autodeteccion guardada: cada {interval} minutos."
                )
                audit_ui_event("configurar_autoescaneo", intervalo_minutos=interval)
                send_json(self, {"ok": True, "message": message, "auto_scan_interval_minutes": interval})
            except Exception as exc:
                send_json(self, {"ok": False, "message": str(exc)}, 400)
            return
        if parsed.path != "/api/run":
            send_json(self, {"error": "not_found"}, 404)
            return

        try:
            body = read_json_body(self)
            action = str(body.get("action", ""))
            args = build_args(action, body)
            ok, message = RUNNER.start(action, args)
            audit_ui_event("ejecutar_accion", "iniciada" if ok else "rechazada", action=action)
            send_json(self, {"ok": ok, "message": message})
        except Exception as exc:
            audit_ui_event("ejecutar_accion", "error", error=exc)
            send_json(self, {"ok": False, "message": str(exc)}, 400)

    def log_message(self, fmt: str, *args) -> None:
        return


def build_args(action: str, body: dict) -> list[str]:
    if action == "prepare":
        modo = str(body.get("modo") or "unit").strip()
        unidad = str(body.get("unidad") or "ud01").strip()
        actividad = str(body.get("actividad") or "").strip()
        max_entregas = str(body.get("max_entregas") or "6").strip()
        require_allowed(max_entregas, ALLOWED_MAX_ENTREGAS, "Entregas por prompt")
        args = [
            "--flujo-correccion-carm",
            "--pendientes",
            str(PENDIENTES_DIR),
            "--temporal",
            str(TEMPORAL_DIR),
            "--max-entregas-por-prompt",
            max_entregas,
        ]
        if modo == "activity":
            require_allowed(actividad, allowed_activities(), "Actividad")
            args.extend(["--actividad", actividad])
            return args
        require_allowed(unidad, allowed_units(), "Unidad")
        args.extend(["--unidad", unidad])
        return args

    if action in {"preview", "publish", "assist_publish"}:
        json_path = require_allowed(str(body.get("json_path") or COMBINED_JSON), allowed_json_paths(), "JSON")
        args = ["--subir-correcciones-carm", str(json_path)]
        if action == "publish":
            revisar_publicacion_segura()
            args.append("--publicar-carm")
        if action == "assist_publish":
            revisar_publicacion_segura()
            args.append("--subida-asistida-carm")
        return args

    if action == "diagnose":
        return ["--diagnosticar-carm"]

    if action == "diagnose_evidence":
        return ["--diagnosticar-carm", "--guardar-evidencias"]

    if action == "detect_course":
        return ["--cachear-curso", "--refrescar-cache"]

    if action == "check_playwright":
        return ["--comprobar-login-carm"]

    if action in {"list_carm", "cache_course", "prepare_carm_codex"}:
        unidad = str(body.get("unidad") or "ud01").strip()
        max_entregas = str(body.get("max_entregas") or "6").strip()
        require_allowed(unidad, allowed_units(), "Unidad")
        require_allowed(max_entregas, ALLOWED_MAX_ENTREGAS, "Entregas por prompt")
        if action == "list_carm":
            return ["--solo-listar-carm", "--unidad", unidad]
        if action == "cache_course":
            return ["--cachear-curso", "--unidad", unidad]
        return [
            "--preparar-carm-codex",
            "--pendientes",
            str(PENDIENTES_DIR),
            "--temporal",
            str(TEMPORAL_DIR),
            "--unidad",
            unidad,
            "--max-entregas-por-prompt",
            max_entregas,
        ]

    if action == "prepare_carm_codex_activity":
        actividad = str(body.get("actividad") or "").strip()
        max_entregas = str(body.get("max_entregas") or "6").strip()
        require_allowed(actividad, allowed_activities(), "Actividad")
        require_allowed(max_entregas, ALLOWED_MAX_ENTREGAS, "Entregas por prompt")
        return [
            "--preparar-carm-codex",
            "--pendientes",
            str(PENDIENTES_DIR),
            "--temporal",
            str(TEMPORAL_DIR),
            "--actividad",
            actividad,
            "--max-entregas-por-prompt",
            max_entregas,
        ]

    if action == "prepare_local_prompts":
        contexto = str(body.get("contexto_unidad") or "").strip()
        actividad = str(body.get("actividad_codigo") or "").strip()
        require_allowed(contexto, ALLOWED_CONTEXT_PATHS, "Archivo de contexto")
        args = [
            "--pendientes",
            str(PENDIENTES_DIR),
            "--temporal",
            str(TEMPORAL_DIR),
            "--contexto-unidad",
            contexto,
            "--preparar-prompts-codex",
        ]
        if actividad:
            require_allowed(actividad, allowed_activities(), "Actividad")
            args.extend(["--actividad-codigo", actividad])
        return args

    if action == "import_codex":
        json_path = str(body.get("json_path") or "").strip()
        require_allowed(json_path, allowed_json_paths(), "JSON")
        return ["--temporal", str(TEMPORAL_DIR), "--importar-correcciones-codex", json_path]

    if action == "delete_cache":
        return ["--borrar-cache-curso"]

    raise ValueError("Accion no permitida.")


def startup_cmd_path() -> Path:
    appdata = os.getenv("APPDATA")
    if not appdata:
        raise RuntimeError("No se pudo localizar APPDATA para la carpeta de inicio.")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Corrector CARM.cmd"


def install_startup() -> Path:
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    runner = pythonw if pythonw.exists() else Path(sys.executable)
    cmd_path = startup_cmd_path()
    cmd_path.parent.mkdir(parents=True, exist_ok=True)
    cmd_path.write_text(
        "@echo off\n"
        f'cd /d "{ROOT}"\n'
        f'start "" "{runner}" "{ROOT / "interfaz_app.py"}" --tray --auto-correct --host {DEFAULT_HOST} --port {DEFAULT_PORT} --no-browser\n',
        encoding="utf-8",
    )
    return cmd_path


def uninstall_startup() -> bool:
    path = startup_cmd_path()
    if path.exists():
        path.unlink()
        return True
    return False


def tray_image():
    if Image is None or ImageDraw is None:
        return None
    img = Image.new("RGB", (64, 64), "#1f7a5b")
    draw = ImageDraw.Draw(img)
    draw.rectangle((10, 10, 54, 54), outline="#ffffff", width=4)
    draw.text((21, 20), "C", fill="#ffffff")
    return img


def run_tray(server: ThreadingHTTPServer, url: str, startup_scan: bool) -> None:
    global TRAY_ICON
    if pystray is None:
        print("pystray/Pillow no estan instalados; la interfaz queda en segundo plano sin icono de bandeja.")
        if startup_scan and carm_credentials_present():
            RUNNER.start("detect_course", ["--cachear-curso", "--refrescar-cache"])
        server.serve_forever()
        return

    def open_ui(icon=None, item=None) -> None:
        webbrowser.open(url)

    def quit_app(icon, item=None) -> None:
        server.shutdown()
        icon.stop()

    icon = pystray.Icon(
        "Corrector CARM",
        tray_image(),
        "Corrector CARM",
        menu=pystray.Menu(
            pystray.MenuItem("Abrir interfaz", open_ui, default=True),
            pystray.MenuItem("Cerrar programa", quit_app),
        ),
    )
    TRAY_ICON = icon
    threading.Thread(target=server.serve_forever, daemon=True).start()
    notify_pending_publication()
    if startup_scan and carm_credentials_present():
        RUNNER.start("detect_course", ["--cachear-curso", "--refrescar-cache"])
    elif startup_scan:
        notify("Corrector CARM", "Faltan credenciales CARM. Abre la interfaz para configurarlas.")
    icon.run()


def start_periodic_scan(disabled: bool) -> None:
    if disabled:
        return

    def loop() -> None:
        while True:
            interval = auto_scan_interval_minutes()
            if interval <= 0:
                time.sleep(60)
                continue
            time.sleep(max(60, interval * 60))
            if not carm_credentials_present():
                continue
            snapshot = RUNNER.snapshot()
            if snapshot.get("running"):
                continue
            ok, _ = RUNNER.start("detect_course", ["--cachear-curso", "--refrescar-cache"])
            if ok:
                notify("Corrector CARM", "Autodeteccion periodica de CARM iniciada.")

    threading.Thread(target=loop, daemon=True).start()


def main() -> None:
    parser = argparse.ArgumentParser(description="Interfaz web local del corrector CARM.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--tray", action="store_true", help="Ejecuta la app en la bandeja del sistema.")
    parser.add_argument(
        "--auto-correct",
        action="store_true",
        help="Tras revisar CARM al inicio, prepara correcciones automaticamente.",
    )
    parser.add_argument(
        "--no-auto-correct",
        action="store_true",
        help="No lanza correccion automatica tras el escaneo inicial.",
    )
    parser.add_argument("--install-startup", action="store_true", help="Instala el arranque automatico de Windows.")
    parser.add_argument("--uninstall-startup", action="store_true", help="Elimina el arranque automatico de Windows.")
    parser.add_argument(
        "--no-startup-scan",
        action="store_true",
        help="No revisa CARM al iniciar para actualizar unidades y casos practicos.",
    )
    parser.add_argument(
        "--no-periodic-scan",
        action="store_true",
        help="No ejecuta autodeteccion periodica de CARM.",
    )
    args = parser.parse_args()
    global AUTO_CORRECT_AFTER_SCAN
    AUTO_CORRECT_AFTER_SCAN = (args.tray or args.auto_correct) and not args.no_auto_correct

    if args.install_startup:
        path = install_startup()
        print(f"Arranque automatico instalado: {path}")
        return
    if args.uninstall_startup:
        removed = uninstall_startup()
        print("Arranque automatico eliminado." if removed else "No habia arranque automatico instalado.")
        return

    try:
        server, active_port, attempted_ports = create_local_server(args.host, args.port)
    except OSError as exc:
        print(f"No se pudo iniciar la interfaz local: {exc}")
        print("Cierra otra instancia del Corrector CARM o prueba con --port 0 para usar un puerto libre automatico.")
        return
    url_host = "127.0.0.1" if args.host in {"0.0.0.0", "::"} else args.host
    url = f"http://{url_host}:{active_port}"
    save_app_config({"last_local_url": url, "last_local_port": active_port})
    print(f"Interfaz Corrector CARM: {url}")
    if args.port and active_port != args.port:
        print(f"Puerto {args.port} ocupado; se ha usado automaticamente el puerto {active_port}.")
    notify_pending_publication()
    start_periodic_scan(disabled=args.no_periodic_scan)
    if args.tray:
        if not args.no_browser:
            threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        run_tray(server, url, startup_scan=not args.no_startup_scan)
        return
    if not args.no_startup_scan and carm_credentials_present():
        ok, message = RUNNER.start("detect_course", ["--cachear-curso", "--refrescar-cache"])
        print(f"Revision inicial CARM: {message if ok else 'omitida'}")
    elif not args.no_startup_scan:
        print("Revision inicial CARM omitida: faltan credenciales.")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
