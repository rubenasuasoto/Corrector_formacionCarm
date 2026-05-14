from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
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
from datetime import datetime
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
VERSION_PATH = ROOT / "VERSION"
DEFAULT_PENDIENTES_DIR = Path(r"C:\temp\vscodec\pendientes")
DEFAULT_TEMPORAL_DIR = Path(r"C:\temp\vscodec\temporal")
DEFAULT_COURSES_DIR = Path(r"C:\temp\vscodec\cursos")
BASE_PENDIENTES_DIR = DEFAULT_PENDIENTES_DIR
BASE_TEMPORAL_DIR = DEFAULT_TEMPORAL_DIR
PENDIENTES_DIR = DEFAULT_PENDIENTES_DIR
TEMPORAL_DIR = DEFAULT_TEMPORAL_DIR
PROMPTS_DIR = PENDIENTES_DIR / "prompts_codex"
COMBINED_JSON = PROMPTS_DIR / "correcciones_codex_combinadas.json"
REVISION_CSV = TEMPORAL_DIR / "revision_pendiente.csv"
AGENTE_LOG = ROOT / "logs_correcciones" / "agente.log"
AUDIT_LOG = ROOT / "respuestas_extraidas" / "auditoria.jsonl"
SUBIDA_ASISTIDA_JSON = ROOT / "respuestas_extraidas" / "subida_carm_asistida.json"
CURSOS_DETECTADOS_JSON = ROOT / "respuestas_extraidas" / "cursos_detectados.json"
ENV_PATH = ROOT / ".env"
CARM_STORAGE_STATE = ROOT / "cache_carm" / "carm_storage_state.json"
ALLOWED_UNITS = {f"ud{i:02d}" for i in range(1, 16)}
ALLOWED_MAX_ENTREGAS = {"0", *{str(i) for i in range(1, 21)}}
ALLOWED_ACTIVITIES = {f"ud{unit:02d}cp{case:02d}" for unit in range(1, 16) for case in range(1, 16)}
UNIT_RE = re.compile(r"^ud\d{2}$")
ACTIVITY_RE = re.compile(r"^ud\d{2}cp\d{2}$")
COURSE_URL_RE = re.compile(r"^https://formacion\.carm\.es/course/view\.php\?id=\d+$")
DASHBOARD_URL_RE = re.compile(r"^https://formacion\.carm\.es/(?:course/my|my)/index\.php$")
DEFAULT_CARM_DASHBOARD_URL = "https://formacion.carm.es/my/index.php"
DEFAULT_CARM_COURSE_URL = ""
TRAY_ICON = None
APP_SERVER: ThreadingHTTPServer | None = None
APP_URL = ""
AUTO_CORRECT_AFTER_SCAN = False
AUTO_CORRECT_ARGS = ["--preparar-carm-codex"]
AUTO_COURSE_QUEUE: list[dict[str, str]] = []
DEFAULT_SCAN_INTERVAL_MINUTES = 60
DEFAULT_AUTO_PREPARE_INTERVAL_MINUTES = 0
API_TOKEN = secrets.token_urlsafe(32)
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
PORT_FALLBACK_ATTEMPTS = 30
RELEASE_CACHE_TTL_SECONDS = 30
_RELEASE_CACHE: dict | None = None
_RELEASE_CACHE_AT = 0.0


def hidden_subprocess_kwargs() -> dict:
    if os.name != "nt":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


def app_version() -> str:
    try:
        value = VERSION_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        value = ""
    return value or "0.0.0-local"


def git_revision() -> dict:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            **hidden_subprocess_kwargs(),
        ).stdout.strip()
        dirty_proc = subprocess.run(
            ["git", "status", "--short"],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            **hidden_subprocess_kwargs(),
        )
        return {"commit": commit or "sin-git", "dirty": bool(dirty_proc.stdout.strip())}
    except Exception:
        return {"commit": "sin-git", "dirty": False}


def release_info() -> dict:
    global _RELEASE_CACHE, _RELEASE_CACHE_AT
    now = time.time()
    if _RELEASE_CACHE is not None and now - _RELEASE_CACHE_AT < RELEASE_CACHE_TTL_SECONDS:
        return dict(_RELEASE_CACHE)
    git = git_revision()
    info = {
        "version": app_version(),
        "commit": git["commit"],
        "dirty": git["dirty"],
    }
    _RELEASE_CACHE = dict(info)
    _RELEASE_CACHE_AT = now
    return info


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


def carm_account_ref(usuario: str | None = None) -> str:
    usuario = (usuario if usuario is not None else read_env_values().get("CARM_USUARIO", "")).strip().lower()
    if not usuario:
        return ""
    return hashlib.sha256(usuario.encode("utf-8", errors="ignore")).hexdigest()[:12]


def account_context_matches_current_user() -> bool:
    stored = str(load_app_config().get("carm_account_ref") or "").strip()
    current = carm_account_ref()
    return not stored or not current or stored == current


def auto_scan_interval_minutes() -> int:
    config = load_app_config()
    try:
        value = int(config.get("auto_scan_interval_minutes", DEFAULT_SCAN_INTERVAL_MINUTES))
    except (TypeError, ValueError):
        value = DEFAULT_SCAN_INTERVAL_MINUTES
    return max(0, min(value, 1440))


def periodic_auto_prepare_enabled() -> bool:
    return bool(load_app_config().get("periodic_auto_prepare", False))


def auto_prepare_interval_minutes() -> int:
    config = load_app_config()
    try:
        value = int(config.get("auto_prepare_interval_minutes", DEFAULT_AUTO_PREPARE_INTERVAL_MINUTES))
    except (TypeError, ValueError):
        value = DEFAULT_AUTO_PREPARE_INTERVAL_MINUTES
    return max(0, min(value, 10080))


def auto_prepare_time_of_day() -> str:
    value = str(load_app_config().get("auto_prepare_time", "") or "").strip()
    if not re.fullmatch(r"(:[01]\d|2[0-3]):[0-5]\d", value):
        return ""
    return value


def auto_prepare_due(now: datetime | None = None) -> str:
    if not periodic_auto_prepare_enabled():
        return ""
    now = now or datetime.now()
    config = load_app_config()
    exact_time = auto_prepare_time_of_day()
    if exact_time:
        hour, minute = [int(part) for part in exact_time.split(":", 1)]
        current_minutes = now.hour * 60 + now.minute
        scheduled_minutes = hour * 60 + minute
        if str(config.get("auto_prepare_last_exact_date") or "") != now.date().isoformat():
            if current_minutes >= scheduled_minutes:
                return f"hora exacta {exact_time}"

    interval = auto_prepare_interval_minutes()
    if interval > 0:
        try:
            last_run = float(config.get("auto_prepare_last_run_at") or 0)
        except (TypeError, ValueError):
            last_run = 0.0
        if last_run <= 0 or time.time() - last_run >= interval * 60:
            return f"intervalo {interval} min"
    return ""


def mark_auto_prepare_run(reason: str) -> None:
    updates = {"auto_prepare_last_run_at": time.time()}
    if reason.startswith("hora exacta"):
        updates["auto_prepare_last_exact_date"] = datetime.now().date().isoformat()
    save_app_config(updates)


def _normalize_dir(path: str | Path, fallback: Path) -> Path:
    raw = str(path or "").strip()
    if not raw:
        return fallback
    return Path(raw).expanduser()


def course_scoped_dirs_enabled() -> bool:
    return bool(load_app_config().get("course_scoped_dirs", True))


def active_course_id() -> str:
    return course_id_from_url(current_course_url())


def _course_safe_id(course_id: str) -> str:
    return course_id if str(course_id or "").isdigit() else "sin_curso"


def _apply_course_scope(base_pendientes: Path, base_temporal: Path) -> tuple[Path, Path]:
    if not course_scoped_dirs_enabled():
        return base_pendientes, base_temporal
    active_id = active_course_id()
    if not active_id:
        return base_pendientes, base_temporal
    course_id = _course_safe_id(active_id)
    course_root = DEFAULT_COURSES_DIR / course_id
    return course_root / "pendientes", course_root / "temporal"


def course_work_dirs(course_id: str) -> tuple[Path, Path]:
    if not str(course_id or "").strip():
        return BASE_PENDIENTES_DIR, BASE_TEMPORAL_DIR
    course_id = _course_safe_id(course_id)
    if course_scoped_dirs_enabled():
        course_root = DEFAULT_COURSES_DIR / course_id
        return course_root / "pendientes", course_root / "temporal"
    return BASE_PENDIENTES_DIR, BASE_TEMPORAL_DIR


def ensure_work_dirs() -> None:
    for path in (
        BASE_PENDIENTES_DIR,
        BASE_TEMPORAL_DIR,
        DEFAULT_COURSES_DIR,
        PENDIENTES_DIR,
        TEMPORAL_DIR,
        PROMPTS_DIR,
        ROOT / "cache_carm",
        ROOT / "logs_correcciones",
    ):
        try:
            path.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            continue


def configure_work_dirs(pendientes: str | Path | None = None, temporal: str | Path | None = None, persist: bool = False) -> None:
    global BASE_PENDIENTES_DIR, BASE_TEMPORAL_DIR, PENDIENTES_DIR, TEMPORAL_DIR, PROMPTS_DIR, COMBINED_JSON, REVISION_CSV
    current = load_app_config()
    BASE_PENDIENTES_DIR = _normalize_dir(pendientes or current.get("pendientes_dir"), DEFAULT_PENDIENTES_DIR)
    BASE_TEMPORAL_DIR = _normalize_dir(temporal or current.get("temporal_dir"), DEFAULT_TEMPORAL_DIR)
    PENDIENTES_DIR, TEMPORAL_DIR = _apply_course_scope(BASE_PENDIENTES_DIR, BASE_TEMPORAL_DIR)
    PROMPTS_DIR = PENDIENTES_DIR / "prompts_codex"
    COMBINED_JSON = PROMPTS_DIR / "correcciones_codex_combinadas.json"
    REVISION_CSV = TEMPORAL_DIR / "revision_pendiente.csv"
    ensure_work_dirs()
    if persist:
        save_app_config({"pendientes_dir": str(BASE_PENDIENTES_DIR), "temporal_dir": str(BASE_TEMPORAL_DIR)})


def save_automation_config(
    interval_minutes: str | int,
    periodic_auto_prepare: bool | None = None,
    auto_prepare_interval: str | int | None = None,
    auto_prepare_time: str | None = None,
) -> int:
    try:
        interval = int(interval_minutes)
    except (TypeError, ValueError):
        raise ValueError("El intervalo debe ser un numero de minutos.")
    if interval < 0 or interval > 1440:
        raise ValueError("El intervalo debe estar entre 0 y 1440 minutos. Usa 0 para desactivar.")
    updates = {"auto_scan_interval_minutes": interval}
    if periodic_auto_prepare is not None:
        updates["periodic_auto_prepare"] = bool(periodic_auto_prepare)
    if auto_prepare_interval is not None:
        try:
            prepare_interval = int(auto_prepare_interval)
        except (TypeError, ValueError):
            raise ValueError("El intervalo de autoprompt debe ser un numero de minutos.")
        if prepare_interval < 0 or prepare_interval > 10080:
            raise ValueError("El intervalo de autoprompt debe estar entre 0 y 10080 minutos. Usa 0 para desactivar.")
        updates["auto_prepare_interval_minutes"] = prepare_interval
    if auto_prepare_time is not None:
        prepare_time = str(auto_prepare_time or "").strip()
        if prepare_time and not re.fullmatch(r"(:[01]\d|2[0-3]):[0-5]\d", prepare_time):
            raise ValueError("La hora exacta debe tener formato HH:MM.")
        updates["auto_prepare_time"] = prepare_time
    save_app_config(updates)
    return interval


def correction_source_options() -> list[dict]:
    paths = [REVISION_CSV]
    if PROMPTS_DIR.exists():
        json_pendientes = sorted(PROMPTS_DIR.glob("*_correccion.json"))
        if json_pendientes:
            paths.append(PROMPTS_DIR)
        if COMBINED_JSON.exists():
            paths.append(COMBINED_JSON)
        paths.extend(json_pendientes)
        corrections_dir = PROMPTS_DIR / "correcciones_codex"
        if corrections_dir.exists():
            paths.extend(sorted(corrections_dir.glob("*_correccion.json")))
    seen: set[str] = set()
    options: list[dict] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path == PROMPTS_DIR:
            count = len(list(PROMPTS_DIR.glob("*_correccion.json")))
            label = f"Todos los JSON pendientes ({count})"
        else:
            label = path.name
        options.append({"path": key, "label": label, "exists": path.exists(), "is_dir": path.is_dir()})
    return options


def json_options() -> list[dict]:
    return correction_source_options()


def allowed_json_paths() -> set[str]:
    allowed = {item["path"] for item in correction_source_options()}
    allowed.add(str(REVISION_CSV))
    allowed.add(str(COMBINED_JSON))
    allowed.update(
        str(PROMPTS_DIR / name)
        for name in (
            "prompt_ud01cp01_correccion.json",
            "prompt_ud01cp02_correccion.json",
            "prompt_ud02cp03_correccion.json",
        )
    )
    allowed.update(
        str(PROMPTS_DIR / "correcciones_codex" / name)
        for name in (
            "prompt_ud01cp01_correccion.json",
            "prompt_ud01cp02_correccion.json",
            "prompt_ud02cp03_correccion.json",
        )
    )
    return allowed


def default_correction_source_path() -> Path:
    if REVISION_CSV.exists():
        return REVISION_CSV
    if PROMPTS_DIR.exists():
        for path in sorted(PROMPTS_DIR.glob("*_correccion.json")):
            return path
    return REVISION_CSV

def redact_text(text: object) -> str:
    value = str(text or "")
    value = re.sub(r"[\w.\-+%]+@[\w.\-]+\.[A-Za-z]{2,}", "[email-redactado]", value)
    value = re.sub(r"(sesskey=)[^&\"'>\s]+", r"\1[redactado]", value, flags=re.I)
    value = re.sub(r"(password|contrasena|contraseña|api[_-]key|token|authorization|cookie)(\s*[=:]\s*)[^&\"'>\s]+", r"\1\2[redactado]", value, flags=re.I)
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


def interface_url(fragment: str = "") -> str:
    base = APP_URL or load_app_config().get("last_local_url", "")
    if not base:
        return ""
    fragment = str(fragment or "").strip()
    if fragment and not fragment.startswith("#"):
        fragment = f"#{fragment}"
    return f"{base}{fragment}"


def notify(title: str, message: str, target: str = "") -> None:
    text = message[:240]
    url = interface_url(target)
    try:
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "Add-Type -AssemblyName System.Drawing; "
            "$n=New-Object System.Windows.Forms.NotifyIcon; "
            "$n.Icon=[System.Drawing.SystemIcons]::Information; "
            "$n.Visible=$true; "
        )
        if url:
            script += (
                f"$url={json.dumps(url)}; "
                "$open={ Start-Process $url }; "
                "$n.add_BalloonTipClicked($open); "
                "$n.add_Click($open); "
            )
        script += (
            f"$n.ShowBalloonTip(9000, {json.dumps(title)}, {json.dumps(text)}, 'Info'); "
            "Start-Sleep -Seconds 10; $n.Dispose()"
        )
        subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-WindowStyle",
                "Hidden",
                "-Command",
                script,
            ],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **hidden_subprocess_kwargs(),
        )
        return
    except Exception:
        pass
    if TRAY_ICON is not None:
        try:
            TRAY_ICON.notify(text, title)
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


PLACEHOLDER_ENV_VALUES = {
    "",
    "tu_usuario_carm",
    "tu_contrasena_carm",
    "usuario",
    "contrasena",
    "contraseña",
    "password",
    "changeme",
    "cambiar",
    "none",
    "null",
}


def is_real_env_value(value: str | None, *, secret: bool = False) -> bool:
    clean = str(value or "").strip()
    if not clean:
        return False
    lowered = clean.lower()
    if lowered in PLACEHOLDER_ENV_VALUES:
        return False
    if lowered.startswith("tu_") or lowered.startswith("your_"):
        return False
    if secret and lowered in {"***", "*****", "sk-...", "tu_api_key_aqui"}:
        return False
    return True


def is_useful_didactic_context(value: str | None) -> bool:
    clean = str(value or "").strip()
    if len(clean) < 400:
        return False
    normalized = re.sub(r"\s+", " ", clean.lower())
    fallbacks = (
        "no hay contexto didactico limpio suficiente en cache",
        "no hay contexto didáctico limpio suficiente en cache",
        "no hay contexto didactico limpio disponible en cache",
        "la cache contiene una pagina indice de moodle",
    )
    return not any(fallback in normalized for fallback in fallbacks)


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
    return is_real_env_value(env.get("CARM_USUARIO")) and is_real_env_value(env.get("CARM_CONTRASENA"), secret=True)


def openai_api_key_present() -> bool:
    api_key = read_env_values().get("OPENAI_API_KEY", "").strip()
    return is_real_env_value(api_key, secret=True)


def correction_mode() -> str:
    env = read_env_values()
    raw = env.get("CORRECTION_MODE", "").strip().lower()
    if raw in {"api", "prompt"}:
        return raw
    return "api" if openai_api_key_present() else "prompt"


def auth_status() -> dict:
    return {
        "configured": carm_credentials_present(),
        "session_saved": CARM_STORAGE_STATE.exists(),
        "openai_api_configured": openai_api_key_present(),
        "correction_mode": correction_mode(),
        "openai_model": read_env_values().get("OPENAI_MODEL", "gpt-5-mini") or "gpt-5-mini",
    }


def _check_module(label: str, module_name: str, required: bool = True) -> dict:
    found = importlib.util.find_spec(module_name) is not None
    return {
        "name": label,
        "ok": found or not required,
        "required": required,
        "message": "Disponible." if found else ("Falta dependencia obligatoria." if required else "No instalada; solo afecta a lectura avanzada."),
    }


def _check_chromium_installed() -> dict:
    ms_playwright = Path(os.getenv("LOCALAPPDATA", "")) / "ms-playwright"
    local_chromiums = sorted(ms_playwright.glob("chromium-*")) if ms_playwright.exists() else []
    local_chromiums = [path for path in local_chromiums if path.is_dir() and "headless" not in path.name.lower()]
    if local_chromiums:
        return {
            "name": "Chromium de Playwright",
            "ok": True,
            "required": True,
            "message": str(local_chromiums[-1]),
        }
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "--dry-run", "chromium"],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            **hidden_subprocess_kwargs(),
        )
        locations: list[Path] = []
        for line in proc.stdout.splitlines():
            if "Install location:" not in line:
                continue
            raw = line.split("Install location:", 1)[1].strip()
            if raw:
                locations.append(Path(raw))
        installed = any(path.exists() for path in locations)
        return {
            "name": "Chromium de Playwright",
            "ok": proc.returncode == 0 and installed,
            "required": True,
            "message": str(next((path for path in locations if path.exists()), "")) if installed else "Ejecuta: playwright install chromium",
        }
    except Exception as exc:
        return {
            "name": "Chromium de Playwright",
            "ok": False,
            "required": True,
            "message": f"No se pudo comprobar Chromium: {exc}",
        }


def _check_app_python_env() -> dict:
    expected = ROOT / ".venv" / "Scripts"
    current = Path(sys.executable).resolve()
    try:
        inside_venv = expected.resolve() in current.parents or current.parent.resolve() == expected.resolve()
    except Exception:
        inside_venv = False
    return {
        "name": "Python de la app",
        "ok": inside_venv,
        "required": True,
        "message": str(current) if inside_venv else f"Arrancado con {current}. Reinicia con iniciar_app_windows.cmd para usar .venv.",
    }


def _check_playwright_lock() -> dict:
    lock_path = Path(os.getenv("LOCALAPPDATA", "")) / "ms-playwright" / "__dirlock"
    exists = lock_path.exists()
    return {
        "name": "Lock de Playwright",
        "ok": not exists,
        "required": False,
        "message": (
            f"Detectado {lock_path}. Si hay fallos de instalacion, ejecuta reparar_dependencias_windows.cmd -LimpiarPlaywrightLock."
            if exists
            else "No detectado."
        ),
    }


def _check_git_sensitive_index() -> dict:
    try:
        repo_proc = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            **hidden_subprocess_kwargs(),
        )
        if repo_proc.returncode != 0:
            return {
                "name": "Git sin artefactos sensibles",
                "ok": True,
                "required": True,
                "message": "No hay repositorio Git en esta instalacion; comprobacion omitida.",
            }

        proc = subprocess.run(
            ["git", "ls-files", ".env", "logs_correcciones", "correcciones_validadas", "respuestas_extraidas", "cache_carm"],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            **hidden_subprocess_kwargs(),
        )
        tracked = [line for line in proc.stdout.splitlines() if line.strip()]
        ok = proc.returncode == 0 and not tracked
        return {
            "name": "Git sin artefactos sensibles",
            "ok": ok,
            "required": True,
            "message": "Correcto." if ok else f"Hay {len(tracked)} archivo(s) sensible(s) versionados.",
        }
    except Exception as exc:
        return {
            "name": "Git sin artefactos sensibles",
            "ok": True,
            "required": True,
            "message": f"No se pudo comprobar Git en esta instalacion; comprobacion omitida: {exc}",
        }


def local_health_status() -> dict:
    checks = [
        _check_app_python_env(),
        _check_module("Playwright", "playwright"),
        _check_chromium_installed(),
        _check_playwright_lock(),
        _check_module("OpenAI SDK", "openai"),
        _check_module("python-dotenv", "dotenv"),
        _check_module("pystray", "pystray"),
        _check_module("Pillow", "PIL"),
        _check_module("pypdf", "pypdf", required=False),
        _check_module("python-pptx", "pptx", required=False),
        _check_module("openpyxl", "openpyxl", required=False),
        _check_module("pytesseract", "pytesseract", required=False),
        _check_git_sensitive_index(),
    ]
    checks.extend(
        [
            {
                "name": "Credenciales CARM",
                "ok": carm_credentials_present(),
                "required": True,
                "message": "Configuradas." if carm_credentials_present() else "Pendientes de configurar en la app.",
            },
            {
                "name": "Curso activo",
                "ok": bool(active_course_id()),
                "required": True,
                "message": f"Curso {active_course_id()}." if active_course_id() else "Selecciona o detecta un curso CARM.",
            },
            {
                "name": "Carpetas de trabajo",
                "ok": PENDIENTES_DIR.exists() and TEMPORAL_DIR.exists() and PROMPTS_DIR.exists(),
                "required": True,
                "message": f"{PENDIENTES_DIR} | {TEMPORAL_DIR}",
            },
        ]
    )
    required_ok = all(item["ok"] for item in checks if item.get("required"))
    optional_missing = sum(1 for item in checks if not item["ok"] and not item.get("required"))
    return {
        "ok": required_ok,
        "optional_missing": optional_missing,
        "checks": checks,
        "message": "Equipo listo para operar." if required_ok else "Hay puntos obligatorios pendientes.",
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
        **hidden_subprocess_kwargs(),
    )
    ok = proc.returncode == 0 and " - ERROR - " not in proc.stdout
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    return ok, lines[-1] if lines else ("Credenciales verificadas." if ok else "No se pudo verificar CARM.")


def save_carm_credentials(usuario: str, contrasena: str) -> tuple[bool, str]:
    usuario = usuario.strip()
    contrasena = contrasena.strip()
    if not usuario or not contrasena:
        return False, "Usuario y contrasena son obligatorios."
    previous_env_ref = carm_account_ref()
    previous_config_ref = str(load_app_config().get("carm_account_ref") or "").strip()
    new_ref = carm_account_ref(usuario)
    ok, message = verify_carm_credentials(usuario, contrasena)
    if not ok:
        if CARM_STORAGE_STATE.exists():
            CARM_STORAGE_STATE.unlink()
        return False, message
    account_changed = bool(new_ref and ((previous_config_ref and previous_config_ref != new_ref) or (previous_env_ref and previous_env_ref != new_ref)))
    write_env_values(
        {
            "CARM_USUARIO": usuario,
            "CARM_CONTRASENA": contrasena,
            "CARM_RECORDAR_CUENTA": "1",
            **({"CARM_COURSE_URL": ""} if account_changed else {}),
        }
    )
    if account_changed and CARM_STORAGE_STATE.exists():
        CARM_STORAGE_STATE.unlink()
    save_app_config(
        {
            "carm_account_ref": new_ref,
            **({"selected_course_ids": [], "active_course_id": ""} if account_changed else {}),
        }
    )
    configure_work_dirs()
    if account_changed:
        return True, "Credenciales CARM guardadas. Cuenta distinta detectada: selecciona de nuevo el curso para usar sus carpetas propias."
    return True, "Credenciales CARM guardadas y verificadas."


def save_openai_config(api_key: str, model: str, mode: str) -> tuple[bool, str]:
    mode = (mode or "prompt").strip().lower()
    if mode not in {"api", "prompt"}:
        return False, "Modo de correccion no valido."
    model = (model or "gpt-5-mini").strip() or "gpt-5-mini"
    current = read_env_values()
    api_key = (api_key or "").strip()
    updates: dict[str, str] = {
        "CORRECTION_MODE": mode,
        "OPENAI_MODEL": model,
    }
    if api_key:
        mode = "api"
        updates["CORRECTION_MODE"] = "api"
        updates["OPENAI_API_KEY"] = api_key
    if mode == "api":
        candidate = api_key or current.get("OPENAI_API_KEY", "")
        if not candidate or candidate.lower() in {"tu_api_key_aqui", "sk-...", "none", "null"}:
            return False, "Para modo API necesitas introducir OPENAI_API_KEY."
        ok, message = verify_openai_api(candidate, model)
        if not ok:
            return False, message
    write_env_values(updates)
    return True, "Configuracion OpenAI guardada." if mode == "api" else "Modo solo prompts guardado."


def verify_openai_api(api_key: str, model: str) -> tuple[bool, str]:
    api_key = (api_key or "").strip()
    model = (model or "gpt-5-mini").strip() or "gpt-5-mini"
    if not api_key or api_key.lower() in {"tu_api_key_aqui", "sk-...", "none", "null"}:
        return False, "Introduce una OPENAI_API_KEY real."
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Responde solo OK."},
                {"role": "user", "content": "OK"},
            ],
            max_completion_tokens=4,
        )
        return True, f"OpenAI API verificada correctamente con {model}."
    except Exception as exc:
        raw = str(exc)
        low = raw.lower()
        if "insufficient_quota" in low or "quota" in low or "billing" in low or "credit" in low:
            return False, "La API key parece valida, pero la cuenta no tiene saldo/cuota disponible o billing activo."
        if "invalid_api_key" in low or "incorrect api key" in low or "401" in low or "unauthorized" in low:
            return False, "OPENAI_API_KEY no es valida o no pertenece al proyecto correcto."
        if "model" in low and ("not found" in low or "does not exist" in low or "404" in low):
            return False, f"El modelo {model} no esta disponible para esta cuenta. Prueba gpt-5-mini."
        if "rate limit" in low or "429" in low:
            return False, "La API key funciona, pero ahora mismo hay limite de uso/rate limit. Espera o revisa Limits."
        return False, f"No se pudo verificar OpenAI API: {raw[:500]}"


def logout_carm() -> None:
    write_env_values({"CARM_USUARIO": "", "CARM_CONTRASENA": ""})
    if CARM_STORAGE_STATE.exists():
        CARM_STORAGE_STATE.unlink()


def current_course_url() -> str:
    if not account_context_matches_current_user():
        return ""
    value = (read_env_values().get("CARM_COURSE_URL") or "").strip()
    if COURSE_URL_RE.fullmatch(value):
        return value
    configured_active = str(load_app_config().get("active_course_id") or "").strip()
    if configured_active.isdigit():
        return course_url_from_id(configured_active)
    raw_selected = load_app_config().get("selected_course_ids", [])
    if isinstance(raw_selected, list):
        for item in raw_selected:
            course_id = str(item or "").strip()
            if course_id.isdigit():
                return course_url_from_id(course_id)
    return ""


def dashboard_url() -> str:
    env = read_env_values()
    configured = (env.get("CARM_DASHBOARD_URL") or "").strip()
    if DASHBOARD_URL_RE.fullmatch(configured):
        return configured
    legacy = (env.get("CARM_COURSE_URL") or "").strip()
    if DASHBOARD_URL_RE.fullmatch(legacy):
        return legacy
    return DEFAULT_CARM_DASHBOARD_URL


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
    previous_active = active_course_id()
    if value.isdigit():
        value = course_url_from_id(value)
    if DASHBOARD_URL_RE.fullmatch(value):
        write_env_values({"CARM_DASHBOARD_URL": value})
        configure_work_dirs()
        return current_course_url()
    if not COURSE_URL_RE.fullmatch(value):
        raise ValueError("Introduce una URL de curso CARM, una URL de area personal CARM valida o solo el ID numerico del curso.")
    write_env_values({"CARM_COURSE_URL": value})
    new_course_id = course_id_from_url(value)
    if new_course_id:
        save_app_config({"active_course_id": new_course_id})
    selected_raw = load_app_config().get("selected_course_ids", [])
    selected = [str(item).strip() for item in selected_raw] if isinstance(selected_raw, list) else []
    selected = [item for item in selected if item.isdigit()]
    if new_course_id and (not selected or selected == [previous_active]):
        save_app_config({"selected_course_ids": [new_course_id]})
    configure_work_dirs()
    return value


def save_course_scope_config(enabled: bool) -> None:
    save_app_config({"course_scoped_dirs": bool(enabled)})
    configure_work_dirs()


configure_work_dirs()


def selected_course_ids() -> list[str]:
    if not account_context_matches_current_user():
        return []
    raw = load_app_config().get("selected_course_ids", [])
    ids: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            course_id = str(item or "").strip()
            if course_id.isdigit() and course_id not in ids:
                ids.append(course_id)
    if not ids:
        current = active_course_id()
        if current:
            ids.append(current)
    return ids


def save_selected_course_ids(ids: list[str]) -> list[str]:
    clean: list[str] = []
    for item in ids:
        course_id = str(item or "").strip()
        if course_id.isdigit() and course_id not in clean:
            clean.append(course_id)
    if not clean:
        current = active_course_id()
        if current:
            clean.append(current)
    save_app_config({"selected_course_ids": clean})
    return clean


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

    def start(self, action: str, args: list[str], env_overrides: dict[str, str] | None = None) -> tuple[bool, str]:
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
            if env_overrides:
                env.update({str(key): str(value) for key, value in env_overrides.items()})
            if action in {"detect_course", "detect_courses", "auto_prepare", "check_playwright"}:
                env["CARM_HEADLESS"] = "1"
            popen_kwargs = {}
            if os.name == "nt":
                popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
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
                **popen_kwargs,
            )
            threading.Thread(target=self._read_output, daemon=True).start()
            return True, "Proceso iniciado."

    def _read_output(self) -> None:
        global AUTO_COURSE_QUEUE
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
            if self.action in {"detect_course", "detect_courses", "check_playwright"} and code == 0 and not has_error:
                self.last_detection_at = time.time()
            if self.action == "check_playwright" and code == 0 and not has_error and self.scan_blocked_by_permissions:
                self.scan_blocked_by_permissions = False
                should_retry_scan = True
            if self.action == "auto_prepare":
                self.last_detection_at = time.time()
            should_auto_correct = (
                AUTO_CORRECT_AFTER_SCAN
                and self.action == "detect_course"
                and code == 0
                and not has_error
            )
        if has_error:
            if self.action == "auto_prepare":
                AUTO_COURSE_QUEUE = []
            if self.permission_error:
                notify("Corrector CARM", "Windows bloqueo Playwright/Chromium. Ejecuta la app con permisos permitidos.", target="activity")
            else:
                notify("Corrector CARM", "Hay errores en la ultima tarea. Abre la interfaz para revisar el log.", target="activity")
        elif self.action in {"auto_prepare", "prepare"}:
            notify_prompts_prepared()
        elif self.action in {"prepare_carm_api", "solve_prompts_api", "import_codex"}:
            notify_pending_publication()
        if should_retry_scan:
            notify("Corrector CARM", "Permisos de navegador recuperados. Repito el escaneo de CARM.", target="activity")
            threading.Timer(1.0, lambda: start_startup_work()).start()
        if should_auto_correct:
            threading.Timer(1.0, lambda: start_auto_prepare()).start()
        elif self.action == "auto_prepare" and not has_error:
            threading.Timer(1.0, lambda: continue_auto_course_queue()).start()

    def _notify_line(self, line: str) -> None:
        lowered = line.lower()
        if (" - error - " in lowered or lowered.startswith("error")) and not self.error_notified:
            self.error_notified = True
            notify("Corrector CARM - error", line, target="activity")
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
            notify("Corrector CARM - revision manual", line, target="activity")

    @staticmethod
    def _is_permission_error(line: str) -> bool:
        lowered = line.lower()
        return (
            "winerror 5" in lowered
            or "permissionerror" in lowered
            or "acceso denegado" in lowered
        )

    def stop(self) -> bool:
        global AUTO_COURSE_QUEUE
        with self.lock:
            AUTO_COURSE_QUEUE = []
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


def restart_app(delay: float = 0.7) -> None:
    relaunch_args = [sys.executable, *sys.argv]
    if len(relaunch_args) > 1:
        script_path = Path(relaunch_args[1])
        if script_path.suffix.lower() == ".py" and not script_path.is_absolute():
            relaunch_args[1] = str((ROOT / script_path).resolve())

    helper_code = (
        "import subprocess, sys, time;"
        "time.sleep(float(sys.argv[1]));"
        "subprocess.Popen(sys.argv[3:], cwd=sys.argv[2])"
    )
    helper_args = [sys.executable, "-c", helper_code, str(delay), str(ROOT), *relaunch_args]

    def do_restart() -> None:
        try:
            popen_kwargs = {"cwd": str(ROOT)}
            if os.name == "nt":
                popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(
                helper_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **popen_kwargs,
            )
        except Exception as exc:
            notify("Corrector CARM", f"No se pudo relanzar la app: {exc}", target="activity")
            return
        threading.Timer(1.5, lambda: os._exit(0)).start()
        try:
            RUNNER.stop()
        except Exception:
            pass
        try:
            if TRAY_ICON is not None:
                TRAY_ICON.stop()
        except Exception:
            pass
        try:
            if APP_SERVER is not None:
                APP_SERVER.shutdown()
        except Exception:
            pass
        os._exit(0)

    threading.Thread(target=do_restart, daemon=False).start()


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


def revision_csv_state(path: Path) -> dict:
    rows = 0
    blocking = 0
    activities: dict[str, int] = {}
    states: dict[str, int] = {}
    read_error = ""
    estados_bloqueantes = {"revision_manual_necesaria", "error", "error_descarga", "sin_archivo_detectado", "sin_entrega"}
    if path.exists():
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                data = list(csv.DictReader(handle, delimiter=";"))
            rows = len(data)
            for row in data:
                estado = (row.get("estado") or "sin_estado").strip().lower() or "sin_estado"
                actividad = (row.get("actividad") or "sin_actividad").strip().lower() or "sin_actividad"
                states[estado] = states.get(estado, 0) + 1
                activities[actividad] = activities.get(actividad, 0) + 1
                if estado in estados_bloqueantes:
                    blocking += 1
        except Exception as exc:
            blocking = 1
            read_error = str(exc)
    return {
        "file": file_info(path),
        "rows": rows,
        "blocking": blocking,
        "activities": activities,
        "states": states,
        "read_error": read_error,
    }


def pending_publication_state() -> dict:
    combined = file_info(COMBINED_JSON)
    revision = file_info(REVISION_CSV)
    source_path = default_correction_source_path()
    source = file_info(source_path)
    assisted = file_info(SUBIDA_ASISTIDA_JSON)
    revision_state = revision_csv_state(REVISION_CSV)
    rows = revision_state["rows"]
    blocking = revision_state["blocking"]
    activities = revision_state["activities"]
    base_modified = max(source["modified"], revision["modified"])
    last_handled = assisted["modified"]
    pending = bool(revision["exists"] and rows and last_handled < base_modified)
    return {
        "pending": pending,
        "rows": rows,
        "blocking": blocking,
        "activities": activities,
        "states": revision_state["states"],
        "read_error": revision_state["read_error"],
        "ready_for_assisted_upload": pending and blocking == 0,
        "source": source,
        "combined": combined,
        "revision_csv": revision,
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
            target="upload",
        )
        return
    notify(
        "Corrector CARM",
        f"Hay {pending['rows']} calificaciones revisadas pendientes de subir. Abre la interfaz para iniciar subida asistida.",
        target="upload",
    )


def notify_prompts_prepared() -> None:
    prompts = sorted(PROMPTS_DIR.glob("prompt_*.md")) if PROMPTS_DIR.exists() else []
    if prompts:
        notify(
            "Corrector CARM",
            f"Hay {len(prompts)} prompt(s) preparados. Abre la interfaz y pulsa Corregir prompts con API.",
            target="prepare",
        )


def start_auto_prepare() -> tuple[bool, str]:
    global AUTO_COURSE_QUEUE
    if correction_mode() == "api" and openai_api_key_present():
        notify("Corrector CARM", "Preparo prompts automaticamente. La API se ejecutara cuando lo confirmes.", target="activity")
    else:
        notify("Corrector CARM", "Sin API key o modo prompt: preparo prompts para correccion manual.", target="activity")
    courses = selected_courses_for_auto()
    if len(courses) > 1:
        if not course_scoped_dirs_enabled():
            AUTO_COURSE_QUEUE = []
            notify(
                "Corrector CARM",
                "Hay varios cursos seleccionados, pero las carpetas por curso no estan activas. Uso solo el curso activo para evitar mezclar datos.",
                target="settings",
            )
        else:
            AUTO_COURSE_QUEUE = courses[1:]
            return start_auto_prepare_for_course(courses[0])
    return RUNNER.start("auto_prepare", auto_prepare_args_from_cache())


def continue_auto_course_queue() -> None:
    global AUTO_COURSE_QUEUE
    if not AUTO_COURSE_QUEUE:
        return
    next_course = AUTO_COURSE_QUEUE.pop(0)
    start_auto_prepare_for_course(next_course)


def start_startup_work() -> None:
    if not carm_credentials_present():
        notify("Corrector CARM", "Faltan credenciales CARM. Abre la interfaz para configurarlas.", target="settings")
        return
    if not active_course_id():
        notify("Corrector CARM", "No hay curso activo. Detecto cursos disponibles desde el area personal.", target="settings")
        RUNNER.start("detect_courses", ["--listar-cursos-carm"])
        return
    if has_cached_course_data():
        RUNNER.last_detection_at = time.time()
        if AUTO_CORRECT_AFTER_SCAN:
            start_auto_prepare()
        else:
            notify("Corrector CARM", "Cache del curso cargada. No se refresca CARM al iniciar.", target="activity")
        return
    notify("Corrector CARM", "No hay cache didactica del curso. Hago primera deteccion en CARM.", target="activity")
    RUNNER.start("detect_course", ["--cachear-curso"])


def schedule_course_scan_if_missing(course_id: str, retries: int = 90, delay_seconds: float = 2.0) -> tuple[bool, str]:
    course_id = str(course_id or "").strip()
    if not course_id:
        return False, "No hay curso activo para escanear."
    if has_cached_course_data():
        return False, "El curso ya tiene cache didactica."

    ok, message = RUNNER.start("detect_course", ["--cachear-curso"])
    if ok:
        notify("Corrector CARM", f"Escaneando curso {course_id} para crear cache didactica.", target="activity")
        return True, "Escaneo del curso iniciado."

    if "marcha" not in message.lower() or retries <= 0:
        return False, message

    def retry() -> None:
        if active_course_id() != course_id or has_cached_course_data():
            return
        schedule_course_scan_if_missing(course_id, retries=retries - 1, delay_seconds=delay_seconds)

    threading.Timer(delay_seconds, retry).start()
    return True, "Escaneo del curso programado cuando termine la tarea actual."


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


def cache_path_for_course_id(course_id: str) -> Path | None:
    course_id = str(course_id or "").strip()
    if not course_id.isdigit():
        return None
    path = ROOT / "cache_carm" / f"curso_{course_id}.sqlite"
    return path if path.exists() else None


def is_detected_course_allowed(title: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(title or "").strip().lower())
    normalized = normalized.replace("_", " ").replace(":", " ").strip()
    blocked = {"faq", "faqs", "curso carm", "carm curso carm", "carm - curso carm"}
    if normalized in blocked:
        return False
    return "faq" not in normalized


def detected_courses() -> list[dict]:
    cursos_por_id: dict[str, dict] = {}
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
        titulo = titulo or f"Curso {course_id}"
        if not is_detected_course_allowed(titulo):
            continue
        cursos_por_id[course_id] = {
            "id": course_id,
            "url": url,
            "titulo": titulo,
            "cache_path": str(path),
            "modified": updated,
            "source": "cache",
            "current": course_id == course_id_from_url(current_course_url()),
        }

    if CURSOS_DETECTADOS_JSON.exists():
        try:
            datos = json.loads(CURSOS_DETECTADOS_JSON.read_text(encoding="utf-8-sig"))
            if isinstance(datos, list):
                for item in datos:
                    if not isinstance(item, dict):
                        continue
                    course_id = str(item.get("id") or course_id_from_url(str(item.get("url") or ""))).strip()
                    if not course_id:
                        continue
                    existente = cursos_por_id.get(course_id, {})
                    titulo = str(item.get("titulo") or existente.get("titulo") or f"Curso {course_id}")
                    if not is_detected_course_allowed(titulo):
                        continue
                    cursos_por_id[course_id] = {
                        "id": course_id,
                        "url": str(item.get("url") or existente.get("url") or course_url_from_id(course_id)),
                        "titulo": titulo,
                        "cache_path": existente.get("cache_path", ""),
                        "modified": max(float(existente.get("modified") or 0), CURSOS_DETECTADOS_JSON.stat().st_mtime),
                        "source": "cache+y_carm" if existente else "carm",
                        "current": course_id == course_id_from_url(current_course_url()),
                    }
        except Exception:
            pass

    return sorted(cursos_por_id.values(), key=lambda item: (not item.get("current"), item.get("titulo", "").lower()))


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
                columnas_unidad = {
                    row[1]
                    for row in con.execute("PRAGMA table_info(unidad)").fetchall()
                }
                unidad_select = (
                    "codigo, COALESCE(nombre, ''), COALESCE(contenido_imprimible, ''), COALESCE(resumen_didactico, '')"
                    if "resumen_didactico" in columnas_unidad
                    else "codigo, COALESCE(nombre, ''), COALESCE(contenido_imprimible, ''), ''"
                )
                for codigo, nombre, contenido, resumen in con.execute(
                    f"SELECT {unidad_select} FROM unidad ORDER BY codigo"
                ).fetchall():
                    codigo = str(codigo or "").strip().lower()
                    if UNIT_RE.fullmatch(codigo):
                        units[codigo] = str(nombre or codigo.upper())
                        if is_useful_didactic_context(resumen) or is_useful_didactic_context(contenido):
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
        "dashboard_url": dashboard_url(),
        "course_id": course_id_from_url(current_course_url()),
        "selected_course_ids": selected_course_ids(),
        "course_scoped_dirs": course_scoped_dirs_enabled(),
        "active_pendientes_dir": str(PENDIENTES_DIR),
        "active_temporal_dir": str(TEMPORAL_DIR),
        "base_pendientes_dir": str(BASE_PENDIENTES_DIR),
        "base_temporal_dir": str(BASE_TEMPORAL_DIR),
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


def has_cached_course_data() -> bool:
    options = course_options()
    units = options.get("units") or []
    didactic_units = int(options.get("didactic_units") or 0)
    return bool(
        options.get("cache_path")
        and units
        and options.get("activities")
        and didactic_units >= len(units)
    )


def auto_prepare_args_from_cache() -> list[str]:
    if correction_mode() == "api" and openai_api_key_present():
        return [
            *AUTO_CORRECT_ARGS,
            "--pendientes",
            str(PENDIENTES_DIR),
            "--temporal",
            str(TEMPORAL_DIR),
            "--max-entregas-por-prompt",
            "0",
        ]
    return [
        "--preparar-carm-codex",
        "--pendientes",
        str(PENDIENTES_DIR),
        "--temporal",
        str(TEMPORAL_DIR),
        "--max-entregas-por-prompt",
        "0",
    ]


def course_url_for_id(course_id: str) -> str:
    for course in detected_courses():
        if str(course.get("id") or "") == str(course_id):
            return str(course.get("url") or course_url_from_id(course_id))
    return course_url_from_id(course_id)


def selected_courses_for_auto() -> list[dict[str, str]]:
    courses: list[dict[str, str]] = []
    for course_id in selected_course_ids():
        if not course_id.isdigit():
            continue
        pendientes, temporal = course_work_dirs(course_id)
        courses.append(
            {
                "id": course_id,
                "url": course_url_for_id(course_id),
                "pendientes": str(pendientes),
                "temporal": str(temporal),
            }
        )
    return courses


def selected_course_summaries() -> list[dict]:
    detected = {str(item.get("id") or ""): item for item in detected_courses()}
    summaries: list[dict] = []
    for course in selected_courses_for_auto():
        course_id = course["id"]
        pendientes = Path(course["pendientes"])
        temporal = Path(course["temporal"])
        prompts_dir = pendientes / "prompts_codex"
        prompts = sorted(prompts_dir.glob("prompt_*.md")) if prompts_dir.exists() else []
        corrections = sorted(prompts_dir.glob("*_correccion.json")) if prompts_dir.exists() else []
        revision_csv = temporal / "revision_pendiente.csv"
        revision_state = revision_csv_state(revision_csv)
        cache_path = cache_path_for_course_id(course_id)
        cache_info = file_info(cache_path) if cache_path else file_info(ROOT / "cache_carm" / f"curso_{course_id}.sqlite")
        summaries.append(
            {
                "id": course_id,
                "titulo": str(detected.get(course_id, {}).get("titulo") or f"Curso {course_id}"),
                "url": course["url"],
                "pendientes_dir": str(pendientes),
                "temporal_dir": str(temporal),
                "cache_exists": bool(cache_path),
                "cache_path": str(cache_path or ""),
                "cache": cache_info,
                "prompts": len(prompts),
                "corrections": len(corrections),
                "revision_csv": revision_state["file"],
                "revision_rows": revision_state["rows"],
                "revision_blocking": revision_state["blocking"],
                "revision_activities": revision_state["activities"],
                "revision_states": revision_state["states"],
                "revision_read_error": revision_state["read_error"],
            }
        )
    return summaries


def auto_prepare_args_for_course(course: dict[str, str]) -> list[str]:
    return [
        "--preparar-carm-codex",
        "--pendientes",
        course["pendientes"],
        "--temporal",
        course["temporal"],
        "--max-entregas-por-prompt",
        "0",
    ]


def start_auto_prepare_for_course(course: dict[str, str]) -> tuple[bool, str]:
    Path(course["pendientes"]).mkdir(parents=True, exist_ok=True)
    Path(course["temporal"]).mkdir(parents=True, exist_ok=True)
    notify("Corrector CARM", f"Autoprompteo iniciado para curso {course['id']}.", target="activity")
    return RUNNER.start(
        "auto_prepare",
        auto_prepare_args_for_course(course),
        env_overrides={"CARM_COURSE_URL": course["url"]},
    )


def start_detect_course_for_course(course: dict[str, str]) -> tuple[bool, str]:
    notify("Corrector CARM", f"Actualizo cache didactica del curso {course['id']}.", target="activity")
    return RUNNER.start(
        "detect_course",
        ["--cachear-curso"],
        env_overrides={"CARM_COURSE_URL": course["url"]},
    )


def project_state() -> dict:
    prompts = sorted(PROMPTS_DIR.glob("prompt_*.md")) if PROMPTS_DIR.exists() else []
    corrections = sorted(PROMPTS_DIR.glob("*_correccion.json")) if PROMPTS_DIR.exists() else []
    resumenes = sorted(TEMPORAL_DIR.glob("resumen*.txt")) if TEMPORAL_DIR.exists() else []
    return {
        "release": release_info(),
        "combined": file_info(COMBINED_JSON),
        "revision_csv": file_info(REVISION_CSV),
        "correction_source": file_info(default_correction_source_path()),
        "pendientes_dir": str(PENDIENTES_DIR),
        "base_pendientes_dir": str(BASE_PENDIENTES_DIR),
        "prompts_dir": str(PROMPTS_DIR),
        "temporal_dir": str(TEMPORAL_DIR),
        "base_temporal_dir": str(BASE_TEMPORAL_DIR),
        "course_scoped_dirs": course_scoped_dirs_enabled(),
        "account_context_ok": account_context_matches_current_user(),
        "course_id": active_course_id(),
        "selected_course_ids": selected_course_ids(),
        "selected_courses": selected_course_summaries(),
        "auto_course_queue": [course.get("id", "") for course in AUTO_COURSE_QUEUE],
        "auto_correct_after_scan": AUTO_CORRECT_AFTER_SCAN,
        "startup_installed": startup_cmd_path().exists(),
        "startup_auto_correct_enabled": startup_auto_correct_enabled(),
        "auto_scan_interval_minutes": auto_scan_interval_minutes(),
        "periodic_auto_prepare": periodic_auto_prepare_enabled(),
        "auto_prepare_interval_minutes": auto_prepare_interval_minutes(),
        "auto_prepare_time": auto_prepare_time_of_day(),
        "json_options": json_options(),
        "prompts": [file_info(p) for p in prompts],
        "corrections": [file_info(p) for p in corrections],
        "summaries": [file_info(p) for p in resumenes],
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
    .course-switch { min-width: 210px; max-width: 320px; }
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
        <small id="releaseInfo">Panel local de preparacion, revision y subida</small>
      </div>
    </div>
    <div class="topbar-actions">
      <select id="activeCourseSelect" class="course-switch" aria-label="Curso activo"></select>
      <span id="courseSummary" class="pill"></span>
      <span id="statusBadge" class="badge idle">Parado</span>
      <button id="refreshBtn">Actualizar</button>
      <button id="restartBtn">Reiniciar app</button>
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
          <div><strong>Preparar</strong><small>CARM y OpenAI API</small></div>
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

      <section id="prepare">
        <div class="section-head">
          <h2>Preparar correcciones</h2>
          <p>Elige una unidad o un caso concreto y genera las salidas revisables.</p>
        </div>
        <div class="row">
          <div class="field">
            <label for="prepareMode">Filtro</label>
            <select id="prepareMode">
              <option value="course">Todo el curso</option>
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
              <option value="0" selected>Todos los pendientes</option>
              <option value="3">3</option>
              <option value="4">4</option>
              <option value="5">5</option>
              <option value="6">6</option>
              <option value="8">8</option>
              <option value="10">10</option>
              <option value="12">12</option>
            </select>
          </div>
        </div>
        <div class="button-row">
          <button class="primary" id="prepareBtn">Preparar prompts</button>
          <button id="solveApiBtn">Corregir prompts con API</button>
          <button class="danger" id="stopBtn">Detener</button>
        </div>
      </section>

      <section id="upload">
        <div class="section-head">
          <h2>Subida a CARM</h2>
          <p>La subida asistida rellena CARM y espera tu guardado manual en cada alumno.</p>
        </div>
        <label for="jsonPath">Archivo de correcciones</label>
        <select id="jsonPath">
          <option value="">Cargando fuentes de correccion...</option>
        </select>
        <div id="uploadPendingDetail" class="hint"></div>
        <div class="button-row">
          <button id="importCodexBtn">Importar JSON a revision</button>
          <button class="primary" id="assistPublishBtn">Sin pendientes para subir</button>
        </div>
        <label class="check" style="margin-top:10px">
          <input type="checkbox" id="publishCheck">
          Confirmo que he revisado las correcciones
        </label>
        <label class="check">
          <input type="checkbox" id="uploadTraceCheck">
          Guardar trace de diagnostico de subida
        </label>
        <p class="hint">El trace puede contener datos personales de CARM. Activalo solo para diagnosticar fallos y no lo compartas sin revisar.</p>
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
            <span>correcciones listas</span>
          </div>
        </div>
        <div class="stack">
          <div>
            <label>Archivo para subir</label>
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
          <p>Prompts, resúmenes y respuestas recibidas.</p>
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
          <div>
            <label>Resúmenes</label>
            <div id="summariesList" class="list"></div>
          </div>
        </div>
      </section>
    </div>

    <section class="activity-panel" id="activity">
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
        <p class="hint">Introduce tus credenciales de CARM. Despues elige si la app corrige con OpenAI API o si solo genera prompts para pegarlos manualmente en Codex/ChatGPT.</p>
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
        <div class="grid2">
          <div>
            <label for="correctionMode">Modo de correccion</label>
            <select id="correctionMode">
              <option value="api">OpenAI API: corregir automaticamente</option>
              <option value="prompt">Solo prompts: corregir manualmente fuera</option>
            </select>
          </div>
          <div>
            <label for="openaiModel">Modelo OpenAI</label>
            <select id="openaiModel">
              <option value="gpt-5-mini">gpt-5-mini</option>
              <option value="gpt-5.4-mini">gpt-5.4-mini</option>
              <option value="gpt-5.2">gpt-5.2</option>
              <option value="gpt-4.1-mini">gpt-4.1-mini</option>
            </select>
          </div>
        </div>
        <div>
          <label for="openaiKey">OpenAI API key</label>
          <input id="openaiKey" type="password" autocomplete="off" placeholder="sk-...">
          <p class="hint">Opcional si eliges solo prompts. Si ya hay una key guardada puedes dejar este campo vacio.</p>
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
            <div class="path" id="activeFoldersMessage">Carpeta activa pendiente de cargar.</div>
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
              <label for="courseUrl">URL area personal, URL de curso o ID</label>
              <input id="courseUrl" placeholder="https://formacion.carm.es/my/index.php">
            </div>
            <div>
              <label for="detectedCourse">Cursos detectados</label>
              <select id="detectedCourse"></select>
            </div>
            <div>
              <label>Cursos para autoprompteo</label>
              <div id="selectedCoursesList" class="list"></div>
            </div>
            <div>
              <label>Estado por curso</label>
              <div id="selectedCoursesSummary" class="list"></div>
            </div>
            <div class="path" id="courseMessage">Curso pendiente de cargar.</div>
            <div class="row">
              <button class="primary" id="saveCourseBtn" type="button">Guardar curso</button>
              <button id="useDetectedCourseBtn" type="button">Usar detectado</button>
              <button id="saveSelectedCoursesBtn" type="button">Guardar seleccion</button>
              <button id="detectCoursesBtn" type="button">Detectar cursos CARM</button>
            </div>
            <label class="check">
              <input type="checkbox" id="courseScopedDirs">
              Separar carpetas por curso
            </label>
            <p class="hint">Activado por defecto. Este curso usa sus propias carpetas en C:\temp\vscodec\cursos\&lt;id&gt;\ para no mezclar prompts, CSV ni resumenes.</p>
            <h3>Autoescaneo</h3>
            <div class="grid2">
              <div>
                <label for="autoScanInterval">Revisar CARM cada (minutos)</label>
                <input id="autoScanInterval" type="number" min="0" max="1440" step="5">
              </div>
              <div>
                <label>&nbsp;</label>
                <button id="saveAutomationBtn" type="button">Guardar automatizacion</button>
              </div>
            </div>
            <p class="hint">Solo comprueba si hay que detectar cursos o actualizar cache. Usa 0 para desactivar el autoescaneo.</p>
            <h3>Autoprompt</h3>
            <label class="check">
              <input type="checkbox" id="periodicAutoPrepare">
              Preparar prompts automaticamente
            </label>
            <div class="grid2">
              <div>
                <label for="autoPrepareInterval">Preparar prompts cada (minutos)</label>
                <input id="autoPrepareInterval" type="number" min="0" max="10080" step="5">
              </div>
              <div>
                <label for="autoPrepareTime">Hora exacta diaria</label>
                <input id="autoPrepareTime" type="time">
              </div>
            </div>
            <p class="hint">Usa 0 para desactivar intervalos. La hora exacta se ejecuta una vez al dia. El autoprompt no llama a la API, no guarda notas en CARM y no borra prompts pendientes sin corregir.</p>
            <div class="row">
              <button id="scanNowBtn" type="button">Escanear ahora</button>
              <button id="pauseScanBtn" type="button">Pausar autoescaneo</button>
              <button id="resumeScanBtn" type="button">Reactivar 60 min</button>
            </div>
          </div>
        </section>

        <section style="box-shadow:none">
          <div class="section-head">
            <h2>Windows</h2>
            <p>Controla que ocurre al iniciar sesion en Windows.</p>
          </div>
          <div class="stack">
            <label class="check">
              <input type="checkbox" id="startupEnabled">
              Iniciar Corrector CARM en bandeja con Windows
            </label>
            <label class="check">
              <input type="checkbox" id="startupAutoCorrect">
              Preparar prompts automaticamente al iniciar
            </label>
            <p class="hint">La preparacion automatica no llama a la API ni publica en CARM. Solo revisa pendientes y genera prompts.</p>
            <div class="path" id="startupMessage">Arranque pendiente de comprobar.</div>
            <div class="row">
              <button id="saveStartupBtn" type="button">Guardar arranque</button>
            </div>
          </div>
        </section>

        <section style="box-shadow:none">
          <div class="section-head">
            <h2>Estado local</h2>
            <p>Comprueba dependencias, Chromium, configuracion y que Git no versiona datos sensibles.</p>
          </div>
          <div class="stack">
            <div class="path" id="healthMessage">Comprobacion pendiente.</div>
            <div id="healthChecks" class="list"></div>
            <div class="row">
              <button id="checkHealthBtn" type="button">Comprobar equipo</button>
            </div>
          </div>
        </section>

        <section style="box-shadow:none">
          <div class="section-head">
            <h2>OpenAI</h2>
            <p>Con API key la app corrige automaticamente. Sin API key genera prompts para corregir fuera e importar el JSON.</p>
          </div>
          <div class="stack">
            <div class="grid2">
              <div>
                <label for="settingsCorrectionMode">Modo de correccion</label>
                <select id="settingsCorrectionMode">
                  <option value="api">OpenAI API: corregir automaticamente</option>
                  <option value="prompt">Solo prompts: corregir manualmente fuera</option>
                </select>
              </div>
              <div>
                <label for="settingsOpenaiModel">Modelo OpenAI</label>
                <select id="settingsOpenaiModel">
                  <option value="gpt-5-mini">gpt-5-mini</option>
                  <option value="gpt-5.4-mini">gpt-5.4-mini</option>
                  <option value="gpt-5.2">gpt-5.2</option>
                  <option value="gpt-4.1-mini">gpt-4.1-mini</option>
                </select>
              </div>
            </div>
            <div>
              <label for="settingsOpenaiKey">OpenAI API key</label>
              <input id="settingsOpenaiKey" type="password" autocomplete="off" placeholder="sk-...">
              <p class="hint">Si introduces una key, la app la verifica con una llamada minima y activa el modo API. Deja el campo vacio para conservar la key actual.</p>
            </div>
            <div class="path" id="openaiMessage">OpenAI pendiente de comprobar.</div>
            <div class="row">
              <button class="primary" id="saveOpenaiBtn" type="button">Guardar OpenAI</button>
              <button id="checkOpenaiBtn" type="button">Comprobar API</button>
            </div>
          </div>
        </section>

        <div>
          <label for="advancedAction">Comando</label>
          <select id="advancedAction">
            <option value="detect_course">Actualizar datos didacticos desde CARM</option>
            <option value="detect_courses">Detectar cursos disponibles</option>
            <option value="check_playwright">Comprobar permisos de navegador</option>
            <option value="diagnose">Diagnosticar CARM</option>
            <option value="diagnose_evidence">Diagnosticar CARM con evidencias</option>
            <option value="list_carm">Listar entregas pendientes</option>
            <option value="cache_course">Cachear curso</option>
            <option value="check_openai">Comprobar OpenAI API</option>
            <option value="solve_prompts_api">Corregir prompts preparados con API</option>
            <option value="prepare_carm_api">Corregir desde CARM con API directo</option>
            <option value="prepare_carm_codex">Preparar prompts desde CARM</option>
            <option value="prepare_carm_codex_activity">Preparar prompts de un caso desde CARM</option>
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
                <option value="0" selected>Todos los pendientes</option>
                <option value="3">3</option>
                <option value="4">4</option>
                <option value="5">5</option>
                <option value="6">6</option>
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

        <div id="fieldsImport" class="advanced-fields">
          <div>
            <label for="importJsonPath">JSON/CSV de correcciones</label>
            <select id="importJsonPath">
              <option value="">Cargando fuentes de correccion...</option>
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
    let refreshInProgress = false;
    const advancedHints = {
      diagnose: 'Entra en CARM, genera diagnostico limpio y no descarga entregas.',
      check_playwright: 'Comprueba que Windows permite abrir Playwright/Chromium e iniciar sesion en CARM.',
      diagnose_evidence: 'Guarda HTML/capturas redactadas para depurar selectores. Usalo solo si necesitas evidencias.',
      detect_course: 'Entra en CARM y actualiza la cache didactica con unidades, casos practicos, enunciados y contenido estable.',
      detect_courses: 'Entra en CARM y lista los cursos visibles para este usuario. No descarga entregas ni corrige.',
      list_carm: 'Lista entregas que requieren calificacion sin descargar archivos.',
      cache_course: 'Actualiza la cache local de recursos estables del curso.',
      check_openai: 'Comprueba que OPENAI_API_KEY y OPENAI_MODEL estan configurados.',
      solve_prompts_api: 'Envia a OpenAI API los prompts ya preparados y genera el CSV revisable.',
      prepare_carm_api: 'Descarga entregas desde CARM y corrige con OpenAI API en un solo paso.',
      prepare_carm_codex: 'Descarga desde CARM y genera prompts para Codex sin llamar a la API.',
      prepare_carm_codex_activity: 'Descarga y prepara prompts solo para el caso practico elegido.',
      import_codex: 'Importa un JSON/CSV de correcciones y crea salidas revisables por alumno.',
      delete_cache: 'Borra la cache SQLite local del curso.'
    };
    const advancedLabels = {
      diagnose: '--diagnosticar-carm',
      check_playwright: '--comprobar-login-carm',
      diagnose_evidence: '--diagnosticar-carm --guardar-evidencias',
      detect_course: '--cachear-curso --refrescar-cache',
      detect_courses: '--listar-cursos-carm',
      list_carm: '--solo-listar-carm --unidad <unidad>',
      cache_course: '--cachear-curso --unidad <unidad>',
      check_openai: '--comprobar-openai-api',
      solve_prompts_api: '--corregir-prompts-openai',
      prepare_carm_api: '--extraer-carm --requerir-openai-api --unidad <unidad>',
      prepare_carm_codex: '--preparar-carm-codex --unidad <unidad> --max-entregas-por-prompt <n>',
      prepare_carm_codex_activity: '--preparar-carm-codex --actividad <caso> --max-entregas-por-prompt <n>',
      import_codex: '--importar-correcciones-codex <json>',
      delete_cache: '--borrar-cache-curso'
    };
    let courseOptions = {units: [], activities: []};
    let authState = {configured: false, session_saved: false};
    let coursePickSelectionOverride = null;

    function showSystemNotice(message) {
      $('systemNoticeText').textContent = message;
      $('systemNotice').classList.add('open');
    }

    function clearSystemNotice() {
      $('systemNotice').classList.remove('open');
      $('systemNoticeText').textContent = '';
    }

    function handleHashTarget() {
      const target = (window.location.hash || '').replace('#', '');
      if (!target) return;
      if (target === 'settings') {
        toggleSettings(true);
        return;
      }
      const el = $(target);
      if (el) el.scrollIntoView({behavior: 'smooth', block: 'start'});
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
      const kb = file.exists  Math.max(1, Math.round(file.size / 1024)) + ' KB' : 'no existe';
      return `<div class="item"><span>${escapeHtml(name)}<br><small>${escapeHtml(file.path)}</small></span><small>${escapeHtml(kb)}</small></div>`;
    }

    function escapeHtml(value) {
      return String(value  '').replace(/[&<>"']/g, (char) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
      }[char]));
    }

    function escapeAttr(value) {
      return escapeHtml(value);
    }

    function optionHtml(value, label) {
      return `<option value="${escapeAttr(value)}">${escapeHtml(label)}</option>`;
    }

    function jsonOptionHtml(item) {
      const suffix = item.exists  '' : ' · pendiente';
      return optionHtml(item.path, `${item.label}${suffix}`);
    }

    function courseOptionHtml(item) {
      const suffix = item.current  ' · actual' : '';
      return optionHtml(item.url, `${item.id} · ${item.titulo}${suffix}`);
    }

    function courseCheckboxHtml(item) {
      const selectedIds = coursePickSelectionOverride || courseOptions.selected_course_ids || [];
      const selected = selectedIds.includes(String(item.id));
      const suffix = item.current  ' · activo' : '';
      return `<label class="check"><input type="checkbox" class="coursePick" value="${escapeAttr(item.id)}" ${selected  'checked' : ''}> ${escapeHtml(item.id + ' · ' + item.titulo + suffix)}</label>`;
    }

    function checkedCourseIds() {
      return Array.from(document.querySelectorAll('.coursePick:checked')).map((item) => item.value);
    }

    function selectedCourseSummaryHtml(item) {
      const cache = item.cache_exists  'cache OK' : 'sin cache';
      const csv = item.revision_csv && item.revision_csv.exists
         `${item.revision_rows || 0} fila(s) CSV`
        : 'sin CSV';
      const blocking = item.revision_blocking  ` · ${item.revision_blocking} incidencia(s)` : '';
      const activities = item.revision_activities  Object.entries(item.revision_activities).map(([key, value]) => `${key}:${value}`).join(', ') : '';
      const cacheDate = item.cache && item.cache.modified  new Date(item.cache.modified * 1000).toLocaleString() : 'cache sin fecha';
      const detail = `${cache} · ${cacheDate} · ${item.prompts} prompt(s) · ${item.corrections} JSON · ${csv}${blocking}`;
      const extra = activities  `<br><small>${escapeHtml(activities)}</small>` : '';
      return `<div class="item"><span>${escapeHtml(item.id + ' · ' + item.titulo)}<br><small>${escapeHtml(detail)}</small>${extra}</span></div>`;
    }

    function healthCheckHtml(item) {
      const status = item.ok  'OK' : (item.required  'Pendiente' : 'Opcional');
      return `<div class="item"><span>${escapeHtml(item.name)}<br><small>${escapeHtml(item.message || '')}</small></span><small>${escapeHtml(status)}</small></div>`;
    }

    function activityLabel(act) {
      const tipo = act.tipo  ` · ${act.tipo}` : '';
      return `${act.codigo} · ${act.nombre}${tipo}`;
    }

    function fillSelect(select, html, current = '') {
      if (select.innerHTML !== html) {
        const previous = select.value;
        select.innerHTML = html;
        if (previous && [...select.options].some((opt) => opt.value === previous)) select.value = previous;
      }
      if (current && [...select.options].some((opt) => opt.value === current)) select.value = current;
    }

    function setText(id, value) {
      const el = $(id);
      if (el.textContent !== value) el.textContent = value;
    }

    function setHtml(id, value) {
      const el = $(id);
      if (el.innerHTML !== value) el.innerHTML = value;
    }

    function setInputValue(id, value) {
      const el = $(id);
      if (document.activeElement === el) return;
      if (el.value !== String(value  '')) el.value = String(value  '');
    }

    function isEditingControl() {
      const tag = (document.activeElement.tagName || '').toLowerCase();
      return ['input', 'select', 'textarea', 'button'].includes(tag);
    }

    function activitiesForUnit(unit) {
      return courseOptions.activities.filter((item) => item.unidad === unit);
    }

    async function loadOptions() {
      courseOptions = await api('/api/options');
      const unitHtml = courseOptions.units.length
         courseOptions.units.map((unit) => optionHtml(unit.codigo, `${unit.codigo} · ${unit.nombre}`)).join('')
        : '<option value="">Sin unidades detectadas</option>';
      fillSelect($('unidad'), unitHtml, $('unidad').value || 'ud01');
      fillSelect($('advancedUnidad'), unitHtml, $('advancedUnidad').value || $('unidad').value);
      updateActivityOptions();
      updateAdvancedActivityOptions();
      const source = courseOptions.source === 'cache_didactica'
         (courseOptions.didactic_units < courseOptions.units.length  'cache parcial' : 'cache didactica')
        : 'valores base';
      $('courseSummary').textContent = `${courseOptions.units.length} unidades · ${courseOptions.activities.length} casos · ${source}`;
    }

    async function loadAuth() {
      authState = await api('/api/auth');
      $('logoutBtn').disabled = !authState.configured;
      if ($('correctionMode')) $('correctionMode').value = authState.correction_mode || 'prompt';
      if ($('openaiModel')) $('openaiModel').value = authState.openai_model || 'gpt-5-mini';
      if ($('settingsCorrectionMode')) $('settingsCorrectionMode').value = authState.correction_mode || 'prompt';
      if ($('settingsOpenaiModel')) $('settingsOpenaiModel').value = authState.openai_model || 'gpt-5-mini';
      if ($('openaiMessage')) {
        $('openaiMessage').textContent = authState.openai_api_configured
           `API configurada. Modo: ${authState.correction_mode || 'api'}. Modelo: ${authState.openai_model || 'gpt-5-mini'}.`
          : `Sin API key. Modo: ${authState.correction_mode || 'prompt'}.`;
      }
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
           source.map((act) => optionHtml(act.codigo, activityLabel(act))).join('')
          : '<option value="">Sin casos detectados para esta unidad</option>',
        $('actividad').value
      );
      $('activityField').style.display = $('prepareMode').value === 'activity'  '' : 'none';
      $('unidad').disabled = $('prepareMode').value === 'course';
    }

    function updateAdvancedActivityOptions() {
      fillSelect(
        $('advancedActividad'),
        courseOptions.activities.length
           courseOptions.activities.map((act) => optionHtml(act.codigo, activityLabel(act))).join('')
          : '<option value="">Sin casos detectados</option>',
        $('advancedActividad').value || $('actividad').value
      );
    }

    function setBusy(running) {
      const locked = running || !authState.configured;
      const hasUnits = courseOptions.units.length > 0;
      const mode = $('prepareMode').value;
      const hasSelectedActivity = mode !== 'activity' || Boolean($('actividad').value);
      $('prepareBtn').disabled = locked || (mode !== 'course' && !hasUnits) || !hasSelectedActivity;
      $('prepareBtn').textContent = 'Preparar prompts';
      $('solveApiBtn').disabled = locked || !authState.openai_api_configured;
      $('importCodexBtn').disabled = locked || !window.__selectedCorrectionIsImportable;
      const pendingRows = Number(window.__pendingUploadRows || 0);
      const pendingBlocking = Number(window.__pendingUploadBlocking || 0);
      $('assistPublishBtn').disabled = locked || !window.__selectedCorrectionCanUpload || !$('publishCheck').checked || pendingRows <= 0 || pendingBlocking > 0;
      $('restartBtn').disabled = running;
      $('stopBtn').disabled = !running;
      $('runAdvancedBtn').disabled = locked;
      $('scanNowBtn').disabled = locked;
      $('detectCoursesBtn').disabled = locked;
      $('saveSelectedCoursesBtn').disabled = locked;
      $('activeCourseSelect').disabled = locked;
      $('pauseScanBtn').disabled = !authState.configured;
      $('resumeScanBtn').disabled = running || !authState.configured;
    }

    function setWorkflow(status, state) {
      const hasReviewFiles = state.revision_csv.exists && (state.pending_publication.rows > 0 || state.correction_source.exists);
      $('stepPrepare').className = 'step ' + (hasReviewFiles  'done' : 'active');
      $('stepReview').className = 'step ' + (hasReviewFiles  'active' : '');
      $('stepPublish').className = 'step ' + ($('publishCheck').checked  'active' : '');
      if (status.running) {
        $('stepPrepare').className = 'step active';
        $('stepReview').className = 'step';
        $('stepPublish').className = 'step';
      }
    }

    function toggleAuth(open) {
      $('authModal').classList.toggle('open', open);
      $('authModal').setAttribute('aria-hidden', open  'false' : 'true');
    }

    function setAuthLocked(locked) {
      document.body.classList.toggle('auth-locked', locked);
      $('authModal').classList.toggle('locked', locked);
      toggleAuth(locked);
      $('authSubtitle').textContent = locked  'Acceso requerido' : 'Credenciales configuradas';
      if (locked) {
        $('authMessage').textContent = 'Introduce CARM y elige API o solo prompts para usar el panel.';
        showSystemNotice('Panel bloqueado: falta configuracion inicial.');
      }
    }

    function pendingUploadLabel(pending) {
      if (!pending || !pending.rows) return 'Sin pendientes para subir';
      const activities = Object.entries(pending.activities || {})
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([activity, count]) => `${activity.toUpperCase()}: ${count}`)
        .join(' · ');
      return `Subir ${pending.rows} pendiente(s) a CARM${activities  ` · ${activities}` : ''}`;
    }

    function pendingUploadDetail(pending) {
      if (!pending || !pending.rows) return 'No hay calificaciones pendientes en revision_pendiente.csv.';
      const activities = Object.entries(pending.activities || {})
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([activity, count]) => `${activity.toUpperCase()} (${count})`)
        .join(', ');
      const blocked = pending.blocking
         ` Hay ${pending.blocking} fila(s) con incidencia; revisa el CSV antes de subir.`
        : '';
      return `Pendiente por subir: ${activities || `${pending.rows} fila(s)`}.${blocked}`;
    }

    function toggleSettings(open) {
      $('settingsModal').classList.toggle('open', open);
      $('settingsModal').setAttribute('aria-hidden', open  'false' : 'true');
      if (open) updateAdvancedForm();
    }

    function updateAdvancedForm() {
      const action = $('advancedAction').value;
      $('advancedHint').textContent = advancedHints[action] || '';
      $('fieldsUnidad').classList.toggle('active', ['list_carm', 'cache_course', 'prepare_carm_api', 'prepare_carm_codex'].includes(action));
      $('fieldsActivity').classList.toggle('active', action === 'prepare_carm_codex_activity');
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
      $('foldersMessage').textContent = result.message || (result.ok  'Carpetas guardadas.' : 'No se pudieron guardar.');
      $('saveFoldersBtn').disabled = false;
      await refresh();
    }

    async function saveCourse(urlOrId) {
      $('saveCourseBtn').disabled = true;
      $('courseMessage').textContent = 'Guardando curso...';
      const result = await api('/api/config/course', {
        method: 'POST',
        body: JSON.stringify({
          course: urlOrId || $('courseUrl').value,
          course_scoped_dirs: $('courseScopedDirs').checked
        })
      });
      $('courseMessage').textContent = result.message || (result.ok  'Curso guardado.' : 'No se pudo guardar.');
      $('saveCourseBtn').disabled = false;
      if (result.ok && result.pendientes_dir) {
        $('foldersMessage').textContent = `Carpeta activa del curso: ${result.pendientes_dir}`;
        $('activeFoldersMessage').textContent = `Carpeta activa: ${result.pendientes_dir} | ${result.temporal_dir}`;
      }
      if (result.ok && result.course_scan_started) {
        showSystemNotice('Curso guardado. Escaneando datos didacticos de CARM...');
      }
      if (result.ok) await refresh();
    }

    async function saveSelectedCourses() {
      const ids = checkedCourseIds();
      $('saveSelectedCoursesBtn').disabled = true;
      $('courseMessage').textContent = 'Guardando cursos seleccionados...';
      const result = await api('/api/config/selected-courses', {
        method: 'POST',
        body: JSON.stringify({course_ids: ids})
      });
      $('courseMessage').textContent = result.message || (result.ok  'Seleccion guardada.' : 'No se pudo guardar la seleccion.');
      $('saveSelectedCoursesBtn').disabled = false;
      await refresh();
    }

    async function saveAutomation() {
      $('saveAutomationBtn').disabled = true;
      $('courseMessage').textContent = 'Guardando automatizacion...';
      const result = await api('/api/config/automation', {
        method: 'POST',
        body: JSON.stringify({
          auto_scan_interval_minutes: $('autoScanInterval').value,
          periodic_auto_prepare: $('periodicAutoPrepare').checked,
          auto_prepare_interval_minutes: $('autoPrepareInterval').value,
          auto_prepare_time: $('autoPrepareTime').value
        })
      });
      $('courseMessage').textContent = result.message || (result.ok  'Automatizacion guardada.' : 'No se pudo guardar.');
      $('saveAutomationBtn').disabled = false;
      await refresh();
    }

    async function saveStartup() {
      $('saveStartupBtn').disabled = true;
      $('startupMessage').textContent = 'Guardando arranque de Windows...';
      const result = await api('/api/config/startup', {
        method: 'POST',
        body: JSON.stringify({
          enabled: $('startupEnabled').checked,
          auto_correct: $('startupAutoCorrect').checked
        })
      });
      $('startupMessage').textContent = result.message || (result.ok  'Arranque guardado.' : 'No se pudo guardar el arranque.');
      $('saveStartupBtn').disabled = false;
      await refresh();
    }

    async function checkHealth() {
      $('checkHealthBtn').disabled = true;
      $('healthMessage').textContent = 'Comprobando equipo...';
      const result = await api('/api/health');
      $('healthMessage').textContent = result.message || (result.ok  'Equipo listo.' : 'Hay puntos pendientes.');
      $('healthChecks').innerHTML = (result.checks || []).map(healthCheckHtml).join('');
      $('checkHealthBtn').disabled = false;
    }

    async function saveOpenAIConfig(checkOnly = false) {
      $('saveOpenaiBtn').disabled = true;
      $('checkOpenaiBtn').disabled = true;
      $('openaiMessage').textContent = checkOnly  'Comprobando API...' : 'Guardando OpenAI...';
      const result = await api('/api/config/openai', {
        method: 'POST',
        body: JSON.stringify({
          correction_mode: checkOnly  'api' : $('settingsCorrectionMode').value,
          openai_api_key: $('settingsOpenaiKey').value,
          openai_model: $('settingsOpenaiModel').value,
          check_only: checkOnly
        })
      });
      $('openaiMessage').textContent = result.message || (result.ok  'OpenAI configurado.' : 'No se pudo comprobar OpenAI.');
      $('saveOpenaiBtn').disabled = false;
      $('checkOpenaiBtn').disabled = false;
      if (result.ok && !checkOnly) {
        $('settingsOpenaiKey').value = '';
        await refresh();
      }
    }

    async function setAutomationInterval(minutes, stopCurrentScan = false) {
      $('autoScanInterval').value = String(minutes);
      await saveAutomation();
      if (stopCurrentScan) {
        const status = await api('/api/status');
        if (status.running && ['detect_course', 'auto_prepare'].includes(status.action)) {
          await api('/api/stop', {method:'POST'});
        }
      }
      await safeRefresh();
    }

    async function refresh() {
      const scrollX = window.scrollX;
      const scrollY = window.scrollY;
      const shouldRestoreScroll = !isEditingControl();
      const settingsOpen = $('settingsModal').classList.contains('open');
      const previousCourseUrlInput = $('courseUrl').value;
      const previousDetectedCourse = $('detectedCourse').value;
      const hadCoursePicks = document.querySelectorAll('.coursePick').length > 0;
      const previousCoursePicks = checkedCourseIds();
      await loadAuth();
      if (!authState.configured) {
        setBusy(false);
        return;
      }
      const status = await api('/api/status');
      const state = await api('/api/state');
      await loadOptions();
      if (state.release) {
        const dirty = state.release.dirty  ' · cambios locales' : '';
        setText('releaseInfo', `Panel local · v${state.release.version} · ${state.release.commit}${dirty}`);
      }
      setInputValue('pendientesDir', state.base_pendientes_dir || state.pendientes_dir);
      setInputValue('temporalDir', state.base_temporal_dir || state.temporal_dir);
      if ($('courseScopedDirs')) $('courseScopedDirs').checked = Boolean(state.course_scoped_dirs);
      setText('activeFoldersMessage', state.course_scoped_dirs && state.course_id
         `Carpeta activa del curso ${state.course_id}: ${state.pendientes_dir} | ${state.temporal_dir}`
        : `Carpeta activa: ${state.pendientes_dir} | ${state.temporal_dir}`);
      setInputValue('autoScanInterval', state.auto_scan_interval_minutes);
      if ($('periodicAutoPrepare')) $('periodicAutoPrepare').checked = Boolean(state.periodic_auto_prepare);
      setInputValue('autoPrepareInterval', state.auto_prepare_interval_minutes);
      setInputValue('autoPrepareTime', state.auto_prepare_time || '');
      $('pauseScanBtn').textContent = state.auto_scan_interval_minutes > 0  'Pausar autoescaneo' : 'Autoescaneo pausado';
      if ($('startupEnabled')) $('startupEnabled').checked = Boolean(state.startup_installed);
      if ($('startupAutoCorrect')) $('startupAutoCorrect').checked = Boolean(state.startup_auto_correct_enabled);
      if ($('startupMessage')) {
        $('startupMessage').textContent = state.startup_installed
           (state.startup_auto_correct_enabled  'Arranque instalado con autopreparacion de prompts.' : 'Arranque instalado sin autopreparacion de prompts.')
          : 'Arranque automatico no instalado.';
      }
      const jsonHtml = state.json_options.map(jsonOptionHtml).join('');
      const selectedCorrectionSource = state.json_options.find((item) => item.path === $('jsonPath').value);
      const correctionSourceValue = selectedCorrectionSource && selectedCorrectionSource.exists
         selectedCorrectionSource.path
        : state.correction_source.path;
      fillSelect($('jsonPath'), jsonHtml, correctionSourceValue);
      fillSelect($('importJsonPath'), jsonHtml, $('importJsonPath').value);
      const selectedJsonPath = $('jsonPath').value || '';
      window.__selectedCorrectionIsImportable = selectedJsonPath === state.prompts_dir || selectedJsonPath.toLowerCase().endsWith('.json');
      window.__selectedCorrectionCanUpload = selectedJsonPath !== state.prompts_dir;
      if (!settingsOpen || !previousCourseUrlInput) {
        setInputValue('courseUrl', courseOptions.course_url || courseOptions.dashboard_url || '');
      }
      const detectedHtml = courseOptions.detected_courses.length
         courseOptions.detected_courses.map(courseOptionHtml).join('')
        : '<option value="">Sin cursos detectados todavia</option>';
      fillSelect($('detectedCourse'), detectedHtml, settingsOpen  previousDetectedCourse : (courseOptions.course_url || ''));
      const activeCourseHtml = courseOptions.detected_courses.length
         courseOptions.detected_courses.map(courseOptionHtml).join('')
        : `<option value="${escapeAttr(courseOptions.course_url || '')}">Curso ${escapeHtml(courseOptions.course_id || 'actual')}</option>`;
      fillSelect($('activeCourseSelect'), activeCourseHtml, courseOptions.course_url || '');
      coursePickSelectionOverride = settingsOpen && hadCoursePicks  previousCoursePicks : null;
      $('selectedCoursesList').innerHTML = courseOptions.detected_courses.length
         courseOptions.detected_courses.map(courseCheckboxHtml).join('')
        : '<div class="item"><span>Detecta cursos CARM para elegir varios.</span></div>';
      coursePickSelectionOverride = null;
      $('selectedCoursesSummary').innerHTML = state.selected_courses && state.selected_courses.length
         state.selected_courses.map(selectedCourseSummaryHtml).join('')
        : '<div class="item"><span>Sin cursos seleccionados para autoprompteo.</span></div>';
      $('useDetectedCourseBtn').disabled = !courseOptions.detected_courses.length;
      setText('courseMessage', courseOptions.cache_path
         `Curso ${courseOptions.course_id} · cache: ${courseOptions.cache_path} · trabajo: ${state.pendientes_dir}`
        : `Curso ${courseOptions.course_id || 'sin ID'} · sin cache didactica · trabajo: ${state.pendientes_dir}`);
      const badge = $('statusBadge');
      const failed = status.has_error || (status.exit_code && status.exit_code !== 0);
      badge.className = 'badge ' + (status.running  '' : (failed  'err' : 'idle'));
      setText('statusBadge', status.running  'Ejecutando' : (status.permission_error  'Permisos Windows' : (failed  'Error' : 'Parado')));
      setText('elapsed', status.running  `${status.action} · ${status.elapsed}s` : '');
      const logBox = $('logBox');
      const wasAtLogBottom = logBox.scrollHeight - logBox.scrollTop - logBox.clientHeight < 24;
      const nextLog = (status.lines || []).join('\n') || (state.agent_log || []).join('\n');
      if (logBox.textContent !== nextLog) logBox.textContent = nextLog;
      if (wasAtLogBottom) logBox.scrollTop = logBox.scrollHeight;
      if (state.pending_publication && state.pending_publication.pending) {
        const pending = state.pending_publication;
        const extra = pending.blocking
           `Hay ${pending.blocking} incidencia(s); revisa el CSV antes de subir.`
          : 'Puedes usar Subida asistida para rellenar CARM y guardar manualmente.';
        showSystemNotice(`Hay ${pending.rows} calificacion(es) preparadas pendientes de subir. ${extra}`);
      }
      if (state.prompts.length && authState.openai_api_configured && !(state.pending_publication && state.pending_publication.pending)) {
        showSystemNotice(`Hay ${state.prompts.length} prompt(s) preparados. Pulsa "Corregir prompts con API" cuando quieras gastar la API.`);
      }
      window.__pendingUploadRows = state.pending_publication  state.pending_publication.rows : 0;
      window.__pendingUploadBlocking = state.pending_publication  state.pending_publication.blocking : 0;
      setText('assistPublishBtn', pendingUploadLabel(state.pending_publication));
      setText('uploadPendingDetail', pendingUploadDetail(state.pending_publication));
      setText('combinedPath', `${state.correction_source.path} · ${state.correction_source.exists  'listo' : 'pendiente'}`);
      setText('revisionPath', `${state.revision_csv.path} · ${state.revision_csv.exists  'listo' : 'pendiente'}`);
      setHtml('promptsList', state.prompts.length  state.prompts.map(fmtFile).join('') : '<span class="muted">Sin prompts</span>');
      setHtml('correctionsList', state.corrections.length  state.corrections.map(fmtFile).join('') : '<span class="muted">Sin correcciones</span>');
      setHtml('summariesList', state.summaries.length  state.summaries.map(fmtFile).join('') : '<span class="muted">Sin resumenes</span>');
      setText('promptCount', String(state.prompts.length));
      setText('correctionCount', String(state.pending_publication.rows || state.corrections.length));
      setWorkflow(status, state);
      setBusy(status.running);
      if (shouldRestoreScroll && (window.scrollX !== scrollX || window.scrollY !== scrollY)) {
        requestAnimationFrame(() => window.scrollTo(scrollX, scrollY));
      }
    }

    async function safeRefresh() {
      if (refreshInProgress) return;
      refreshInProgress = true;
      try {
        await refresh();
      } catch (err) {
        console.warn('No se pudo refrescar el panel local', err);
      } finally {
        refreshInProgress = false;
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

    async function restartApp() {
      if (!confirm('Reiniciar la aplicacion local ahora Se detendra cualquier tarea en curso.')) return;
      showSystemNotice('Reiniciando Corrector CARM...');
      try {
        await api('/api/restart', {method: 'POST'});
      } catch (err) {
        console.warn('La app se esta reiniciando', err);
      }
      setTimeout(() => window.location.reload(), 2200);
    }

    $('prepareBtn').onclick = () => run('prepare', {
      modo: $('prepareMode').value,
      unidad: $('unidad').value,
      actividad: $('actividad').value,
      max_entregas: $('maxEntregas').value
    });
    $('solveApiBtn').onclick = () => run('solve_prompts_api');
    $('importCodexBtn').onclick = () => run('import_codex', {json_path: $('jsonPath').value});
    $('assistPublishBtn').onclick = () => {
      if (!$('publishCheck').checked) return alert('Marca la confirmación antes de iniciar la subida asistida.');
      run('assist_publish', {json_path: $('jsonPath').value, guardar_trace_subida: $('uploadTraceCheck').checked});
    };
    $('stopBtn').onclick = async () => { await api('/api/stop', {method:'POST'}); await safeRefresh(); };
    $('refreshBtn').onclick = safeRefresh;
    $('restartBtn').onclick = restartApp;
    $('logoutBtn').onclick = async () => {
      if (!confirm('Esto vaciara CARM_USUARIO/CARM_CONTRASENA en .env y borrara la sesion recordada. Tendras que volver a introducir credenciales para usar el panel. Continuar')) return;
      const result = await api('/api/auth/logout', {method:'POST'});
      $('authMessage').textContent = result.message || 'Sesion cerrada.';
      await refresh();
    };
    $('saveAuthBtn').onclick = async () => {
      $('saveAuthBtn').disabled = true;
      $('authMessage').textContent = 'Verificando credenciales en CARM...';
      const result = await api('/api/auth/save', {
        method: 'POST',
        body: JSON.stringify({
          usuario: $('carmUser').value,
          contrasena: $('carmPass').value,
          correction_mode: $('correctionMode').value,
          openai_api_key: $('openaiKey').value,
          openai_model: $('openaiModel').value
        })
      });
      $('authMessage').textContent = result.message || (result.ok  'Guardado.' : 'No se pudo guardar.');
      $('saveAuthBtn').disabled = false;
      if (result.ok) {
        $('carmPass').value = '';
        $('openaiKey').value = '';
        setAuthLocked(false);
        if (result.course_detection_started) {
          showSystemNotice('Credenciales guardadas. Detectando cursos CARM...');
        }
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
    $('saveSelectedCoursesBtn').onclick = saveSelectedCourses;
    $('saveAutomationBtn').onclick = saveAutomation;
    $('saveStartupBtn').onclick = saveStartup;
    $('checkHealthBtn').onclick = checkHealth;
    $('saveOpenaiBtn').onclick = () => saveOpenAIConfig(false);
    $('checkOpenaiBtn').onclick = () => saveOpenAIConfig(true);
    $('scanNowBtn').onclick = () => {
      toggleSettings(false);
      run('detect_course');
    };
    $('detectCoursesBtn').onclick = () => {
      toggleSettings(false);
      run('detect_courses');
    };
    $('pauseScanBtn').onclick = () => setAutomationInterval(0, true);
    $('resumeScanBtn').onclick = () => setAutomationInterval(60);
    $('useDetectedCourseBtn').onclick = () => {
      if (!$('detectedCourse').value) return;
      saveCourse($('detectedCourse').value);
    };
    $('detectedCourse').onchange = () => {
      if ($('detectedCourse').value) $('courseUrl').value = $('detectedCourse').value;
    };
    $('activeCourseSelect').onchange = () => {
      if ($('activeCourseSelect').value) saveCourse($('activeCourseSelect').value);
    };
    $('advancedAction').onchange = updateAdvancedForm;
    $('runAdvancedBtn').onclick = () => {
      const action = $('advancedAction').value;
      if (action === 'delete_cache' && !confirm('Borrar la cache local del curso')) return;
      toggleSettings(false);
      run(action, {
        unidad: $('advancedUnidad').value,
        actividad: $('advancedActividad').value,
        max_entregas: $('advancedMaxEntregas').value,
        json_path: $('importJsonPath').value
      });
    };
    $('publishCheck').onchange = safeRefresh;
    $('jsonPath').onchange = safeRefresh;
    $('prepareMode').onchange = updateActivityOptions;
    $('unidad').onchange = updateActivityOptions;
    $('advancedUnidad').onchange = updateAdvancedActivityOptions;
    updateAdvancedForm();
    window.addEventListener('hashchange', handleHashTarget);
    setInterval(safeRefresh, 5000);
    safeRefresh();
    setTimeout(handleHashTarget, 300);
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
        if parsed.path == "/api/health":
            send_json(self, local_health_status())
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
                if ok:
                    ok, openai_message = save_openai_config(
                        str(body.get("openai_api_key") or ""),
                        str(body.get("openai_model") or ""),
                        str(body.get("correction_mode") or ""),
                    )
                    message = f"{message} {openai_message}" if ok else openai_message
                detection_started = False
                detection_message = ""
                if ok:
                    detection_started, detection_message = RUNNER.start("detect_courses", ["--listar-cursos-carm"])
                    if detection_started:
                        message = f"{message} Detectando cursos CARM en segundo plano."
                    else:
                        message = f"{message} No se ha iniciado autodeteccion de cursos: {detection_message}"
                audit_ui_event("guardar_credenciales_carm", "ok" if ok else "error", usuario=body.get("usuario", ""))
                send_json(
                    self,
                    {
                        "ok": ok,
                        "message": message,
                        "course_detection_started": detection_started,
                    },
                    200 if ok else 400,
                )
            except Exception as exc:
                audit_ui_event("guardar_credenciales_carm", "error", error=exc)
                send_json(self, {"ok": False, "message": str(exc)}, 400)
            return
        if not carm_credentials_present() and parsed.path != "/api/auth/logout":
            send_json(self, {"ok": False, "auth_required": True, "message": "Credenciales CARM requeridas."}, HTTPStatus.UNAUTHORIZED)
            return
        if parsed.path == "/api/stop":
            audit_ui_event("detener_tarea", tarea=RUNNER.action)
            send_json(self, {"ok": RUNNER.stop()})
            return
        if parsed.path == "/api/restart":
            audit_ui_event("reiniciar_app")
            send_json(self, {"ok": True, "message": "Reiniciando Corrector CARM..."})
            restart_app()
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
                        "base_pendientes_dir": str(BASE_PENDIENTES_DIR),
                        "base_temporal_dir": str(BASE_TEMPORAL_DIR),
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
                save_course_scope_config(bool(body.get("course_scoped_dirs")))
                url = save_course_url(str(body.get("course") or ""))
                configure_work_dirs()
                scope = "carpetas separadas por curso" if course_scoped_dirs_enabled() else "carpetas globales"
                dashboard_saved = DASHBOARD_URL_RE.fullmatch(str(body.get("course") or "").strip()) is not None
                audit_ui_event("configurar_curso", course_id=course_id_from_url(url), dashboard=dashboard_saved)
                active_label = course_id_from_url(url) or "sin seleccionar"
                scan_started = False
                scan_message = ""
                if active_label != "sin seleccionar" and not dashboard_saved and not has_cached_course_data():
                    scan_started, scan_message = schedule_course_scan_if_missing(active_label)
                message = (
                    f"Area personal guardada para detectar cursos. Curso activo: {active_label} ({scope})."
                    if dashboard_saved
                    else f"Curso activo guardado: {active_label} ({scope})."
                )
                if scan_message:
                    message = f"{message} {scan_message}"
                elif not dashboard_saved:
                    message = f"{message} Cache didactica disponible."
                send_json(
                    self,
                    {
                        "ok": True,
                        "message": message,
                        "course_url": url,
                        "course_id": course_id_from_url(url),
                        "dashboard_url": dashboard_url(),
                        "course_scoped_dirs": course_scoped_dirs_enabled(),
                        "pendientes_dir": str(PENDIENTES_DIR),
                        "temporal_dir": str(TEMPORAL_DIR),
                        "course_scan_started": scan_started,
                    },
                )
            except Exception as exc:
                send_json(self, {"ok": False, "message": str(exc)}, 400)
            return
        if parsed.path == "/api/config/selected-courses":
            try:
                body = read_json_body(self)
                raw_ids = body.get("course_ids", [])
                if not isinstance(raw_ids, list):
                    raw_ids = []
                ids = save_selected_course_ids([str(item) for item in raw_ids])
                audit_ui_event("configurar_cursos_auto", cursos=",".join(ids))
                message = f"Cursos seleccionados para autoprompteo: {', '.join(ids)}."
                if len(ids) > 1 and not course_scoped_dirs_enabled():
                    message += " Activa 'Separar carpetas por curso' antes de autopromptear varios cursos."
                send_json(self, {"ok": True, "message": message, "selected_course_ids": ids})
            except Exception as exc:
                send_json(self, {"ok": False, "message": str(exc)}, 400)
            return
        if parsed.path == "/api/config/automation":
            try:
                body = read_json_body(self)
                interval = save_automation_config(
                    body.get("auto_scan_interval_minutes", DEFAULT_SCAN_INTERVAL_MINUTES),
                    periodic_auto_prepare=bool(body.get("periodic_auto_prepare")),
                    auto_prepare_interval=body.get("auto_prepare_interval_minutes", DEFAULT_AUTO_PREPARE_INTERVAL_MINUTES),
                    auto_prepare_time=body.get("auto_prepare_time", ""),
                )
                prepare_interval = auto_prepare_interval_minutes()
                prepare_time = auto_prepare_time_of_day()
                if periodic_auto_prepare_enabled():
                    detalles = []
                    if prepare_interval > 0:
                        detalles.append(f"cada {prepare_interval} minutos")
                    if prepare_time:
                        detalles.append(f"a las {prepare_time}")
                    message = "Autoprompteo periodico guardado: " + (", ".join(detalles) if detalles else "activo, sin horario configurado.")
                else:
                    message = (
                        "Autodeteccion periodica desactivada."
                        if interval == 0
                        else f"Autodeteccion guardada: cada {interval} minutos."
                    )
                audit_ui_event(
                    "configurar_autoescaneo",
                    intervalo_minutos=interval,
                    periodic_auto_prepare=periodic_auto_prepare_enabled(),
                    auto_prepare_interval_minutes=prepare_interval,
                    auto_prepare_time=prepare_time,
                )
                send_json(
                    self,
                    {
                        "ok": True,
                        "message": message,
                        "auto_scan_interval_minutes": interval,
                        "periodic_auto_prepare": periodic_auto_prepare_enabled(),
                        "auto_prepare_interval_minutes": prepare_interval,
                        "auto_prepare_time": prepare_time,
                    },
                )
            except Exception as exc:
                send_json(self, {"ok": False, "message": str(exc)}, 400)
            return
        if parsed.path == "/api/config/startup":
            try:
                body = read_json_body(self)
                enabled = bool(body.get("enabled"))
                auto_correct = bool(body.get("auto_correct"))
                if enabled:
                    path = install_startup(auto_correct=auto_correct)
                    message = (
                        "Arranque de Windows guardado con autopreparacion de prompts."
                        if auto_correct
                        else "Arranque de Windows guardado sin autopreparacion de prompts."
                    )
                    audit_ui_event("configurar_arranque_windows", "instalado", auto_correct=auto_correct)
                    send_json(
                        self,
                        {
                            "ok": True,
                            "message": message,
                            "startup_path": str(path),
                            "startup_installed": True,
                            "startup_auto_correct_enabled": auto_correct,
                        },
                    )
                    return
                removed = uninstall_startup()
                audit_ui_event("configurar_arranque_windows", "desinstalado")
                send_json(
                    self,
                    {
                        "ok": True,
                        "message": "Arranque de Windows desactivado." if removed else "El arranque automatico ya estaba desactivado.",
                        "startup_installed": False,
                        "startup_auto_correct_enabled": False,
                    },
                )
            except Exception as exc:
                audit_ui_event("configurar_arranque_windows", "error", error=exc)
                send_json(self, {"ok": False, "message": str(exc)}, 400)
            return
        if parsed.path == "/api/config/openai":
            try:
                body = read_json_body(self)
                mode = str(body.get("correction_mode") or "")
                api_key = str(body.get("openai_api_key") or "")
                model = str(body.get("openai_model") or "")
                if bool(body.get("check_only")):
                    candidate = api_key or read_env_values().get("OPENAI_API_KEY", "")
                    ok, message = verify_openai_api(candidate, model or read_env_values().get("OPENAI_MODEL", "gpt-5-mini"))
                    audit_ui_event("comprobar_openai_api", "ok" if ok else "error")
                    send_json(self, {"ok": ok, "message": message}, 200 if ok else 400)
                    return
                ok, message = save_openai_config(api_key, model, mode)
                audit_ui_event("configurar_openai", "ok" if ok else "error", mode=mode)
                send_json(self, {"ok": ok, "message": message}, 200 if ok else 400)
            except Exception as exc:
                audit_ui_event("configurar_openai", "error", error=exc)
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
            audit_ui_event("ejecutar_accion", "iniciada" if ok else "rechazada", accion=action)
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
        max_entregas = str(body.get("max_entregas") or "0").strip()
        require_allowed(max_entregas, ALLOWED_MAX_ENTREGAS, "Entregas por prompt")
        args = [
            "--preparar-carm-codex",
            "--pendientes",
            str(PENDIENTES_DIR),
            "--temporal",
            str(TEMPORAL_DIR),
            "--max-entregas-por-prompt",
            max_entregas,
        ]
        if modo == "course":
            return args
        if modo == "activity":
            require_allowed(actividad, allowed_activities(), "Actividad")
            args.extend(["--actividad", actividad])
            return args
        require_allowed(unidad, allowed_units(), "Unidad")
        args.extend(["--unidad", unidad])
        return args

    if action in {"preview", "publish", "assist_publish"}:
        json_path = require_allowed(
            str(body.get("json_path") or default_correction_source_path()),
            allowed_json_paths(),
            "Archivo de correcciones",
        )
        if Path(json_path).is_dir():
            raise ValueError("Para subir a CARM selecciona revision_pendiente.csv o un JSON concreto, no 'Todos los JSON pendientes'.")
        args = ["--subir-correcciones-carm", str(json_path)]
        if action == "preview":
            args.extend(["--solo-primera-previsualizacion-carm", "--mantener-navegador"])
        if action == "publish":
            raise ValueError("La publicacion automatica directa esta desactivada. Usa subida asistida con guardado humano.")
        if action == "assist_publish":
            revisar_publicacion_segura()
            args.append("--subida-asistida-carm")
            if bool(body.get("guardar_trace_subida")):
                args.append("--guardar-trace-subida")
        return args

    if action == "diagnose":
        return ["--diagnosticar-carm"]

    if action == "diagnose_evidence":
        return ["--diagnosticar-carm", "--guardar-evidencias"]

    if action == "detect_course":
        if not active_course_id():
            return ["--listar-cursos-carm"]
        return ["--cachear-curso", "--refrescar-cache"]

    if action == "detect_courses":
        return ["--listar-cursos-carm"]

    if action == "check_playwright":
        return ["--comprobar-login-carm"]

    if action in {"list_carm", "cache_course", "prepare_carm_api", "prepare_carm_codex"}:
        unidad = str(body.get("unidad") or "ud01").strip()
        max_entregas = str(body.get("max_entregas") or "0").strip()
        require_allowed(unidad, allowed_units(), "Unidad")
        require_allowed(max_entregas, ALLOWED_MAX_ENTREGAS, "Entregas por prompt")
        if action == "list_carm":
            return ["--solo-listar-carm", "--unidad", unidad]
        if action == "cache_course":
            return ["--cachear-curso", "--unidad", unidad]
        if action == "prepare_carm_api":
            return [
                "--extraer-carm",
                "--requerir-openai-api",
                "--pendientes",
                str(PENDIENTES_DIR),
                "--temporal",
                str(TEMPORAL_DIR),
                "--max-entregas-por-prompt",
                max_entregas,
                "--unidad",
                unidad,
            ]
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

    if action == "check_openai":
        return ["--comprobar-openai-api"]

    if action == "solve_prompts_api":
        return [
            "--pendientes",
            str(PENDIENTES_DIR),
            "--temporal",
            str(TEMPORAL_DIR),
            "--corregir-prompts-openai",
        ]

    if action == "prepare_carm_codex_activity":
        actividad = str(body.get("actividad") or "").strip()
        max_entregas = str(body.get("max_entregas") or "0").strip()
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

    if action == "import_codex":
        json_path = str(body.get("json_path") or "").strip()
        require_allowed(json_path, allowed_json_paths(), "JSON")
        return [
            "--pendientes",
            str(PENDIENTES_DIR),
            "--temporal",
            str(TEMPORAL_DIR),
            "--importar-correcciones-codex",
            json_path,
        ]

    if action == "delete_cache":
        return ["--borrar-cache-curso"]

    raise ValueError("Accion no permitida.")


def startup_cmd_path() -> Path:
    appdata = os.getenv("APPDATA")
    if not appdata:
        raise RuntimeError("No se pudo localizar APPDATA para la carpeta de inicio.")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Corrector CARM.cmd"


def install_startup(auto_correct: bool = False) -> Path:
    venv_pythonw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    current_pythonw = Path(sys.executable).with_name("pythonw.exe")
    runner = (
        venv_pythonw
        if venv_pythonw.exists()
        else (venv_python if venv_python.exists() else (current_pythonw if current_pythonw.exists() else Path(sys.executable)))
    )
    cmd_path = startup_cmd_path()
    cmd_path.parent.mkdir(parents=True, exist_ok=True)
    auto_correct_arg = " --auto-correct" if auto_correct else ""
    cmd_path.write_text(
        "@echo off\n"
        f'cd /d "{ROOT}"\n'
        f'start "" /min "{runner}" "{ROOT / "interfaz_app.py"}" --tray --host {DEFAULT_HOST} --port {DEFAULT_PORT} --no-browser{auto_correct_arg}\n',
        encoding="utf-8",
    )
    return cmd_path


def startup_auto_correct_enabled() -> bool:
    try:
        path = startup_cmd_path()
        return path.exists() and "--auto-correct" in path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False


def repair_startup_if_installed() -> bool:
    # No reactivamos --auto-correct de forma silenciosa: arrancar la app y
    # autopreparar prompts son decisiones separadas del usuario.
    return False


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
        message = (
            "pystray/Pillow no estan instalados en la venv; no se puede crear icono de bandeja. "
            "Instala requirements.txt y reinicia la app."
        )
        print(message)
        notify("Corrector CARM", message, target="settings")
        if startup_scan:
            start_startup_work()
        server.serve_forever()
        return

    def open_ui(icon=None, item=None) -> None:
        webbrowser.open(url)

    def quit_app(icon, item=None) -> None:
        server.shutdown()
        icon.stop()

    def restart_from_tray(icon, item=None) -> None:
        notify("Corrector CARM", "Reiniciando aplicacion...", target="activity")
        restart_app(delay=0.2)

    icon = pystray.Icon(
        "Corrector CARM",
        tray_image(),
        "Corrector CARM",
        menu=pystray.Menu(
            pystray.MenuItem("Abrir interfaz", open_ui, default=True),
            pystray.MenuItem("Reiniciar app", restart_from_tray),
            pystray.MenuItem("Cerrar programa", quit_app),
        ),
    )
    TRAY_ICON = icon
    threading.Thread(target=server.serve_forever, daemon=True).start()
    notify_pending_publication()
    if startup_scan:
        start_startup_work()
    icon.run()


def start_periodic_scan(disabled: bool) -> None:
    if disabled:
        return

    def loop() -> None:
        while True:
            time.sleep(60)
            interval = auto_scan_interval_minutes()
            if not carm_credentials_present():
                continue
            snapshot = RUNNER.snapshot()
            if snapshot.get("running"):
                continue
            prepare_reason = auto_prepare_due()
            if prepare_reason:
                ok, _ = start_auto_prepare()
                if ok:
                    mark_auto_prepare_run(prepare_reason)
                    notify("Corrector CARM", f"Autoprompteo periodico iniciado por {prepare_reason}.", target="activity")
                continue
            if interval <= 0:
                continue
            if RUNNER.last_detection_at <= 0:
                RUNNER.last_detection_at = time.time()
                continue
            if time.time() - RUNNER.last_detection_at < interval * 60:
                continue
            selected = selected_courses_for_auto()
            if len(selected) > 1 and course_scoped_dirs_enabled():
                missing = [course for course in selected if not cache_path_for_course_id(course["id"])]
                if not missing:
                    continue
                ok, _ = start_detect_course_for_course(missing[0])
                if ok:
                    notify("Corrector CARM", f"Deteccion periodica iniciada para curso {missing[0]['id']}.", target="activity")
                continue
            if not active_course_id():
                ok, _ = RUNNER.start("detect_courses", ["--listar-cursos-carm"])
                if ok:
                    notify("Corrector CARM", "Deteccion periodica de cursos CARM iniciada.", target="activity")
                continue
            if has_cached_course_data():
                continue
            ok, _ = RUNNER.start("detect_course", ["--cachear-curso"])
            if ok:
                notify("Corrector CARM", "Primera deteccion periodica de CARM iniciada.", target="activity")

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
    parser.add_argument(
        "--install-startup-auto-correct",
        action="store_true",
        help="Al instalar el arranque de Windows, activa tambien autoprompteo al iniciar.",
    )
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
    global AUTO_CORRECT_AFTER_SCAN, APP_URL
    AUTO_CORRECT_AFTER_SCAN = args.auto_correct and not args.no_auto_correct

    if args.install_startup:
        path = install_startup(auto_correct=args.install_startup_auto_correct)
        print(f"Arranque automatico instalado: {path}")
        if args.install_startup_auto_correct:
            print("Autoprompteo al inicio activado en el arranque automatico.")
        return
    if args.uninstall_startup:
        removed = uninstall_startup()
        print("Arranque automatico eliminado." if removed else "No habia arranque automatico instalado.")
        return

    try:
        server, active_port, attempted_ports = create_local_server(args.host, args.port)
        global APP_SERVER
        APP_SERVER = server
    except OSError as exc:
        print(f"No se pudo iniciar la interfaz local: {exc}")
        print("Cierra otra instancia del Corrector CARM o prueba con --port 0 para usar un puerto libre automatico.")
        return
    url_host = "127.0.0.1" if args.host in {"0.0.0.0", "::"} else args.host
    url = f"http://{url_host}:{active_port}"
    APP_URL = url
    save_app_config({"last_local_url": url, "last_local_port": active_port})
    print(f"Interfaz Corrector CARM: {url}")
    if args.port and active_port != args.port:
        print(f"Puerto {args.port} ocupado; se ha usado automaticamente el puerto {active_port}.")
    notify_pending_publication()
    repair_startup_if_installed()
    start_periodic_scan(disabled=args.no_periodic_scan)
    if args.tray:
        if not args.no_browser:
            threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        run_tray(server, url, startup_scan=not args.no_startup_scan)
        return
    if not args.no_startup_scan:
        start_startup_work()
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
