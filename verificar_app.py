from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def safe_print(value: str = "") -> None:
    try:
        print(value)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        print(value.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def run_step(name: str, command: list[str], timeout: int = 120) -> bool:
    safe_print(f"\n==> {name}")
    proc = subprocess.run(
        command,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    output = proc.stdout.strip()
    if output:
        lines = output.splitlines()
        if len(lines) > 40:
            lines = [*lines[:20], "...", *lines[-20:]]
        safe_print("\n".join(lines))
    if proc.returncode != 0:
        safe_print(f"ERROR: {name} fallo con codigo {proc.returncode}.")
        return False
    safe_print(f"OK: {name}")
    return True


def print_health(operacion: bool) -> bool:
    safe_print("\n==> Estado local")
    import interfaz_app as app

    release = app.release_info()
    dirty = " con cambios locales" if release.get("dirty") else ""
    safe_print(f"Version: {release.get('version')} ({release.get('commit')}{dirty})")
    health = app.local_health_status()
    ok = True
    for check in health["checks"]:
        required = bool(check.get("required"))
        if not operacion and check["name"] in {"Credenciales CARM", "Curso activo"}:
            required = False
        status = "OK" if check.get("ok") else ("PENDIENTE" if required else "OPCIONAL")
        safe_print(f"[{status}] {check['name']}: {check.get('message', '')}")
        if required and not check.get("ok"):
            ok = False
    safe_print(f"OK: {health['message']}" if ok else "ERROR: Hay puntos obligatorios pendientes.")
    return ok


def _request_json(url: str, token: str | None = None) -> tuple[int, dict]:
    headers = {}
    if token:
        headers["X-Corrector-Token"] = token
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(raw or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            payload = {"message": raw}
        return exc.code, payload


def check_local_endpoints() -> bool:
    safe_print("\n==> Endpoints locales")
    import interfaz_app as app

    server, port, _ = app.create_local_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    try:
        status, _ = _request_json(f"{base_url}/api/auth")
        if status != 403:
            safe_print(f"ERROR: /api/auth sin token devolvio {status}, se esperaba 403.")
            return False
        status, auth = _request_json(f"{base_url}/api/auth", app.API_TOKEN)
        if status != 200 or "configured" not in auth:
            safe_print(f"ERROR: /api/auth con token devolvio {status}.")
            return False
        status, health = _request_json(f"{base_url}/api/health", app.API_TOKEN)
        if status != 200 or "checks" not in health:
            safe_print(f"ERROR: /api/health con token devolvio {status}.")
            return False
        safe_print("OK: token local y endpoints basicos responden correctamente.")
        return True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verificacion local del Corrector CARM.")
    parser.add_argument(
        "--instalacion",
        action="store_true",
        help="No exige credenciales CARM ni curso activo; util justo despues de instalar.",
    )
    parser.add_argument(
        "--sin-prueba-offline",
        action="store_true",
        help="Compatibilidad: la prueba offline antigua fue retirada.",
    )
    parser.add_argument(
        "--sin-endpoints",
        action="store_true",
        help="Omite comprobacion del servidor local y token.",
    )
    args = parser.parse_args()

    ok = True
    ok &= run_step(
        "Compilacion Python",
        [
            sys.executable,
            "-m",
            "py_compile",
            "interfaz_app.py",
            "corrector_agente.py",
        ],
    )
    ok &= print_health(operacion=not args.instalacion)
    if not args.sin_endpoints:
        ok &= check_local_endpoints()

    if ok:
        safe_print("\nVerificacion completada correctamente.")
        return 0
    safe_print("\nVerificacion completada con incidencias.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
