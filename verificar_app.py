from __future__ import annotations

import argparse
import csv
import json
import shutil
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


def check_textos_sin_mojibake() -> bool:
    safe_print("\n==> Codificacion de textos")
    patrones = (chr(0x00C3), chr(0x00C2), chr(0x00E2), chr(0x10E1) + chr(0x0192))
    extensiones = {".md", ".py", ".json", ".txt", ".ps1", ".cmd"}
    revisar = []
    try:
        proc = subprocess.run(
            ["git", "ls-files"],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        revisar = [ROOT / line.strip() for line in proc.stdout.splitlines() if line.strip()]
    except Exception:
        revisar = list(ROOT.glob("*.md")) + list(ROOT.glob("*.py"))

    incidencias: list[str] = []
    for path in revisar:
        if path.suffix.lower() not in extensiones and path.name != ".env.example":
            continue
        try:
            texto = path.read_text(encoding="utf-8-sig", errors="replace")
        except Exception:
            continue
        if any(patron in texto for patron in patrones):
            incidencias.append(str(path.relative_to(ROOT)))

    if incidencias:
        safe_print("ERROR: posibles textos con mojibake: " + ", ".join(incidencias[:12]))
        return False
    safe_print("OK: no se detectan secuencias mojibake en textos versionados.")
    return True


def check_javascript_panel_embebido() -> bool:
    safe_print("\n==> JavaScript del panel local")
    try:
        lines = (ROOT / "interfaz_app.py").read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        safe_print(f"ERROR: no se pudo leer interfaz_app.py: {exc}")
        return False

    incidencias: list[str] = []
    for index, line in enumerate(lines, start=1):
        if not (2600 <= index <= 3400):
            continue
        stripped = line.strip()
        next_line = lines[index].strip() if index < len(lines) else ""
        if next_line.startswith(":"):
            contexto: list[str] = []
            cursor = index - 1
            while cursor >= 1 and len(contexto) < 4:
                candidate = lines[cursor - 1].strip()
                if candidate:
                    contexto.append(candidate)
                cursor -= 1
            if not any(item == "?" or "?" in item for item in contexto):
                incidencias.append(f"{index}: posible ternario sin '?': {stripped}")
        patrones_rotos = (
            "  ''",
            "  '",
            "  `",
            "exists  ",
            "length  ",
            "checked  ",
            "current  ",
            "running  ",
            "checkOnly  ",
            "settingsOpen  ",
            "pending_publication  ",
        )
        if any(patron in stripped for patron in patrones_rotos):
            incidencias.append(f"{index}: posible operador JS perdido: {stripped}")

    if incidencias:
        safe_print("ERROR: posibles roturas de JavaScript embebido:")
        for item in incidencias[:12]:
            safe_print(f"- {item}")
        return False
    safe_print("OK: no se detectan ternarios rotos en el JavaScript embebido.")
    return True


def check_iconos_app() -> bool:
    safe_print("\n==> Iconos de la app")
    ico = ROOT / "assets" / "corrector_carm.ico"
    png = ROOT / "assets" / "corrector_carm.png"
    incidencias: list[str] = []
    if not ico.exists() or ico.stat().st_size < 1024:
        incidencias.append("assets/corrector_carm.ico no existe o es demasiado pequeno.")
    if not png.exists() or png.stat().st_size < 1024:
        incidencias.append("assets/corrector_carm.png no existe o es demasiado pequeno.")
    if png.exists():
        try:
            if png.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
                incidencias.append("assets/corrector_carm.png no parece un PNG valido.")
        except Exception as exc:
            incidencias.append(f"No se pudo leer assets/corrector_carm.png: {exc}")
    if ico.exists():
        try:
            if ico.read_bytes()[:4] != b"\x00\x00\x01\x00":
                incidencias.append("assets/corrector_carm.ico no parece un ICO valido.")
        except Exception as exc:
            incidencias.append(f"No se pudo leer assets/corrector_carm.ico: {exc}")

    if incidencias:
        safe_print("ERROR: iconos de la app con incidencias:")
        for item in incidencias:
            safe_print(f"- {item}")
        return False
    safe_print("OK: iconos propios disponibles para panel, bandeja y accesos directos.")
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
        with urllib.request.urlopen(f"{base_url}/assets/corrector_carm.png?v=verificar", timeout=10) as response:
            if response.status != 200 or response.headers.get("Content-Type") != "image/png":
                safe_print("ERROR: el PNG del icono no se sirve correctamente.")
                return False
            if response.read(8) != b"\x89PNG\r\n\x1a\n":
                safe_print("ERROR: el PNG del icono servido no tiene cabecera PNG valida.")
                return False
        with urllib.request.urlopen(f"{base_url}/assets/corrector_carm.ico?v=verificar", timeout=10) as response:
            if response.status != 200 or response.headers.get("Content-Type") != "image/x-icon":
                safe_print("ERROR: el ICO del icono no se sirve correctamente.")
                return False
            if response.read(4) != b"\x00\x00\x01\x00":
                safe_print("ERROR: el ICO del icono servido no tiene cabecera ICO valida.")
                return False
        safe_print("OK: token local y endpoints basicos responden correctamente.")
        return True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def check_importacion_json_csv() -> bool:
    safe_print("\n==> Importacion JSON a revision_pendiente.csv")
    from corrector_agente import GeneradorSalidas

    tmp_root = ROOT / ".tmp_verificacion_importacion"
    pendientes = tmp_root / "pendientes"
    prompts_dir = pendientes / "prompts_codex"
    temporal = tmp_root / "temporal"
    try:
        if tmp_root.exists():
            shutil.rmtree(tmp_root)
        prompts_dir.mkdir(parents=True, exist_ok=True)
        temporal.mkdir(parents=True, exist_ok=True)

        json_ud01 = prompts_dir / "prompt_ud01cp01_correccion.json"
        json_ud02 = prompts_dir / "prompt_ud02cp01_correccion.json"
        json_ud01.write_text(
            json.dumps(
                {
                    "actividad": "ud01cp01",
                    "correcciones": [
                        {
                            "id": "0",
                            "alumno": "Alumno Uno",
                            "nota": 8,
                            "criterios": [],
                            "retroalimentacion": "Feedback inicial UD01.",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        json_ud02.write_text(
            json.dumps(
                {
                    "actividad": "ud02cp01",
                    "correcciones": [
                        {
                            "id": "0",
                            "alumno": "Alumno Dos",
                            "nota": 7,
                            "criterios": [],
                            "retroalimentacion": "Feedback inicial UD02.",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        salida = GeneradorSalidas(pendientes, temporal)
        salida.importar_correcciones_codex(json_ud01)
        salida.importar_correcciones_codex(json_ud02)

        revision = temporal / "revision_pendiente.csv"
        with revision.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter=";"))
        claves = {(row.get("actividad"), row.get("alumno")) for row in rows}
        if claves != {("ud01cp01", "Alumno Uno"), ("ud02cp01", "Alumno Dos")}:
            safe_print(f"ERROR: el CSV no conserva correctamente varias actividades: {claves}")
            return False

        json_ud01.write_text(
            json.dumps(
                {
                    "actividad": "ud01cp01",
                    "correcciones": [
                        {
                            "id": "0",
                            "alumno": "Alumno Uno",
                            "nota": 9,
                            "criterios": [],
                            "retroalimentacion": "Feedback actualizado UD01.",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        salida.importar_correcciones_codex(json_ud01)
        with revision.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter=";"))
        filas_ud01 = [row for row in rows if row.get("actividad") == "ud01cp01" and row.get("alumno") == "Alumno Uno"]
        if len(rows) != 2 or len(filas_ud01) != 1 or filas_ud01[0].get("nota") != "9.0":
            safe_print("ERROR: reimportar una correccion no sustituyo la fila anterior como se esperaba.")
            return False

        safe_print("OK: JSON de varias unidades importan al CSV sin duplicar filas.")
        return True
    except Exception as exc:
        safe_print(f"ERROR: prueba de importacion JSON/CSV fallo: {exc}")
        return False
    finally:
        if tmp_root.exists():
            shutil.rmtree(tmp_root, ignore_errors=True)


def check_contexto_cursos_cuenta() -> bool:
    safe_print("\n==> Contexto de cuenta y curso")
    import interfaz_app as app

    original_read_env = app.read_env_values
    original_load_config = app.load_app_config
    try:
        old_ref = app.hashlib.sha256("cuenta_antigua".encode()).hexdigest()[:12]
        app.read_env_values = lambda: {"CARM_USUARIO": "cuenta_nueva", "CARM_COURSE_URL": ""}
        app.load_app_config = lambda: {"carm_account_ref": old_ref, "selected_course_ids": ["1592"]}
        if app.account_context_matches_current_user() or app.current_course_url() or app.selected_course_ids():
            safe_print("ERROR: una cuenta distinta puede reutilizar cursos seleccionados antiguos.")
            return False

        same_ref = app.hashlib.sha256("misma_cuenta".encode()).hexdigest()[:12]
        app.read_env_values = lambda: {"CARM_USUARIO": "misma_cuenta", "CARM_COURSE_URL": ""}
        app.load_app_config = lambda: {"carm_account_ref": same_ref, "selected_course_ids": ["1592"]}
        if not app.account_context_matches_current_user() or app.active_course_id() != "1592":
            safe_print("ERROR: una misma cuenta no conserva correctamente su curso seleccionado.")
            return False
        pendientes_default, temporal_default = app._apply_course_scope(app.DEFAULT_PENDIENTES_DIR, app.DEFAULT_TEMPORAL_DIR)
        if "1592" not in str(pendientes_default) or "1592" not in str(temporal_default):
            safe_print("ERROR: las carpetas por curso no estan activadas por defecto.")
            return False

        app.load_app_config = lambda: {
            "carm_account_ref": same_ref,
            "selected_course_ids": ["1592", "1600"],
            "active_course_id": "1600",
            "course_scoped_dirs": True,
        }
        if app.active_course_id() != "1600":
            safe_print("ERROR: el curso activo no prevalece sobre la lista de autoprompteo.")
            return False
        pendientes, temporal = app._apply_course_scope(app.DEFAULT_PENDIENTES_DIR, app.DEFAULT_TEMPORAL_DIR)
        if "1600" not in str(pendientes) or "1600" not in str(temporal):
            safe_print("ERROR: las carpetas activas no cambian al curso seleccionado.")
            return False

        app.read_env_values = lambda: {"CARM_USUARIO": "tu_usuario_carm", "CARM_CONTRASENA": "tu_contrasena_carm"}
        if app.carm_credentials_present():
            safe_print("ERROR: valores de plantilla en .env cuentan como credenciales reales.")
            return False

        safe_print("OK: cambio de cuenta bloquea cursos antiguos y misma cuenta conserva seleccion.")
        return True
    except Exception as exc:
        safe_print(f"ERROR: prueba de contexto cuenta/curso fallo: {exc}")
        return False
    finally:
        app.read_env_values = original_read_env
        app.load_app_config = original_load_config


def check_interfaz_flujos_seguro() -> bool:
    safe_print("\n==> Flujos seguros de interfaz")
    import interfaz_app as app

    original_allowed_units = app.allowed_units
    original_revisar_publicacion_segura = app.revisar_publicacion_segura
    try:
        app.allowed_units = lambda: {"ud01"}
        app.revisar_publicacion_segura = lambda: None
        args = app.build_args("prepare", {"modo": "course", "max_entregas": "0"})
        if "--unidad" in args or "--actividad" in args:
            safe_print("ERROR: preparar todo el curso no debe forzar unidad ni actividad.")
            return False
        try:
            app.build_args("publish", {"json_path": str(app.REVISION_CSV)})
        except ValueError as exc:
            if "desactivada" not in str(exc).lower():
                safe_print(f"ERROR: publicacion directa bloqueada con mensaje inesperado: {exc}")
                return False
        else:
            safe_print("ERROR: la interfaz todavia permite publicacion directa.")
            return False
        assisted_args = app.build_args(
            "assist_publish",
            {"json_path": str(app.REVISION_CSV), "guardar_trace_subida": True},
        )
        if "--subida-asistida-carm" not in assisted_args or "--guardar-trace-subida" not in assisted_args:
            safe_print("ERROR: la subida asistida no propaga correctamente el trace de diagnostico.")
            return False
        safe_print("OK: preparar todo el curso no filtra unidad y publicacion directa esta bloqueada.")
        return True
    except Exception as exc:
        safe_print(f"ERROR: prueba de flujos seguros fallo: {exc}")
        return False
    finally:
        app.allowed_units = original_allowed_units
        app.revisar_publicacion_segura = original_revisar_publicacion_segura


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
        help="Omite la prueba offline de importacion JSON a revision_pendiente.csv.",
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
    ok &= check_textos_sin_mojibake()
    ok &= check_javascript_panel_embebido()
    ok &= check_iconos_app()
    ok &= print_health(operacion=not args.instalacion)
    if not args.sin_prueba_offline:
        ok &= check_importacion_json_csv()
        ok &= check_contexto_cursos_cuenta()
        ok &= check_interfaz_flujos_seguro()
    if not args.sin_endpoints:
        ok &= check_local_endpoints()

    if ok:
        safe_print("\nVerificacion completada correctamente.")
        return 0
    safe_print("\nVerificacion completada con incidencias.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
