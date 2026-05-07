from __future__ import annotations

import argparse
import os
import json
import re
import sqlite3
import subprocess
import sys
import threading
import time
import webbrowser
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
TEMPORAL_DIR = Path(r"C:\temp\vscodec\temporal")
PROMPTS_DIR = TEMPORAL_DIR / "prompts_codex"
COMBINED_JSON = PROMPTS_DIR / "correcciones_codex_combinadas.json"
REVISION_CSV = TEMPORAL_DIR / "revision_pendiente.csv"
AGENTE_LOG = ROOT / "logs_correcciones" / "agente.log"
ENV_PATH = ROOT / ".env"
CARM_STORAGE_STATE = ROOT / "cache_carm" / "carm_storage_state.json"
ALLOWED_UNITS = {f"ud{i:02d}" for i in range(1, 16)}
ALLOWED_MAX_ENTREGAS = {str(i) for i in range(1, 21)}
ALLOWED_ACTIVITIES = {f"ud{unit:02d}cp{case:02d}" for unit in range(1, 16) for case in range(1, 16)}
ALLOWED_JSON_PATHS = {
    str(COMBINED_JSON),
    str(PROMPTS_DIR / "prompt_ud01cp01_correccion.json"),
    str(PROMPTS_DIR / "prompt_ud01cp02_correccion.json"),
    str(PROMPTS_DIR / "prompt_ud02cp03_correccion.json"),
}
ALLOWED_CONTEXT_PATHS = {
    str(ROOT / "tmp_prueba" / "manual_ud01.txt"),
}
UNIT_RE = re.compile(r"^ud\d{2}$")
ACTIVITY_RE = re.compile(r"^ud\d{2}cp\d{2}$")
TRAY_ICON = None
AUTO_CORRECT_AFTER_SCAN = False
AUTO_CORRECT_ARGS = ["--flujo-correccion-carm", "--max-entregas-por-prompt", "6"]


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
    write_env_values({"CARM_USUARIO": None, "CARM_CONTRASENA": None})
    if CARM_STORAGE_STATE.exists():
        CARM_STORAGE_STATE.unlink()


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
            env = os.environ.copy()
            if action in {"detect_course", "auto_correct"}:
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
        has_error = False
        with self.lock:
            self.exit_code = code
            self.lines.append(f"[proceso terminado con codigo {code}]")
            has_error = any(" - ERROR - " in line or line.startswith("ERROR") for line in self.lines)
            should_auto_correct = (
                AUTO_CORRECT_AFTER_SCAN
                and self.action == "detect_course"
                and code == 0
                and not has_error
            )
        if has_error:
            notify("Corrector CARM", "Hay errores en la ultima tarea. Abre la interfaz para revisar el log.")
        elif self.action == "auto_correct":
            notify("Corrector CARM", "Correccion automatica terminada. Revisa el CSV antes de publicar.")
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
            return {
                "running": running,
                "action": self.action,
                "started_at": self.started_at,
                "elapsed": round(time.time() - self.started_at, 1) if self.started_at else 0,
                "exit_code": self.exit_code,
                "has_error": has_error,
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


def file_info(path: Path) -> dict:
    return {
        "path": str(path),
        "exists": path.exists(),
        "modified": path.stat().st_mtime if path.exists() else 0,
        "size": path.stat().st_size if path.exists() else 0,
    }


def latest_log_lines(path: Path, limit: int = 80) -> list[str]:
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except Exception as exc:
        return [f"No se pudo leer el log: {exc}"]


def _cache_paths() -> list[Path]:
    cache_dir = ROOT / "cache_carm"
    if not cache_dir.exists():
        return []
    return sorted(cache_dir.glob("curso_*.sqlite"), key=lambda p: p.stat().st_mtime, reverse=True)


def course_options() -> dict:
    units: dict[str, str] = {}
    activities: dict[str, dict] = {}
    cache_path = ""
    cache_modified = 0.0
    didactic_units = 0
    for path in _cache_paths()[:1]:
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
                for codigo, unidad, nombre in con.execute(
                    "SELECT codigo, COALESCE(unidad_codigo, ''), COALESCE(nombre, '') FROM actividad ORDER BY codigo"
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
                        }
        except sqlite3.Error:
            continue
        break

    if not units:
        units = {codigo: codigo.upper() for codigo in sorted(ALLOWED_UNITS)}
    if not activities:
        activities = {
            codigo: {"codigo": codigo, "unidad": codigo[:4], "nombre": codigo.upper()}
            for codigo in sorted(ALLOWED_ACTIVITIES)
            if codigo in {"ud01cp01", "ud01cp02", "ud02cp03"}
        }

    return {
        "source": "cache_didactica" if cache_path else "fallback",
        "cache_path": cache_path,
        "cache_modified": cache_modified,
        "didactic_units": didactic_units,
        "units": [{"codigo": codigo, "nombre": nombre} for codigo, nombre in sorted(units.items())],
        "activities": sorted(activities.values(), key=lambda item: item["codigo"]),
    }


def project_state() -> dict:
    prompts = sorted(PROMPTS_DIR.glob("prompt_*.md")) if PROMPTS_DIR.exists() else []
    corrections = sorted(PROMPTS_DIR.glob("*_correccion.json")) if PROMPTS_DIR.exists() else []
    return {
        "combined": file_info(COMBINED_JSON),
        "revision_csv": file_info(REVISION_CSV),
        "prompts_dir": str(PROMPTS_DIR),
        "temporal_dir": str(TEMPORAL_DIR),
        "prompts": [file_info(p) for p in prompts],
        "corrections": [file_info(p) for p in corrections],
        "agent_log": latest_log_lines(AGENTE_LOG),
    }


def allowed_units() -> set[str]:
    options = course_options()
    detected = {item["codigo"] for item in options["units"]}
    return detected if options["source"] == "cache_didactica" and detected else ALLOWED_UNITS


def allowed_activities() -> set[str]:
    options = course_options()
    detected = {item["codigo"] for item in options["activities"]}
    return detected if options["source"] == "cache_didactica" and detected else ALLOWED_ACTIVITIES


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
      --bg: #f6f7f4;
      --panel: #ffffff;
      --ink: #1d2524;
      --muted: #66736f;
      --line: #d9ded8;
      --green: #1f7a5b;
      --green-soft: #e8f4ee;
      --amber: #a86200;
      --red: #b42318;
      --blue: #2f5f95;
      --shadow: 0 1px 2px rgba(16, 24, 40, .06);
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
      height: 56px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 22px;
      border-bottom: 1px solid var(--line);
      background: #fbfcfa;
    }
    h1 { font-size: 18px; margin: 0; font-weight: 650; }
    h2 { font-size: 14px; margin: 0 0 12px; font-weight: 650; }
    main {
      display: grid;
      grid-template-columns: minmax(320px, 420px) 1fr;
      gap: 16px;
      padding: 16px;
      max-width: 1380px;
      margin: 0 auto;
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 14px;
    }
    .stack { display: grid; gap: 12px; }
    .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .split { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
    label { color: var(--muted); font-size: 12px; display: block; margin-bottom: 4px; }
    input, select {
      width: 100%;
      height: 34px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 6px 8px;
      background: #fff;
      color: var(--ink);
    }
    .field { flex: 1 1 130px; min-width: 0; }
    button {
      height: 34px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--ink);
      padding: 0 12px;
      cursor: pointer;
      font-weight: 600;
    }
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
    .badge.idle { background: #eef1f0; color: var(--muted); }
    .badge.err { background: #fff1f0; color: var(--red); }
    .path {
      font-family: Consolas, "Courier New", monospace;
      background: #f3f5f3;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px;
      overflow-wrap: anywhere;
      color: #31413d;
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
      background: #fbfcfa;
    }
    .item small, .muted { color: var(--muted); }
    pre {
      min-height: 420px;
      max-height: calc(100vh - 190px);
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
    .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
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
    @media (max-width: 900px) {
      main { grid-template-columns: 1fr; }
      .grid2 { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Corrector CARM</h1>
    <div class="row">
      <span id="courseSummary" class="muted"></span>
      <span id="statusBadge" class="badge idle">Parado</span>
      <button id="refreshBtn">Actualizar</button>
      <button id="logoutBtn">Cerrar sesion CARM</button>
      <button id="settingsBtn" class="icon" title="Configuracion" aria-label="Configuracion">⚙</button>
    </div>
  </header>
  <main>
    <div class="stack">
      <section>
        <h2>Preparar Correcciones</h2>
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
        <div class="row" style="margin-top:12px">
          <button class="primary" id="prepareBtn">Preparar con Codex</button>
          <button class="danger" id="stopBtn">Detener</button>
        </div>
      </section>

      <section>
        <h2>Subida A CARM</h2>
        <label for="jsonPath">JSON de correcciones</label>
        <select id="jsonPath">
          <option value="C:\temp\vscodec\temporal\prompts_codex\correcciones_codex_combinadas.json">correcciones_codex_combinadas.json</option>
          <option value="C:\temp\vscodec\temporal\prompts_codex\prompt_ud01cp01_correccion.json">prompt_ud01cp01_correccion.json</option>
          <option value="C:\temp\vscodec\temporal\prompts_codex\prompt_ud01cp02_correccion.json">prompt_ud01cp02_correccion.json</option>
          <option value="C:\temp\vscodec\temporal\prompts_codex\prompt_ud02cp03_correccion.json">prompt_ud02cp03_correccion.json</option>
        </select>
        <div class="row" style="margin-top:12px">
          <button id="previewBtn">Previsualizar</button>
          <button class="warn" id="publishBtn">Publicar</button>
        </div>
        <label class="check" style="margin-top:10px">
          <input type="checkbox" id="publishCheck">
          Confirmo que he revisado las correcciones
        </label>
      </section>

      <section>
        <h2>Salidas</h2>
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
        <h2>Archivos Recientes</h2>
        <div class="grid2">
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

    <section>
      <div class="split">
        <h2>Actividad</h2>
        <span id="elapsed" class="muted"></span>
      </div>
      <pre id="logBox"></pre>
    </section>
  </main>

  <div id="authModal" class="modal-backdrop" aria-hidden="true">
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="authTitle">
      <div class="split">
        <h2 id="authTitle">Configurar CARM</h2>
        <span class="muted">Primera configuracion</span>
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
        <div>
          <label for="advancedAction">Comando</label>
          <select id="advancedAction">
            <option value="detect_course">Actualizar datos didacticos desde CARM</option>
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
              <option value="C:\Users\ruben\OneDrive\Escritorio\agente\tmp_prueba\manual_ud01.txt">tmp_prueba\manual_ud01.txt</option>
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
    const advancedHints = {
      diagnose: 'Entra en CARM, genera diagnostico limpio y no descarga entregas.',
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
      diagnose_evidence: '--diagnosticar-carm --guardar-evidencias',
      detect_course: '--cachear-curso',
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

    async function api(path, options = {}) {
      const res = await fetch(path, {
        headers: {'Content-Type': 'application/json'},
        ...options
      });
      return await res.json();
    }

    function fmtFile(file) {
      const name = file.path.split(/[\\/]/).pop();
      const kb = file.exists ? Math.max(1, Math.round(file.size / 1024)) + ' KB' : 'no existe';
      return `<div class="item"><span>${name}<br><small>${file.path}</small></span><small>${kb}</small></div>`;
    }

    function optionHtml(value, label) {
      return `<option value="${value}">${label}</option>`;
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
      const unitHtml = courseOptions.units.map((unit) => optionHtml(unit.codigo, `${unit.codigo} · ${unit.nombre}`)).join('');
      fillSelect($('unidad'), unitHtml, $('unidad').value || 'ud01');
      fillSelect($('advancedUnidad'), unitHtml, $('advancedUnidad').value || $('unidad').value);
      updateActivityOptions();
      updateAdvancedActivityOptions();
      const source = courseOptions.source === 'cache_didactica' ? 'cache didactica' : 'valores base';
      $('courseSummary').textContent = `${courseOptions.units.length} unidades · ${courseOptions.activities.length} casos · ${source}`;
    }

    async function loadAuth() {
      authState = await api('/api/auth');
      $('logoutBtn').disabled = !authState.configured;
      toggleAuth(!authState.configured);
      return authState;
    }

    function updateActivityOptions() {
      const unit = $('unidad').value;
      const activities = activitiesForUnit(unit);
      const source = activities.length ? activities : courseOptions.activities;
      fillSelect(
        $('actividad'),
        source.map((act) => optionHtml(act.codigo, `${act.codigo} · ${act.nombre}`)).join(''),
        $('actividad').value
      );
      $('activityField').style.display = $('prepareMode').value === 'activity' ? '' : 'none';
    }

    function updateAdvancedActivityOptions() {
      fillSelect(
        $('advancedActividad'),
        courseOptions.activities.map((act) => optionHtml(act.codigo, `${act.codigo} · ${act.nombre}`)).join(''),
        $('advancedActividad').value || $('actividad').value
      );
      fillSelect(
        $('localActivity'),
        courseOptions.activities.map((act) => optionHtml(act.codigo, act.codigo)).join(''),
        $('localActivity').value || $('actividad').value
      );
    }

    function setBusy(running) {
      const locked = running || !authState.configured;
      $('prepareBtn').disabled = locked;
      $('previewBtn').disabled = locked;
      $('publishBtn').disabled = locked || !$('publishCheck').checked;
      $('stopBtn').disabled = !running;
      $('runAdvancedBtn').disabled = locked;
    }

    function toggleAuth(open) {
      $('authModal').classList.toggle('open', open);
      $('authModal').setAttribute('aria-hidden', open ? 'false' : 'true');
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

    async function refresh() {
      await loadAuth();
      const status = await api('/api/status');
      const state = await api('/api/state');
      await loadOptions();
      const badge = $('statusBadge');
      const failed = status.has_error || (status.exit_code && status.exit_code !== 0);
      badge.className = 'badge ' + (status.running ? '' : (failed ? 'err' : 'idle'));
      badge.textContent = status.running ? 'Ejecutando' : (failed ? 'Error' : 'Parado');
      $('elapsed').textContent = status.running ? `${status.action} · ${status.elapsed}s` : '';
      $('logBox').textContent = (status.lines || []).join('\n') || (state.agent_log || []).join('\n');
      $('logBox').scrollTop = $('logBox').scrollHeight;
      $('combinedPath').textContent = `${state.combined.path} · ${state.combined.exists ? 'listo' : 'pendiente'}`;
      $('revisionPath').textContent = `${state.revision_csv.path} · ${state.revision_csv.exists ? 'listo' : 'pendiente'}`;
      $('promptsList').innerHTML = state.prompts.length ? state.prompts.map(fmtFile).join('') : '<span class="muted">Sin prompts</span>';
      $('correctionsList').innerHTML = state.corrections.length ? state.corrections.map(fmtFile).join('') : '<span class="muted">Sin correcciones</span>';
      setBusy(status.running);
    }

    async function run(action, body = {}) {
      if (!authState.configured) {
        toggleAuth(true);
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
    $('publishBtn').onclick = () => {
      if (!$('publishCheck').checked) return alert('Marca la confirmación antes de publicar.');
      run('publish', {json_path: $('jsonPath').value});
    };
    $('stopBtn').onclick = async () => { await api('/api/stop', {method:'POST'}); await refresh(); };
    $('refreshBtn').onclick = refresh;
    $('logoutBtn').onclick = async () => {
      if (!confirm('Cerrar sesion CARM y borrar credenciales locales?')) return;
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
        await refresh();
      }
    };
    $('settingsBtn').onclick = () => toggleSettings(true);
    $('closeSettingsBtn').onclick = () => toggleSettings(false);
    $('cancelSettingsBtn').onclick = () => toggleSettings(false);
    $('settingsModal').onclick = (event) => {
      if (event.target === $('settingsModal')) toggleSettings(false);
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
    $('publishCheck').onchange = refresh;
    $('prepareMode').onchange = updateActivityOptions;
    $('unidad').onchange = updateActivityOptions;
    $('advancedUnidad').onchange = updateAdvancedActivityOptions;
    updateAdvancedForm();
    loadOptions();
    setInterval(refresh, 3000);
    refresh();
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            data = HTML.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
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
        if parsed.path == "/api/auth":
            send_json(self, auth_status())
            return
        send_json(self, {"error": "not_found"}, 404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/stop":
            send_json(self, {"ok": RUNNER.stop()})
            return
        if parsed.path == "/api/auth/save":
            try:
                body = read_json_body(self)
                ok, message = save_carm_credentials(
                    str(body.get("usuario") or ""),
                    str(body.get("contrasena") or ""),
                )
                send_json(self, {"ok": ok, "message": message}, 200 if ok else 400)
            except Exception as exc:
                send_json(self, {"ok": False, "message": str(exc)}, 400)
            return
        if parsed.path == "/api/auth/logout":
            RUNNER.stop()
            logout_carm()
            send_json(self, {"ok": True, "message": "Sesion CARM cerrada. Vuelve a introducir credenciales."})
            return
        if parsed.path != "/api/run":
            send_json(self, {"error": "not_found"}, 404)
            return

        try:
            body = read_json_body(self)
            action = str(body.get("action", ""))
            args = build_args(action, body)
            ok, message = RUNNER.start(action, args)
            send_json(self, {"ok": ok, "message": message})
        except Exception as exc:
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
        args = ["--flujo-correccion-carm", "--max-entregas-por-prompt", max_entregas]
        if modo == "activity":
            require_allowed(actividad, allowed_activities(), "Actividad")
            args.extend(["--actividad", actividad])
            return args
        require_allowed(unidad, allowed_units(), "Unidad")
        args.extend(["--unidad", unidad])
        return args

    if action in {"preview", "publish"}:
        json_path = require_allowed(str(body.get("json_path") or COMBINED_JSON), ALLOWED_JSON_PATHS, "JSON")
        args = ["--subir-correcciones-carm", str(json_path)]
        if action == "publish":
            args.append("--publicar-carm")
        return args

    if action == "diagnose":
        return ["--diagnosticar-carm"]

    if action == "diagnose_evidence":
        return ["--diagnosticar-carm", "--guardar-evidencias"]

    if action == "detect_course":
        return ["--cachear-curso"]

    if action in {"list_carm", "cache_course", "prepare_carm_codex"}:
        unidad = str(body.get("unidad") or "ud01").strip()
        max_entregas = str(body.get("max_entregas") or "6").strip()
        require_allowed(unidad, allowed_units(), "Unidad")
        require_allowed(max_entregas, ALLOWED_MAX_ENTREGAS, "Entregas por prompt")
        if action == "list_carm":
            return ["--solo-listar-carm", "--unidad", unidad]
        if action == "cache_course":
            return ["--cachear-curso", "--unidad", unidad]
        return ["--preparar-carm-codex", "--unidad", unidad, "--max-entregas-por-prompt", max_entregas]

    if action == "prepare_carm_codex_activity":
        actividad = str(body.get("actividad") or "").strip()
        max_entregas = str(body.get("max_entregas") or "6").strip()
        require_allowed(actividad, allowed_activities(), "Actividad")
        require_allowed(max_entregas, ALLOWED_MAX_ENTREGAS, "Entregas por prompt")
        return ["--preparar-carm-codex", "--actividad", actividad, "--max-entregas-por-prompt", max_entregas]

    if action == "prepare_local_prompts":
        contexto = str(body.get("contexto_unidad") or "").strip()
        actividad = str(body.get("actividad_codigo") or "").strip()
        require_allowed(contexto, ALLOWED_CONTEXT_PATHS, "Archivo de contexto")
        args = ["--contexto-unidad", contexto, "--preparar-prompts-codex"]
        if actividad:
            require_allowed(actividad, allowed_activities(), "Actividad")
            args.extend(["--actividad-codigo", actividad])
        return args

    if action == "import_codex":
        json_path = str(body.get("json_path") or "").strip()
        require_allowed(json_path, ALLOWED_JSON_PATHS, "JSON")
        return ["--importar-correcciones-codex", json_path]

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
        f'start "" "{runner}" "{ROOT / "interfaz_app.py"}" --tray --auto-correct --host 127.0.0.1 --port 8765 --no-browser\n',
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
            RUNNER.start("detect_course", ["--cachear-curso"])
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
    if startup_scan and carm_credentials_present():
        RUNNER.start("detect_course", ["--cachear-curso"])
    elif startup_scan:
        notify("Corrector CARM", "Faltan credenciales CARM. Abre la interfaz para configurarlas.")
    icon.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="Interfaz web local del corrector CARM.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
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

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"Interfaz Corrector CARM: {url}")
    if args.tray:
        if not args.no_browser:
            threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        run_tray(server, url, startup_scan=not args.no_startup_scan)
        return
    if not args.no_startup_scan and carm_credentials_present():
        ok, message = RUNNER.start("detect_course", ["--cachear-curso"])
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
