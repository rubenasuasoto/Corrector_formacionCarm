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


def check_javascript_playwright_embebido() -> bool:
    safe_print("\n==> JavaScript Playwright embebido")
    try:
        lines = (ROOT / "corrector_agente.py").read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        safe_print(f"ERROR: no se pudo leer corrector_agente.py: {exc}")
        return False

    patrones_rotos = (
        "  document.querySelector(",
        "label  label.",
        "wrap  wrap.",
        "heading  heading.",
        "card  card.",
        "key.includes('_editor')  ",
        "typeof el.className === 'string'  ",
        "invalid  '",
        "allowManual  '",
    )
    incidencias: list[str] = []
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if any(patron in stripped for patron in patrones_rotos):
            incidencias.append(f"{index}: posible ternario JS roto: {stripped}")

    if incidencias:
        safe_print("ERROR: posibles roturas de JavaScript usado por Playwright:")
        for item in incidencias[:12]:
            safe_print(f"- {item}")
        return False
    safe_print("OK: no se detectan ternarios rotos en JavaScript usado por Playwright.")
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


def check_cache_sqlite_basica() -> bool:
    safe_print("\n==> Cache SQLite CARM")
    from corrector_agente import CacheCursoCarm

    tmp_root = ROOT / ".tmp_verificacion_cache"
    try:
        if tmp_root.exists():
            shutil.rmtree(tmp_root)
        tmp_root.mkdir(parents=True, exist_ok=True)
        cache = CacheCursoCarm(
            path=tmp_root / "curso_9999.sqlite",
            course_url="https://formacion.carm.es/course/view.php?id=9999",
        )
        cache.guardar_curso("Curso de prueba")
        cache.guardar_unidad("ud01", nombre="Unidad 1", contenido_imprimible="")
        cache.guardar_actividad(
            {
                "codigo": "ud01cp01",
                "unidad_codigo": "ud01",
                "nombre": "UD01 - Caso practico 1",
                "tipo": "obligatorio",
                "url": "https://formacion.carm.es/mod/assign/view.php?id=1",
                "url_grading": "https://formacion.carm.es/mod/assign/view.php?action=grading&id=1&filter=require_grading",
                "filtro": "require_grading",
                "enunciado": "Enunciado de prueba",
            }
        )
        cache.obtener_contexto_unidades({"ud01"})
        actividad = cache.enriquecer_actividad({"codigo": "ud01cp01"})
        if actividad.get("enunciado") != "Enunciado de prueba":
            safe_print("ERROR: la cache no devolvio la actividad enriquecida.")
            return False
        safe_print("OK: operaciones basicas de cache SQLite funcionan.")
        return True
    except Exception as exc:
        safe_print(f"ERROR: cache SQLite fallo: {exc}")
        return False
    finally:
        if tmp_root.exists():
            shutil.rmtree(tmp_root, ignore_errors=True)


def check_extraccion_insuficiente() -> bool:
    safe_print("\n==> Extraccion insuficiente")
    from corrector_agente import GeneradorSalidas

    if not GeneradorSalidas._texto_extraido_insuficiente("•\n•\n•\n\n•\n•\n"):
        safe_print("ERROR: texto formado solo por vinetas no queda bloqueado como revision manual.")
        return False
    if GeneradorSalidas._texto_extraido_insuficiente(
        "Respuesta desarrollada con medidas concretas, canal humano alternativo, "
        "aviso visible de uso de IA, trazabilidad y revision profesional."
    ):
        safe_print("ERROR: texto suficiente queda marcado como insuficiente.")
        return False
    avisos = GeneradorSalidas._avisos_calidad_extraccion(
        "Respuesta correcta sobre turismo e IA. " * 12 + (chr(0x10DE) + chr(0x10D0) + chr(0x10E1) + chr(0x10E3) + chr(0x10EE) + chr(0x10D0)) * 4
    )
    if "caracteres_no_latinos_inesperados" not in avisos:
        safe_print("ERROR: no se detectan caracteres no latinos inesperados en una extraccion sospechosa.")
        return False
    avisos = GeneradorSalidas._avisos_calidad_extraccion(
        "Respuesta desarrollada con contenido claro, estructura, ejemplos y medidas aplicables al caso.",
        truncada=True,
    )
    if "respuesta_recortada_por_limite" not in avisos:
        safe_print("ERROR: no se marca como aviso interno una respuesta recortada.")
        return False
    safe_print("OK: textos vacios o solo con marcas/listas quedan fuera de correccion automatica.")
    return True


def check_filtro_requiere_calificacion() -> bool:
    safe_print("\n==> Filtro Requiere calificacion CARM")
    from corrector_agente import ExtractorCarm

    resumen_sin_pendientes = ExtractorCarm._extraer_resumen_accion_actividad("24 de 120 Enviados")
    if resumen_sin_pendientes.get("sin_calificar") is not None:
        safe_print("ERROR: el contador de solo enviados no debe crear pendientes.")
        return False
    resumen_con_pendientes = ExtractorCarm._extraer_resumen_accion_actividad("55 de 120 Enviados, 1 Sin calificar")
    if resumen_con_pendientes.get("sin_calificar") != 1:
        safe_print("ERROR: no se detecta correctamente el contador Sin calificar.")
        return False
    resumen_opcional = ExtractorCarm._extraer_resumen_accion_actividad("26 de 120 Enviados, 3 Sin calificar")
    if resumen_opcional.get("enviados") != 26 or resumen_opcional.get("sin_calificar") != 3:
        safe_print("ERROR: no se detectan correctamente actividades opcionales con varios Sin calificar.")
        return False
    url = ExtractorCarm._url_grading_requiere_calificacion(
        "https://formacion.carm.es/mod/assign/view.php?action=grading&id=19195&tifirst=C&filter=submitted"
    )
    if "filter=requiregrading" not in url or "tifirst" in url or "filter=submitted" in url:
        safe_print("ERROR: la URL de Requiere calificacion no limpia iniciales o no usa el valor real del filtro CARM.")
        return False
    if ExtractorCarm._es_estado_requiere_calificacion("Enviado para calificarCalificado"):
        safe_print("ERROR: una fila ya calificada no debe entrar en revision pendiente.")
        return False
    if not ExtractorCarm._es_estado_requiere_calificacion("Enviado para calificar"):
        safe_print("ERROR: una fila enviada para calificar debe entrar como pendiente.")
        return False
    if not ExtractorCarm._es_estado_requiere_calificacion("Enviado para calificarCalificado - entrega de seguimiento recibida"):
        safe_print("ERROR: una entrega de seguimiento recibida debe seguir tratandose como reenvio pendiente.")
        return False
    safe_print("OK: el filtro distingue enviados, calificados y reenvios pendientes.")
    return True


def check_formatos_lectura() -> bool:
    safe_print("\n==> Formatos de lectura")
    from corrector_agente import GeneradorSalidas

    esperados_texto = {".docx", ".docm", ".odt", ".ods", ".odp", ".rtf"}
    esperados_ocr = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
    if not esperados_texto.issubset(GeneradorSalidas.EXTENSIONES_OFFICE_TEXTO):
        faltan = sorted(esperados_texto - GeneradorSalidas.EXTENSIONES_OFFICE_TEXTO)
        safe_print(f"ERROR: faltan formatos Office/ODF soportados: {faltan}")
        return False
    if not esperados_ocr.issubset(GeneradorSalidas.EXTENSIONES_OCR):
        faltan = sorted(esperados_ocr - GeneradorSalidas.EXTENSIONES_OCR)
        safe_print(f"ERROR: faltan formatos OCR soportados: {faltan}")
        return False
    if {".bmp", ".tif", ".tiff", ".webp"} & GeneradorSalidas.EXTENSIONES_MULTIMEDIA:
        safe_print("ERROR: formatos OCR ampliados siguen clasificados como multimedia.")
        return False
    texto_pdf = (
        "Durante el mes de agosto un destino costero recibe consultas sobre horarios de playas. "
        "Diseña un esquema básico de automatización controlada."
    )
    texto_ocr = texto_pdf + (
        " Entrada multicanal web redes sociales mensajeria. Capa de deteccion IA reglas. "
        "Motor de respuestas frecuentes FAQ. Bloques de respuestas estructuradas. "
        "Repositorio central unico. Respuesta automatizada con enlace oficial. "
        "Derivacion visible a atencion humana. Resultado final coherencia entre canales."
    )
    if not GeneradorSalidas._preferir_ocr_si_aporta_contenido_visual(texto_pdf, texto_ocr):
        safe_print("ERROR: un PDF con esquema visual OCR adicional no se aprovecha.")
        return False
    safe_print("OK: formatos ampliados de Office, ODF, EPUB, ZIP e imagen OCR configurados.")
    return True


def check_prompt_ortografia() -> bool:
    safe_print("\n==> Prompt de ortografia")
    import corrector_agente

    regla = getattr(corrector_agente, "REGLA_IDIOMA_CORRECCION", "")
    if "español" not in regla or "tildes" not in regla or "eñes" not in regla:
        safe_print("ERROR: la regla de idioma no exige español con tildes y eñes.")
        return False
    if any(token in regla.lower() for token in (" espanol ", " numeros ", " puntuacion ")):
        safe_print("ERROR: la regla de idioma contiene palabras clave sin tilde.")
        return False
    try:
        data = json.loads((ROOT / "prompts_correccion.json").read_text(encoding="utf-8"))
        default = data.get("prompts", {}).get("default", {})
        combinado = f"{default.get('sistema', '')}\n{default.get('criterios', '')}"
    except Exception as exc:
        safe_print(f"ERROR: no se pudo leer prompts_correccion.json: {exc}")
        return False
    if "Regla ortográfica" not in combinado or "No devuelvas texto sin acentos" not in combinado:
        safe_print("ERROR: prompts_correccion.json no refuerza la salida con acentos.")
        return False
    prueba = corrector_agente.sanitizar_feedback(
        "La aplicacion practica tambien necesita revision y mas informacion."
    )
    if "aplicación práctica" not in prueba or "también" not in prueba or "revisión" not in prueba:
        safe_print("ERROR: el saneado de feedback no corrige tildes frecuentes.")
        return False
    safe_print("OK: prompts y saneado piden feedback en español con acentos.")
    return True


def check_retroalimentacion_importada() -> bool:
    safe_print("\n==> Retroalimentacion importada")
    from corrector_agente import GeneradorSalidas

    correccion = {
        "alumno": "Silvia Penalva Garcia",
        "nota": 7.8,
        "criterios": [
            {
                "nombre": "Presentacion del trabajo",
                "maximo": 3,
                "puntuacion": 2.4,
                "comentario": "Trabajo claro.",
            },
            {
                "nombre": "Retroalimentacion",
                "maximo": 0,
                "puntuacion": 0,
                "comentario": "Silvia, feedback final para CARM.",
            },
        ],
    }
    normalizada = GeneradorSalidas._normalizar_correccion_importada(correccion)
    if normalizada.get("retroalimentacion") != "Silvia, feedback final para CARM.":
        safe_print("ERROR: no se rescata la retroalimentacion cuando llega como criterio.")
        return False
    if any("retroaliment" in str(item.get("nombre", "")).lower() for item in normalizada.get("criterios", [])):
        safe_print("ERROR: la retroalimentacion sigue apareciendo como criterio evaluable.")
        return False
    safe_print("OK: la retroalimentacion se importa al campo correcto y no como criterio 0/0.")
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
    if ok and not operacion:
        safe_print("OK: instalacion lista; credenciales CARM y curso activo pueden configurarse despues.")
    else:
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
        curso_pendientes = app.Path(r"C:\temp\vscodec\cursos\1592\pendientes")
        curso_temporal = app.Path(r"C:\temp\vscodec\cursos\1592\temporal")
        if not app._looks_like_course_work_dir(curso_pendientes, "pendientes"):
            safe_print("ERROR: no se detectan como base invalida las rutas pendientes de un curso concreto.")
            return False
        if not app._looks_like_course_work_dir(curso_temporal, "temporal"):
            safe_print("ERROR: no se detectan como base invalida las rutas temporales de un curso concreto.")
            return False

        cursos_auto = app.selected_courses_for_auto()
        if [curso["id"] for curso in cursos_auto] != ["1592", "1600"]:
            safe_print("ERROR: los cursos seleccionados para autoprompteo no se conservan en cola.")
            return False
        rutas_pendientes = {curso["pendientes"] for curso in cursos_auto}
        rutas_temporal = {curso["temporal"] for curso in cursos_auto}
        if len(rutas_pendientes) != 2 or len(rutas_temporal) != 2:
            safe_print("ERROR: varios cursos seleccionados comparten carpeta de trabajo.")
            return False
        if not all(rf"\cursos\{curso['id']}\pendientes".lower() in curso["pendientes"].lower() for curso in cursos_auto):
            safe_print("ERROR: los pendientes de autoprompteo no apuntan a la carpeta del curso.")
            return False
        if not all(rf"\cursos\{curso['id']}\temporal".lower() in curso["temporal"].lower() for curso in cursos_auto):
            safe_print("ERROR: los temporales de autoprompteo no apuntan a la carpeta del curso.")
            return False
        for curso in cursos_auto:
            args = app.auto_prepare_args_for_course(curso)
            if curso["pendientes"] not in args or curso["temporal"] not in args:
                safe_print("ERROR: el autoprompteo no propaga rutas por curso al subproceso.")
                return False

        app.read_env_values = lambda: {"CARM_USUARIO": "tu_usuario_carm", "CARM_CONTRASENA": "tu_contrasena_carm"}
        if app.carm_credentials_present():
            safe_print("ERROR: valores de plantilla en .env cuentan como credenciales reales.")
            return False

        safe_print("OK: cambio de cuenta bloquea cursos antiguos y el autoprompteo multi-curso usa carpetas separadas.")
        return True
    except Exception as exc:
        safe_print(f"ERROR: prueba de contexto cuenta/curso fallo: {exc}")
        return False
    finally:
        app.read_env_values = original_read_env
        app.load_app_config = original_load_config


def check_export_codex_project_extenso() -> bool:
    safe_print("\n==> Proyecto Codex por curso")
    import sqlite3
    import interfaz_app as app

    course_id = "999999"
    tmp_root = ROOT / ".tmp_verificar_codex_project"
    tmp_courses = tmp_root / "cursos"
    cache_dir = tmp_root / "cache_carm"
    cache_path = cache_dir / f"curso_{course_id}.sqlite"
    original_courses_dir = app.COURSES_DIR
    original_cache_path_for_course_id = app.cache_path_for_course_id
    try:
        if tmp_root.exists():
            shutil.rmtree(tmp_root, ignore_errors=True)
        cache_dir.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(cache_path) as con:
            con.execute("CREATE TABLE curso (course_id TEXT, titulo TEXT, url TEXT)")
            con.execute(
                "CREATE TABLE unidad (course_id TEXT, codigo TEXT, nombre TEXT, contenido_imprimible TEXT, resumen_didactico TEXT)"
            )
            con.execute(
                "CREATE TABLE actividad (course_id TEXT, codigo TEXT, unidad_codigo TEXT, nombre TEXT, tipo TEXT, enunciado TEXT)"
            )
            con.execute(
                "INSERT INTO curso VALUES (?, ?, ?)",
                (course_id, "Curso de prueba", f"https://formacion.carm.es/course/view.php?id={course_id}"),
            )
            con.execute(
                "INSERT INTO unidad VALUES (?, ?, ?, ?, ?)",
                (
                    course_id,
                    "ud01",
                    "Guía rápida",
                    "Contenido completo con codificación correcta y suficiente detalle. " * 80,
                    "Resumen de la unidad.",
                ),
            )
            con.execute(
                "INSERT INTO actividad VALUES (?, ?, ?, ?, ?, ?)",
                (course_id, "ud01cp01", "ud01", "Caso práctico", "obligatorio", "Enunciado de prueba."),
            )
        app.COURSES_DIR = tmp_courses
        app.cache_path_for_course_id = lambda value: cache_path if str(value) == course_id else None
        project = app.export_codex_course_project(course_id)
        required = [
            project / "contexto_didactico.md",
            project / "actividades.json",
            project / "AGENTS.md",
            project / "unidades" / "ud01.md",
        ]
        if not all(path.exists() for path in required):
            safe_print("ERROR: el proyecto Codex no exporta todos los archivos esperados.")
            return False
        unit_text = (project / "unidades" / "ud01.md").read_text(encoding="utf-8")
        context_text = (project / "contexto_didactico.md").read_text(encoding="utf-8")
        if "Contenido imprimible completo" not in unit_text or len(unit_text) < 1000:
            safe_print("ERROR: Codex no recibe el contenido didactico completo por unidad.")
            return False
        if "unidades/ud01.md" not in context_text:
            safe_print("ERROR: el indice Codex no enlaza el archivo completo de la unidad.")
            return False
        safe_print("OK: proyecto Codex exporta indice, actividades y contenido completo por unidad.")
        return True
    except Exception as exc:
        safe_print(f"ERROR: prueba de proyecto Codex fallo: {exc}")
        return False
    finally:
        app.COURSES_DIR = original_courses_dir
        app.cache_path_for_course_id = original_cache_path_for_course_id
        if tmp_root.exists():
            shutil.rmtree(tmp_root, ignore_errors=True)


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


def check_revision_manual_interfaz() -> bool:
    safe_print("\n==> Revision manual en interfaz")
    import interfaz_app as app

    original_temporal = app.TEMPORAL_DIR
    original_pendientes = app.PENDIENTES_DIR
    original_prompts = app.PROMPTS_DIR
    original_revision = app.REVISION_CSV
    original_notes = app.MANUAL_REVIEW_NOTES
    base = ROOT / ".tmp_revision_manual_check"
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    try:
        temporal = base / "temporal"
        pendientes = base / "pendientes"
        prompts = pendientes / "prompts_codex"
        alumno_dir = temporal / "Ana Prueba"
        alumno_dir.mkdir(parents=True, exist_ok=True)
        prompts.mkdir(parents=True, exist_ok=True)
        original_pdf = alumno_dir / "ud01cp01.pdf"
        correction_txt = alumno_dir / "ud01cp01.txt"
        archived_pages_dir = pendientes / "archivados_prompt" / "20260526_090000" / "ud01cp01"
        archived_pages = archived_pages_dir / "Ana Prueba.pages"
        original_pdf.write_text("Entrega original legible.", encoding="utf-8")
        correction_txt.write_text("Correccion anterior con dudas.", encoding="utf-8")
        archived_pages_dir.mkdir(parents=True, exist_ok=True)
        archived_pages.write_text("Paquete Pages simulado para localizar archivo archivado.", encoding="utf-8")
        revision_csv = temporal / "revision_pendiente.csv"
        notes_json = temporal / "revision_manual_notas.json"
        try:
            app.TEMPORAL_DIR = temporal
            app.PENDIENTES_DIR = pendientes
            app.PROMPTS_DIR = prompts
            app.REVISION_CSV = revision_csv
            app.MANUAL_REVIEW_NOTES = notes_json
            revision_csv.parent.mkdir(parents=True, exist_ok=True)
            with revision_csv.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["alumno", "actividad", "nota", "estado", "retroalimentacion", "archivo_correccion"],
                    delimiter=";",
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "alumno": "Ana Prueba",
                        "actividad": "ud01cp01",
                        "nota": "5",
                        "estado": "borrador_pendiente_de_revision",
                        "retroalimentacion": "Feedback previo.",
                        "archivo_correccion": str(correction_txt),
                    }
                )
            result = app.save_manual_review_case(
                {
                    "alumno": "Ana Prueba",
                    "actividad": "ud01cp01",
                    "nota_revision": "Revisa el PDF original antes de corregir.",
                    "mark_manual": True,
                }
            )
            if not result.get("ok"):
                safe_print("ERROR: no se pudo marcar un caso para revision manual.")
                return False
            state = app.manual_review_state()
            if state["count"] != 1 or state["blocking"] != 1:
                safe_print("ERROR: el panel no detecta el caso marcado para revision manual.")
                return False
            original_files = state["rows"][0].get("original_files", [])
            if str(archived_pages) not in original_files:
                safe_print("ERROR: el panel no localiza originales Pages archivados para revision manual.")
                return False
            prompt = app.build_manual_review_prompt(
                {
                    "alumno": "Ana Prueba",
                    "actividad": "ud01cp01",
                    "nota_revision": "Completa la correccion usando el archivo original.",
                }
            )
            prompt_path = Path(prompt.get("prompt_path", ""))
            if not prompt_path.exists() or not prompt_path.name.startswith("prompt_ud01cp01_revision_"):
                safe_print("ERROR: no se genero el prompt de recorreccion manual.")
                return False
            text = prompt_path.read_text(encoding="utf-8")
            if "No lo menciones" in text or "Completa la correccion" not in text or "preview.jpg" not in text:
                safe_print("ERROR: el prompt de revision manual no contiene las instrucciones esperadas.")
                return False
            safe_print("OK: revision manual guarda notas, bloquea subida y genera prompt para Codex.")
            return True
        except Exception as exc:
            safe_print(f"ERROR: prueba de revision manual fallo: {exc}")
            return False
        finally:
            app.TEMPORAL_DIR = original_temporal
            app.PENDIENTES_DIR = original_pendientes
            app.PROMPTS_DIR = original_prompts
            app.REVISION_CSV = original_revision
            app.MANUAL_REVIEW_NOTES = original_notes
    finally:
        shutil.rmtree(base, ignore_errors=True)


def check_autoprompt_hora() -> bool:
    safe_print("\n==> Horario de autoprompt")
    import interfaz_app as app

    original_config_path = app.APP_CONFIG_PATH
    base = ROOT / ".tmp_autoprompt_check"
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    try:
        app.APP_CONFIG_PATH = base / ".corrector_app.json"
        app.save_automation_config(
            interval_minutes=600,
            periodic_auto_prepare=True,
            auto_prepare_interval=0,
            auto_prepare_time="08:30",
        )
        if app.auto_prepare_time_of_day() != "08:30":
            safe_print("ERROR: la hora 08:30 no queda guardada o no se lee correctamente.")
            return False
        app.save_automation_config(
            interval_minutes=600,
            periodic_auto_prepare=True,
            auto_prepare_interval=0,
            auto_prepare_time="00:00",
        )
        if app.auto_prepare_time_of_day() != "00:00":
            safe_print("ERROR: la hora 00:00 no queda guardada o no se lee correctamente.")
            return False
        try:
            app.save_automation_config(
                interval_minutes=600,
                periodic_auto_prepare=True,
                auto_prepare_interval=0,
                auto_prepare_time="24:00",
            )
        except ValueError:
            safe_print("OK: hora exacta de autoprompt guarda HH:MM validos y rechaza horas invalidas.")
            return True
        safe_print("ERROR: la hora invalida 24:00 fue aceptada.")
        return False
    except Exception as exc:
        safe_print(f"ERROR: prueba de horario de autoprompt fallo: {exc}")
        return False
    finally:
        app.APP_CONFIG_PATH = original_config_path
        shutil.rmtree(base, ignore_errors=True)


def check_preferencias_pantalla() -> bool:
    safe_print("\n==> Preferencias de pantalla")
    import interfaz_app as app

    original_config_path = app.APP_CONFIG_PATH
    base = ROOT / ".tmp_ui_theme_check"
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    try:
        app.APP_CONFIG_PATH = base / ".corrector_app.json"
        for theme in ("auto", "light", "dark"):
            result = app.save_ui_config(theme, "large", "tall", "high", "advanced")
            if (
                not result.get("ok")
                or app.ui_theme() != theme
                or app.ui_font_size() != "large"
                or app.ui_log_height() != "tall"
                or app.ui_contrast() != "high"
                or app.ui_last_settings_page() != "advanced"
            ):
                safe_print(f"ERROR: no se guardo el tema {theme}.")
                return False
        try:
            app.save_ui_config("neon")
        except ValueError:
            pass
        else:
            safe_print("ERROR: se acepto un tema visual no valido.")
            return False
        try:
            app.save_ui_config("auto", "gigante", "normal", "normal", "screen")
        except ValueError:
            safe_print("OK: tema, letra, contraste, altura de registro y ultima seccion se guardan y validan correctamente.")
            return True
        safe_print("ERROR: se acepto un tema visual no valido.")
        return False
    except Exception as exc:
        safe_print(f"ERROR: prueba de preferencias de pantalla fallo: {exc}")
        return False
    finally:
        app.APP_CONFIG_PATH = original_config_path
        shutil.rmtree(base, ignore_errors=True)


def check_menu_configuracion() -> bool:
    safe_print("\n==> Menu de configuracion")
    try:
        text = (ROOT / "interfaz_app.py").read_text(encoding="utf-8")
    except Exception as exc:
        safe_print(f"ERROR: no se pudo leer interfaz_app.py: {exc}")
        return False
    required = [
        "settings-layout",
        "settings-nav",
        "settingsNavBtn",
        "settings-page",
        "showSettingsPage",
        "data-settings-page-panel=\"screen\"",
        "data-settings-page-panel=\"advanced\"",
        "uiFontSize",
        "uiLogHeight",
        "uiContrast",
        "logoutBtn",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        safe_print("ERROR: menu de configuracion incompleto: " + ", ".join(missing))
        return False
    safe_print("OK: configuracion organizada por secciones navegables.")
    return True


def check_instalador_python() -> bool:
    safe_print("\n==> Instalador Python")
    tecnico = ROOT / "instalar_windows.ps1"
    guiado = ROOT / "instalador_guiado_windows.ps1"
    setup = ROOT / "crear_instalador_setup_windows.ps1"
    desinstalador = ROOT / "desinstalar_windows.ps1"
    try:
        tecnico_text = tecnico.read_text(encoding="utf-8")
        guiado_text = guiado.read_text(encoding="utf-8")
        desinstalador_text = desinstalador.read_text(encoding="utf-8")
        setup_text = setup.read_text(encoding="utf-8") if setup.exists() else ""
    except Exception as exc:
        safe_print(f"ERROR: no se pudieron leer los instaladores: {exc}")
        return False

    required_tecnico = [
        "function Ensure-Python",
        "function Install-Python312",
        "Python.Python.3.12",
        "winget.exe",
        "$Python = Ensure-Python",
    ]
    required_guiado = [
        "Find-PythonInstallerCommand",
        "Test-PythonInstallerVersion",
        "Find-WingetInstallerCommand",
        "El instalador intentara instalarlo con winget",
        "UTF8Encoding($false)",
        "Invoke-PreviousInstallCleanup",
        "Backup-PreviousInstallState",
        "Restore-PreviousInstallState",
        "Desinstalando version anterior",
    ]
    required_silent_ui = [
        "Invoke-ProcessWithProgress",
        "CreateNoWindow = $true",
        "WindowStyle Hidden",
        "System.Windows.Forms.ListView",
        "En curso",
        "Desinstalador",
        "Corrector_CARM_instalador.log",
        "Corrector_CARM_instalador_stdout.log",
        "Show-InstallerError",
        "Add_FormClosing",
        "Fase tecnica terminada con codigo",
        "instalador_guiado_windows.ps1",
        "Start-UninstallProgress",
        "Complete-UninstallProgress",
    ]
    missing = [item for item in required_tecnico if item not in tecnico_text]
    missing += [item for item in required_guiado if item not in guiado_text]
    missing += [item for item in required_silent_ui[:11] if item not in guiado_text]
    if setup_text:
        missing += [item for item in required_silent_ui[11:12] if item not in setup_text]
    missing += [item for item in required_silent_ui[12:] if item not in desinstalador_text]
    if missing:
        safe_print("ERROR: autodeteccion/instalacion de Python incompleta: " + ", ".join(missing))
        return False
    safe_print("OK: instalador detecta Python 3.12+, oculta procesos tecnicos y muestra progreso grafico.")
    return True


def check_instalador_ocr() -> bool:
    safe_print("\n==> Instalador OCR")
    script = ROOT / "instalar_ocr_windows.ps1"
    try:
        text = script.read_text(encoding="utf-8")
    except Exception as exc:
        safe_print(f"ERROR: no se pudo leer instalar_ocr_windows.ps1: {exc}")
        return False
    required = [
        "Get-TesseractCommand",
        "Add-TesseractToPath",
        "UB-Mannheim.TesseractOCR",
        "--silent",
        "return $false",
        "OCR usara ingles si esta disponible",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        safe_print("ERROR: instalador OCR poco robusto: " + ", ".join(missing))
        return False
    safe_print("OK: instalador OCR busca Tesseract fuera del PATH y no falla por idioma espanol.")
    return True


def check_arranque_sin_consola() -> bool:
    safe_print("\n==> Arranque sin consola")
    files = {
        "crear_launcher_windows.ps1": ROOT / "crear_launcher_windows.ps1",
        "interfaz_app.py": ROOT / "interfaz_app.py",
        "desinstalar_windows.ps1": ROOT / "desinstalar_windows.ps1",
        "ABRIR_CORRECTOR_CARM.cmd": ROOT / "ABRIR_CORRECTOR_CARM.cmd",
    }
    try:
        texts = {name: path.read_text(encoding="utf-8") for name, path in files.items()}
    except Exception as exc:
        safe_print(f"ERROR: no se pudieron leer los archivos de arranque: {exc}")
        return False

    required = {
        "crear_launcher_windows.ps1": [
            'FileName = runner',
            'CreateNoWindow = true',
            'WindowStyle = ProcessWindowStyle.Hidden',
            'interfaz_app.py',
        ],
        "interfaz_app.py": [
            'Corrector CARM.vbs',
            'legacy_startup_cmd_path',
            'shell.Run',
            '--no-browser',
        ],
        "desinstalar_windows.ps1": ['Corrector CARM.vbs'],
        "ABRIR_CORRECTOR_CARM.cmd": ['Corrector CARM.exe'],
    }
    missing = [
        f"{name}:{item}"
        for name, items in required.items()
        for item in items
        if item not in texts[name]
    ]
    launcher_source = texts["crear_launcher_windows.ps1"]
    if 'FileName = "powershell.exe"' in launcher_source:
        missing.append("crear_launcher_windows.ps1:launcher todavia usa powershell.exe")
    if missing:
        safe_print("ERROR: arranque sin consola incompleto: " + ", ".join(missing))
        return False
    safe_print("OK: lanzador y arranque de Windows usan procesos ocultos sin depender de una consola visible.")
    return True


def check_prompts_codex_noop_no_se_archivan() -> bool:
    safe_print("\n==> Prompts sin entregas legibles")
    try:
        from corrector_agente import (
            correccion_json_tiene_correcciones,
            filtrar_prompts_para_correccion,
            prompt_tiene_entregas_legibles,
            prompt_tiene_revision_manual_pendiente,
        )
    except Exception as exc:
        safe_print(f"ERROR: no se pudieron importar validadores de prompts: {exc}")
        return False

    base = ROOT / ".tmp_verificacion" / "prompts_codex_noop"
    base.mkdir(parents=True, exist_ok=True)
    for path in base.glob("*"):
        try:
            if path.is_file():
                path.unlink()
        except Exception:
            pass
    try:
        prompt_vacio = base / "prompt_ud01cp01.md"
        prompt_vacio.write_text(
            "\n".join(
                [
                    "# Prompt",
                    "## Entregas legibles",
                    "```json",
                    "[]",
                    "```",
                    "## Entregas que requieren revision manual",
                    "```json",
                    '[{"alumno": "Alumno Manual"}]',
                    "```",
                ]
            ),
            encoding="utf-8",
        )
        correccion_vacia = base / "prompt_ud01cp01_correccion.json"
        correccion_vacia.write_text('{"actividad":"ud01cp01","correcciones":[]}', encoding="utf-8")

        prompt_ok = base / "prompt_ud01cp02.md"
        prompt_ok.write_text(
            "\n".join(
                [
                    "# Prompt",
                    "## Entregas legibles",
                    "```json",
                    '[{"id": "1", "alumno": "Alumno Correcto", "respuesta": "Contenido"}]',
                    "```",
                ]
            ),
            encoding="utf-8",
        )
        correccion_ok = base / "prompt_ud01cp02_correccion.json"
        correccion_ok.write_text(
            '{"actividad":"ud01cp02","correcciones":[{"id":"1","alumno":"Alumno Correcto","nota":8}]}',
            encoding="utf-8",
        )

        if prompt_tiene_entregas_legibles(prompt_vacio):
            safe_print("ERROR: un prompt manual sin entregas legibles aparece como corregible.")
            return False
        if not prompt_tiene_revision_manual_pendiente(prompt_vacio):
            safe_print("ERROR: no se detecta la seccion de revision manual pendiente.")
            return False
        if not prompt_tiene_entregas_legibles(prompt_ok):
            safe_print("ERROR: un prompt con entregas legibles no aparece como corregible.")
            return False
        prompt_revision = base / "prompt_ud01cp03_revision_alumno_20260525_120000.md"
        prompt_revision.write_text(
            "\n".join(
                [
                    "# Recorreccion manual ud01cp03",
                    "",
                    "Corrige de nuevo solo este caso. Devuelve un JSON valido con una unica correccion.",
                    "",
                    "## Archivos originales candidatos",
                    "",
                    "- C:\\temp\\vscodec\\cursos\\1592\\pendientes\\ud01cp03\\Alumno.pages",
                ]
            ),
            encoding="utf-8",
        )
        if not prompt_tiene_entregas_legibles(prompt_revision):
            safe_print("ERROR: un prompt de recorreccion manual no aparece como corregible.")
            return False
        if correccion_json_tiene_correcciones(correccion_vacia):
            safe_print("ERROR: una correccion vacia cuenta como resuelta.")
            return False
        if not correccion_json_tiene_correcciones(correccion_ok):
            safe_print("ERROR: una correccion con filas no cuenta como resuelta.")
            return False
        correccion_manual = base / "prompt_ud01cp03_revision_correccion.json"
        correccion_manual.write_text(
            json.dumps(
                {
                    "actividad": "ud01cp03",
                    "correcciones": [],
                    "revision_manual_necesaria": [
                        {
                            "id": "0",
                            "alumno": "Alumno Manual",
                            "motivo": "No se pudo leer el archivo original.",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        if not correccion_json_tiene_correcciones(correccion_manual):
            safe_print("ERROR: una salida con revision_manual_necesaria no cuenta como importable.")
            return False
        from corrector_agente import GeneradorSalidas

        rows = GeneradorSalidas(base, base)._leer_correcciones_codex(correccion_manual)
        if len(rows) != 1 or rows[0].get("estado") != "revision_manual_necesaria":
            safe_print("ERROR: revision_manual_necesaria no se normaliza como fila bloqueada.")
            return False

        prompts, sin_entregas = filtrar_prompts_para_correccion([prompt_vacio], "verificacion")
        if prompts or sin_entregas != [prompt_vacio] or not prompt_vacio.exists():
            safe_print("ERROR: el filtro no conserva correctamente prompts manuales sin archivar.")
            return False
        prompts, sin_entregas = filtrar_prompts_para_correccion([prompt_vacio], "Codex App")
        if prompts != [prompt_vacio] or sin_entregas:
            safe_print("ERROR: Codex App no acepta prompts con revision manual pendiente.")
            return False
        prompts, sin_entregas = filtrar_prompts_para_correccion([prompt_ok], "verificacion")
        if prompts or sin_entregas or not prompt_ok.exists() or not correccion_ok.exists():
            safe_print("ERROR: un prompt ya corregido se mueve o se vuelve a procesar antes de importar a revision.")
            return False
    finally:
        for path in base.glob("*"):
            try:
                if path.is_file():
                    path.unlink()
            except Exception:
                pass

    safe_print("OK: los prompts manuales no consumen Codex/API y los JSON vacios no se tratan como resueltos.")
    return True


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
    ok &= check_javascript_playwright_embebido()
    ok &= check_iconos_app()
    ok &= check_cache_sqlite_basica()
    ok &= check_extraccion_insuficiente()
    ok &= check_filtro_requiere_calificacion()
    ok &= check_formatos_lectura()
    ok &= check_prompt_ortografia()
    ok &= check_retroalimentacion_importada()
    ok &= check_prompts_codex_noop_no_se_archivan()
    ok &= print_health(operacion=not args.instalacion)
    if not args.sin_prueba_offline:
        ok &= check_importacion_json_csv()
        ok &= check_contexto_cursos_cuenta()
        ok &= check_export_codex_project_extenso()
        ok &= check_interfaz_flujos_seguro()
        ok &= check_revision_manual_interfaz()
        ok &= check_autoprompt_hora()
        ok &= check_preferencias_pantalla()
        ok &= check_menu_configuracion()
        ok &= check_instalador_python()
        ok &= check_instalador_ocr()
        ok &= check_arranque_sin_consola()
    if not args.sin_endpoints:
        ok &= check_local_endpoints()

    if ok:
        safe_print("\nVerificacion completada correctamente.")
        return 0
    safe_print("\nVerificacion completada con incidencias.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
