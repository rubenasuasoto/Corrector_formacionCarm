from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
TEMPORAL_DIR = Path(r"C:\temp\vscodec\temporal")
PROMPTS_DIR = TEMPORAL_DIR / "prompts_codex"
COMBINED_JSON = PROMPTS_DIR / "correcciones_codex_combinadas.json"
REVISION_CSV = TEMPORAL_DIR / "revision_pendiente.csv"
AGENTE_LOG = ROOT / "logs_correcciones" / "agente.log"


class TaskRunner:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.process: subprocess.Popen[str] | None = None
        self.action = ""
        self.started_at = 0.0
        self.exit_code: int | None = None
        self.lines: list[str] = []

    def start(self, action: str, args: list[str]) -> tuple[bool, str]:
        with self.lock:
            if self.process and self.process.poll() is None:
                return False, "Ya hay un proceso en marcha."

            self.action = action
            self.started_at = time.time()
            self.exit_code = None
            self.lines = [f"$ {sys.executable} corrector_agente.py {' '.join(args)}"]
            self.process = subprocess.Popen(
                [sys.executable, "corrector_agente.py", *args],
                cwd=str(ROOT),
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
            with self.lock:
                self.lines.append(line.rstrip())
                self.lines = self.lines[-700:]
        code = proc.wait()
        with self.lock:
            self.exit_code = code
            self.lines.append(f"[proceso terminado con codigo {code}]")

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
            return {
                "running": running,
                "action": self.action,
                "started_at": self.started_at,
                "elapsed": round(time.time() - self.started_at, 1) if self.started_at else 0,
                "exit_code": self.exit_code,
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
      <span id="statusBadge" class="badge idle">Parado</span>
      <button id="refreshBtn">Actualizar</button>
    </div>
  </header>
  <main>
    <div class="stack">
      <section>
        <h2>Preparar Correcciones</h2>
        <div class="row">
          <div class="field">
            <label for="unidad">Unidad</label>
            <input id="unidad" value="ud01">
          </div>
          <div class="field">
            <label for="maxEntregas">Entregas por prompt</label>
            <input id="maxEntregas" type="number" min="1" max="20" value="6">
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
        <input id="jsonPath" value="C:\temp\vscodec\temporal\prompts_codex\correcciones_codex_combinadas.json">
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
  <script>
    const $ = (id) => document.getElementById(id);

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

    function setBusy(running) {
      $('prepareBtn').disabled = running;
      $('previewBtn').disabled = running;
      $('publishBtn').disabled = running || !$('publishCheck').checked;
      $('stopBtn').disabled = !running;
    }

    async function refresh() {
      const status = await api('/api/status');
      const state = await api('/api/state');
      const badge = $('statusBadge');
      badge.className = 'badge ' + (status.running ? '' : (status.exit_code && status.exit_code !== 0 ? 'err' : 'idle'));
      badge.textContent = status.running ? 'Ejecutando' : (status.exit_code && status.exit_code !== 0 ? 'Error' : 'Parado');
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
      const result = await api('/api/run', {method: 'POST', body: JSON.stringify({action, ...body})});
      if (!result.ok) alert(result.message || 'No se pudo iniciar');
      await refresh();
    }

    $('prepareBtn').onclick = () => run('prepare', {unidad: $('unidad').value, max_entregas: $('maxEntregas').value});
    $('previewBtn').onclick = () => run('preview', {json_path: $('jsonPath').value});
    $('publishBtn').onclick = () => {
      if (!$('publishCheck').checked) return alert('Marca la confirmación antes de publicar.');
      run('publish', {json_path: $('jsonPath').value});
    };
    $('stopBtn').onclick = async () => { await api('/api/stop', {method:'POST'}); await refresh(); };
    $('refreshBtn').onclick = refresh;
    $('publishCheck').onchange = refresh;
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
        send_json(self, {"error": "not_found"}, 404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/stop":
            send_json(self, {"ok": RUNNER.stop()})
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
        unidad = str(body.get("unidad") or "ud01").strip()
        max_entregas = str(body.get("max_entregas") or "6").strip()
        if not unidad:
            raise ValueError("Unidad requerida.")
        if not max_entregas.isdigit():
            raise ValueError("Entregas por prompt debe ser un numero.")
        return ["--flujo-correccion-carm", "--unidad", unidad, "--max-entregas-por-prompt", max_entregas]

    if action in {"preview", "publish"}:
        json_path = Path(str(body.get("json_path") or COMBINED_JSON))
        args = ["--subir-correcciones-carm", str(json_path)]
        if action == "publish":
            args.append("--publicar-carm")
        return args

    raise ValueError("Accion no permitida.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Interfaz web local del corrector CARM.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"Interfaz Corrector CARM: {url}")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
