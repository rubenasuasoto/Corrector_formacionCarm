"""
Agente de corrección automática para CARM Formación.

Flujo principal:
1) (Opcional) Extrae envios desde CARM a una carpeta local de pendientes.
2) Corrige los ejercicios encontrados en pendientes con contexto de unidad.
3) Genera estructura de salida por alumno en carpeta temporal.
4) Genera resumen global con nota y feedback por alumno.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import getpass
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import datetime
from html import escape as html_escape, unescape
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv() -> bool:
        return False

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None


load_dotenv()

# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------

CARM_LOGIN_URL = "https://formacion.carm.es/login/index.php"
DEFAULT_CARM_DASHBOARD_URL = "https://formacion.carm.es/my/index.php"
DEFAULT_CARM_COURSE_URL = ""
_ENV_CARM_COURSE_URL = os.getenv("CARM_COURSE_URL", DEFAULT_CARM_COURSE_URL).strip()
CARM_MY_URL = os.getenv("CARM_DASHBOARD_URL", "").strip() or (
    _ENV_CARM_COURSE_URL if re.fullmatch(r"https://formacion\.carm\.es/(?:course/my|my)/index\.php", _ENV_CARM_COURSE_URL) else DEFAULT_CARM_DASHBOARD_URL
)
CARM_COURSE_URL = _ENV_CARM_COURSE_URL if re.fullmatch(r"https://formacion\.carm\.es/course/view\.php\?id=\d+", _ENV_CARM_COURSE_URL) else ""
CARM_COURSE_END_DATE = os.getenv("CARM_COURSE_END_DATE", "").strip()
CARM_HEADLESS = os.getenv("CARM_HEADLESS", "0").strip().lower() in {"1", "true", "yes"}
try:
    CARM_NAV_TIMEOUT_MS = int(os.getenv("CARM_NAV_TIMEOUT_MS", "90000"))
except ValueError:
    CARM_NAV_TIMEOUT_MS = 90000

DEFAULT_PENDIENTES_DIR = Path(r"C:\temp\vscodec\pendientes")
DEFAULT_TEMPORAL_DIR = Path(r"C:\temp\vscodec\temporal")
DEFAULT_ACTIVIDAD_CODIGO = "ud01cp01"


def requiere_curso_carm_configurado(accion: str) -> bool:
    if CARM_COURSE_URL:
        return True
    logger.error(
        "No hay curso CARM activo para %s. Primero detecta cursos desde el area personal y selecciona uno en la interfaz.",
        accion,
    )
    return False

LOG_DIR = Path("logs_correcciones")
RESPUESTAS_DIR = Path("respuestas_extraidas")
CORRECCIONES_DIR = Path("correcciones_validadas")
CACHE_DIR = Path("cache_carm")
CARM_RECORDAR_CUENTA = os.getenv("CARM_RECORDAR_CUENTA", "1").strip().lower() not in {"0", "false", "no"}
CARM_STORAGE_STATE = CACHE_DIR / "carm_storage_state.json"
AUDIT_LOG = RESPUESTAS_DIR / "auditoria.jsonl"
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


def _env_int(nombre: str, defecto: int) -> int:
    try:
        return int(os.getenv(nombre, str(defecto)) or defecto)
    except ValueError:
        return defecto


LOG_RETENTION_DAYS = _env_int("LOG_RETENTION_DAYS", 90)
AUDIT_RETENTION_DAYS = _env_int("AUDIT_RETENTION_DAYS", 365)

for d in (LOG_DIR, RESPUESTAS_DIR, CORRECCIONES_DIR, CACHE_DIR):
    d.mkdir(exist_ok=True)


def redactar_texto_sensible(texto: object) -> str:
    texto = str(texto or "")
    texto = re.sub(r"[\w.\-+%]+@[\w.\-]+\.[A-Za-z]{2,}", "[email-redactado]", texto)
    texto = re.sub(r"(sesskey=)[^&\"'>\s]+", r"\1[redactado]", texto, flags=re.I)
    texto = re.sub(r'("sesskey"\s*:\s*")[^"]+', r'\1[redactado]', texto, flags=re.I)
    texto = re.sub(r"(password|contrasena|contraseña|contraseña)(=|%3D)[^&\"'>\s]+", r"\1\2[redactado]", texto, flags=re.I)
    texto = re.sub(r"(api[_-]key|token|authorization|cookie)(\s*[=:]\s*)[^&\"'>\s]+", r"\1\2[redactado]", texto, flags=re.I)
    texto = re.sub(r"(CARM_CONTRASENA|OPENAI_API_KEY|X-Corrector-Token)=\S+", r"\1=[redactado]", texto, flags=re.I)
    return texto


def escribir_env_valores(updates: dict[str, str]) -> None:
    env_path = Path(".env")
    lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines() if env_path.exists() else []
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            output.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in updates:
            seen.add(key)
            output.append(f"{key}={updates[key]}")
        else:
            output.append(line)
    for key, value in updates.items():
        if key not in seen:
            output.append(f"{key}={value}")
    env_path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def es_valor_env_real(valor: str | None) -> bool:
    limpio = str(valor or "").strip()
    if not limpio:
        return False
    bajo = limpio.lower()
    if bajo in PLACEHOLDER_ENV_VALUES:
        return False
    if bajo.startswith("tu_") or bajo.startswith("your_"):
        return False
    return True


def obtener_credenciales_carm_interactivo(motivo: str) -> tuple[str, str] | None:
    usuario = os.getenv("CARM_USUARIO", "").strip()
    contrasena = os.getenv("CARM_CONTRASENA", "").strip()
    if es_valor_env_real(usuario) and es_valor_env_real(contrasena):
        return usuario, contrasena
    if not es_valor_env_real(usuario):
        usuario = ""
    if not es_valor_env_real(contrasena):
        contrasena = ""
    if not sys.stdin.isatty():
        logger.error("Faltan CARM_USUARIO/CARM_CONTRASENA. Abre la interfaz para introducir credenciales CARM.")
        registrar_auditoria("credenciales_carm_requeridas", "bloqueado_sin_consola", motivo=motivo)
        return None

    print("")
    print(f"Credenciales CARM requeridas para: {motivo}")
    print("Se guardaran en .env para que el flujo pueda continuar.")
    if not usuario:
        usuario = input("Usuario CARM: ").strip()
    if not contrasena:
        contrasena = getpass.getpass("Contrasena CARM: ").strip()
    if not usuario or not contrasena:
        logger.error("Credenciales CARM incompletas. Flujo detenido.")
        registrar_auditoria("credenciales_carm_requeridas", "incompletas", motivo=motivo)
        return None
    os.environ["CARM_USUARIO"] = usuario
    os.environ["CARM_CONTRASENA"] = contrasena
    os.environ["CARM_RECORDAR_CUENTA"] = "1"
    escribir_env_valores(
        {
            "CARM_USUARIO": usuario,
            "CARM_CONTRASENA": contrasena,
            "CARM_RECORDAR_CUENTA": "1",
        }
    )
    registrar_auditoria("credenciales_carm_introducidas", motivo=motivo, usuario=usuario)
    return usuario, contrasena


def pseudonimo(valor: object, prefijo: str = "persona") -> str:
    texto = str(valor or "").strip().lower()
    if not texto:
        return f"{prefijo}_desconocida"
    digest = hashlib.sha256(texto.encode("utf-8", errors="ignore")).hexdigest()[:10]
    return f"{prefijo}_{digest}"


def sanitizar_feedback(texto: str, max_chars: int = 6000) -> str:
    limpio = str(texto or "")
    for origen, destino in {
        "პასუხა": "respuesta",
        "პასუხa": "respuesta",
        "პასუხ": "respuesta",
    }.items():
        limpio = limpio.replace(origen, destino)
    limpio = re.sub(r"\S*[\u10A0-\u10FF]+\S*", "texto", limpio)
    limpio = re.sub(r"\s+([,.;:!])", r"\1", limpio)
    limpio = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", limpio)
    limpio = re.sub(r"</(script|iframe|object|embed|style|link|meta)[^>]*>", "", limpio, flags=re.I)
    limpio = re.sub(r"\son\w+\s*=\s*(['\"]).*\1", "", limpio, flags=re.I | re.S)
    limpio = re.sub(r"\s(href|src)\s*=\s*(['\"])\s*javascript:[^'\"]*\2", "", limpio, flags=re.I)
    limpio = redactar_texto_sensible(limpio)
    limpio = limpio.strip()
    if max_chars > 0 and len(limpio) > max_chars:
        limpio = limpio[:max_chars].rstrip() + "\n\n[Feedback recortado por limite de seguridad.]"
    return limpio


def normalizar_texto_para_cli(texto: str) -> str:
    reemplazos = {
        "\ufb00": "ff",
        "\ufb01": "fi",
        "\ufb02": "fl",
        "\ufb03": "ffi",
        "\ufb04": "ffl",
    }
    for origen, destino in reemplazos.items():
        texto = texto.replace(origen, destino)
    return unicodedata.normalize("NFC", texto)


def hidden_subprocess_kwargs() -> dict:
    if os.name != "nt":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


def openai_api_key_configurada() -> bool:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    return bool(api_key and api_key.lower() not in {"tu_api_key_aqui", "sk-...", "none", "null"})


def comprobar_openai_api_configurada() -> dict[str, object]:
    if OpenAI is None:
        raise RuntimeError("El paquete openai no esta instalado en la venv.")
    if not openai_api_key_configurada():
        raise RuntimeError("Falta OPENAI_API_KEY en .env o conserva el valor de ejemplo.")
    modelo = (os.getenv("OPENAI_MODEL") or "gpt-5-mini").strip()
    return {
        "api_key_present": True,
        "model": modelo,
        "package": "openai",
    }


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redactar_texto_sensible(record.getMessage())
        record.args = ()
        return True


def registrar_auditoria(accion: str, resultado: str = "ok", **detalles: object) -> None:
    seguro = {}
    for clave, valor in detalles.items():
        if clave.lower() in {"alumno", "usuario", "email", "correo"}:
            seguro[f"{clave}_ref"] = pseudonimo(valor)
        elif clave.lower() in {"contrasena", "password", "token", "cookie", "api_key"}:
            seguro[clave] = "[redactado]"
        else:
            seguro[clave] = redactar_texto_sensible(valor)
    evento = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "accion": accion,
        "resultado": resultado,
        "detalles": seguro,
    }
    try:
        with AUDIT_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(evento, ensure_ascii=False) + "\n")
    except Exception:
        pass


def limpiar_archivos_antiguos(carpeta: Path, dias: int, patrones: tuple[str, ...]) -> int:
    if dias <= 0 or not carpeta.exists():
        return 0
    limite = datetime.now().timestamp() - (dias * 86400)
    borrados = 0
    for patron in patrones:
        for path in carpeta.glob(patron):
            try:
                if path.is_file() and path.stat().st_mtime < limite:
                    path.unlink()
                    borrados += 1
            except Exception:
                continue
    return borrados


def aplicar_retencion_local() -> None:
    logs_borrados = limpiar_archivos_antiguos(LOG_DIR, LOG_RETENTION_DAYS, ("*.log",))
    auditoria_borrada = limpiar_archivos_antiguos(RESPUESTAS_DIR, AUDIT_RETENTION_DAYS, ("auditoria*.jsonl",))
    if logs_borrados or auditoria_borrada:
        registrar_auditoria(
            "retencion_local",
            logs_borrados=logs_borrados,
            auditoria_borrada=auditoria_borrada,
        )


def _borrar_contenido_directorio(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    borrados = 0
    for item in path.iterdir():
        try:
            if item.name == AUDIT_LOG.name:
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
            borrados += 1
        except Exception as exc:
            logger.warning("No se pudo purgar %s: %s", item, exc)
    return borrados


def purgar_datos_personales_locales(pendientes_dir: Path, temporal_dir: Path) -> dict:
    objetivos = {
        "pendientes": pendientes_dir,
        "temporal": temporal_dir,
        "respuestas_extraidas": RESPUESTAS_DIR,
        "correcciones_validadas": CORRECCIONES_DIR,
    }
    resumen = {nombre: _borrar_contenido_directorio(path) for nombre, path in objetivos.items()}
    registrar_auditoria("purga_datos_personales_locales", **resumen)
    return resumen


def _mover_si_existe(origen: Path, destino_dir: Path) -> Path | None:
    if not origen.exists():
        return None
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino = destino_dir / origen.name
    if destino.exists():
        destino = destino_dir / f"{origen.stem}_{datetime.now().strftime('%H%M%S')}{origen.suffix}"
    return shutil.move(str(origen), str(destino)) and destino


def prompts_pendientes_dir(pendientes_dir: Path) -> Path:
    return pendientes_dir / "prompts_codex"


def archivar_prompt_y_correccion_usados(
    correcciones_path: Path,
    temporal_dir: Path,
    modo: str,
    pendientes_dir: Path | None = None,
) -> Path:
    if correcciones_path.parent.name == "prompts_codex":
        prompts_dir = correcciones_path.parent
    elif pendientes_dir is not None:
        prompts_dir = prompts_pendientes_dir(pendientes_dir)
    else:
        prompts_dir = temporal_dir / "prompts_codex"
    archivo_dir = prompts_dir / "archivados" / datetime.now().strftime("%Y%m%d_%H%M%S")
    movidos: list[str] = []

    for path in (
        correcciones_path,
        prompts_dir / "correcciones_codex_combinadas.json",
        prompts_dir / "manifiesto_entregas.json",
    ):
        moved = _mover_si_existe(path, archivo_dir)
        if moved:
            movidos.append(str(moved))

    codigos: set[str] = set(re.findall(r"(ud\d{2}cp\d{2})", correcciones_path.name, flags=re.I))
    if correcciones_path.suffix.lower() == ".csv" and correcciones_path.exists():
        try:
            with correcciones_path.open("r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle, delimiter=";"):
                    actividad = str(row.get("actividad") or "").strip().lower()
                    if re.fullmatch(r"ud\d{2}cp\d{2}", actividad):
                        codigos.add(actividad)
        except Exception as exc:
            logger.warning("No se pudo leer CSV para archivar prompts usados: %s", exc)

    if codigos:
        for codigo in {codigo.lower() for codigo in codigos}:
            for path in prompts_dir.glob(f"*{codigo}*"):
                if path.is_file() and archivo_dir not in path.parents:
                    moved = _mover_si_existe(path, archivo_dir)
                    if moved:
                        movidos.append(str(moved))
    else:
        for patron in ("prompt_*.md", "prompt_*_correccion.json"):
            for path in prompts_dir.glob(patron):
                if path.is_file() and archivo_dir not in path.parents:
                    moved = _mover_si_existe(path, archivo_dir)
                    if moved:
                        movidos.append(str(moved))

    registrar_auditoria(
        "archivar_prompt_correccion_usados",
        modo=modo,
        origen=correcciones_path,
        destino=archivo_dir,
        archivos=len(movidos),
    )
    logger.info("Prompts/correcciones usados archivados en: %s", archivo_dir)
    return archivo_dir


def archivar_prompts_resueltos(prompts: list[Path], modo: str = "resueltos_api") -> Path | None:
    prompts_existentes = [path for path in prompts if path.exists() and path.is_file()]
    if not prompts_existentes:
        return None
    prompts_dir = prompts_existentes[0].parent
    archivo_dir = prompts_dir / "archivados" / datetime.now().strftime(f"%Y%m%d_%H%M%S_{modo}")
    movidos = 0
    for prompt_path in prompts_existentes:
        relacionados = [
            prompt_path,
            prompt_path.with_name(f"{prompt_path.stem}_correccion.json"),
        ]
        for path in relacionados:
            moved = _mover_si_existe(path, archivo_dir)
            if moved:
                movidos += 1
    if movidos:
        logger.info("Prompts ya resueltos archivados en: %s (%s archivo(s)).", archivo_dir, movidos)
        return archivo_dir
    return None


def archivar_archivos_auxiliares_prompts(prompts_dir: Path, modo: str = "auxiliares") -> Path | None:
    candidatos = [
        prompts_dir / "correcciones_codex_combinadas.json",
    ]
    existentes = [path for path in candidatos if path.exists() and path.is_file()]
    if not existentes:
        return None
    archivo_dir = prompts_dir / "archivados" / datetime.now().strftime(f"%Y%m%d_%H%M%S_{modo}")
    movidos = 0
    for path in existentes:
        moved = _mover_si_existe(path, archivo_dir)
        if moved:
            movidos += 1
    if movidos:
        logger.info("Archivos auxiliares de prompts archivados en: %s", archivo_dir)
        return archivo_dir
    return None


def archivar_correccion_importada_codex(
    correcciones_path: Path,
    pendientes_dir: Path,
    temporal_dir: Path,
) -> Path | None:
    if correcciones_path.suffix.lower() != ".json":
        return None

    prompts_dir = prompts_pendientes_dir(pendientes_dir)
    try:
        path_resuelto = correcciones_path.resolve()
        prompts_resuelto = prompts_dir.resolve()
    except Exception:
        return None
    if prompts_resuelto not in path_resuelto.parents:
        return None

    archivo_dir = prompts_dir / "archivados" / datetime.now().strftime("%Y%m%d_%H%M%S_importado_csv")
    candidatos = [correcciones_path]
    if correcciones_path.name.endswith("_correccion.json"):
        prompt_stem = correcciones_path.name[: -len("_correccion.json")]
        candidatos.append(correcciones_path.with_name(f"{prompt_stem}.md"))
    elif correcciones_path.name == "correcciones_codex_combinadas.json":
        candidatos.extend(sorted(prompts_dir.glob("prompt_*.md")))
        candidatos.extend(sorted(prompts_dir.glob("prompt_*_correccion.json")))

    movidos = 0
    for path in candidatos:
        if path.exists() and path.is_file() and archivo_dir not in path.parents:
            moved = _mover_si_existe(path, archivo_dir)
            if moved:
                movidos += 1

    quedan_trabajo = any(prompts_dir.glob("prompt_*.md")) or any(prompts_dir.glob("prompt_*_correccion.json"))
    if not quedan_trabajo:
        for auxiliar in (
            prompts_dir / "manifiesto_entregas.json",
            prompts_dir / "correcciones_codex_combinadas.json",
        ):
            moved = _mover_si_existe(auxiliar, archivo_dir)
            if moved:
                movidos += 1

    if not movidos:
        return None

    registrar_auditoria(
        "archivar_correccion_importada_codex",
        origen=correcciones_path,
        destino=archivo_dir,
        archivos=movidos,
    )
    logger.info("Prompt/correccion importados al CSV archivados en: %s", archivo_dir)
    return archivo_dir


def archivar_resumenes_usados(resultados: list[dict], temporal_dir: Path, modo: str) -> Path | None:
    codigos = {
        str(resultado.get("actividad") or "").strip().lower()
        for resultado in resultados
        if re.fullmatch(r"ud\d{2}cp\d{2}", str(resultado.get("actividad") or "").strip().lower())
    }
    candidatos = [temporal_dir / f"resumen_{codigo}.txt" for codigo in sorted(codigos)]
    candidatos.append(temporal_dir / "resumen.txt")
    existentes = [path for path in candidatos if path.exists() and path.is_file()]
    if not existentes:
        return None

    archivo_dir = temporal_dir / "archivados_resumenes" / datetime.now().strftime(f"%Y%m%d_%H%M%S_{modo}")
    movidos = 0
    for path in existentes:
        moved = _mover_si_existe(path, archivo_dir)
        if moved:
            movidos += 1
    if movidos:
        logger.info("Resumenes usados archivados en: %s (%s archivo(s)).", archivo_dir, movidos)
        return archivo_dir
    return None


def _clave_revision_csv(row: dict) -> tuple[str, str]:
    return (
        _normalizar_linea_comparable(row.get("actividad", "")).strip(),
        _normalizar_linea_comparable(row.get("alumno", "")).strip(),
    )


def actualizar_revision_pendiente_tras_subida(correcciones_path: Path, resultados: list[dict]) -> dict:
    if correcciones_path.suffix.lower() != ".csv" or not correcciones_path.exists():
        return {"aplicado": False, "eliminadas": 0, "restantes": 0}

    estados_subidos = {
        "publicado",
        "guardado_manual_confirmado_por_usuario",
    }
    claves_subidas = {
        _clave_revision_csv(resultado)
        for resultado in resultados
        if str(resultado.get("estado") or "").strip().lower() in estados_subidos
    }
    claves_subidas.discard(("", ""))
    if not claves_subidas:
        return {"aplicado": True, "eliminadas": 0, "restantes": None}

    with correcciones_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    restantes = [row for row in rows if _clave_revision_csv(row) not in claves_subidas]
    eliminadas = len(rows) - len(restantes)
    if eliminadas <= 0:
        return {"aplicado": True, "eliminadas": 0, "restantes": len(rows)}

    archivo_dir = correcciones_path.parent / "archivados_subida" / datetime.now().strftime("%Y%m%d_%H%M%S")
    archivo_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(correcciones_path, archivo_dir / correcciones_path.name)

    if restantes:
        with correcciones_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter=";")
            writer.writeheader()
            writer.writerows(restantes)
    else:
        correcciones_path.unlink()

    registrar_auditoria(
        "actualizar_revision_pendiente_tras_subida",
        origen=correcciones_path,
        eliminadas=eliminadas,
        restantes=len(restantes),
    )
    logger.info(
        "revision_pendiente.csv actualizado tras subida: %s fila(s) eliminada(s), %s pendiente(s).",
        eliminadas,
        len(restantes),
    )
    return {"aplicado": True, "eliminadas": eliminadas, "restantes": len(restantes)}


def archivar_pendientes_con_prompt(manifiesto_path: Path, pendientes_dir: Path) -> int:
    if not manifiesto_path.exists():
        return 0
    try:
        datos = json.loads(manifiesto_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        logger.warning("No se pudo leer manifiesto para archivar pendientes: %s", exc)
        return 0
    if isinstance(datos, dict):
        datos = [datos]
    if not isinstance(datos, list):
        return 0

    archivo_dir = pendientes_dir / "archivados_prompt" / datetime.now().strftime("%Y%m%d_%H%M%S")
    movidos = 0
    for item in datos:
        if not isinstance(item, dict):
            continue
        origen = Path(str(item.get("archivo") or ""))
        try:
            origen_resuelto = origen.resolve()
            pendientes_resuelto = pendientes_dir.resolve()
        except Exception:
            continue
        if not origen.exists() or not origen.is_file():
            continue
        if pendientes_resuelto not in origen_resuelto.parents and origen_resuelto != pendientes_resuelto:
            logger.warning("No se archiva pendiente fuera de la carpeta permitida: %s", origen)
            continue
        actividad = str(item.get("actividad") or "sin_actividad").strip() or "sin_actividad"
        destino_dir = archivo_dir / actividad
        destino_dir.mkdir(parents=True, exist_ok=True)
        destino = destino_dir / origen.name
        if destino.exists():
            destino = destino_dir / f"{origen.stem}_{movidos + 1}{origen.suffix}"
        shutil.move(str(origen), str(destino))
        movidos += 1

    for carpeta in sorted(pendientes_dir.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if carpeta.is_dir() and carpeta != pendientes_dir and "archivados_prompt" not in carpeta.parts:
            try:
                if not any(carpeta.iterdir()):
                    carpeta.rmdir()
            except Exception:
                continue

    registrar_auditoria(
        "archivar_pendientes_con_prompt",
        manifiesto=manifiesto_path,
        destino=archivo_dir,
        archivos=movidos,
    )
    if movidos:
        logger.info("Pendientes incluidos en prompts archivados en: %s", archivo_dir)
    return movidos


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "agente.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)
for handler in logging.getLogger().handlers:
    handler.addFilter(RedactingFilter())


PROMPT_SISTEMA = (
    "Eres un corrector experto en inteligencia artificial aplicada al turismo de Murcia. "
    "Responde SIEMPRE en JSON válido y en español con acentos. "
    "Sé justo: evalúa solo lo que el alumno ha escrito y no inventes méritos."
)

PROMPT_CRITERIOS = """
Corrige la entrega del alumno usando el enunciado extraído de CARM, el contexto de unidad y la rúbrica disponible.
Evalúa en escala de 0 a 10. Devuelve JSON con este formato exacto:
{
  "nota": 0-10,
  "criterios": [
    {"nombre": "Presentación del trabajo", "maximo": 3, "puntuacion": 0-3, "comentario": "..."},
    {"nombre": "Adecuación al enunciado", "maximo": 4, "puntuacion": 0-4, "comentario": "..."},
    {"nombre": "Aplicación práctica", "maximo": 3, "puntuacion": 0-3, "comentario": "..."}
  ],
  "retroalimentacion": "Feedback final, coloquial pero formal, adaptado al caso, al enunciado y a la unidad"
}
""".strip()

MAX_CONTEXTO_PROMPT_CHARS = 14000
MAX_CONTEXTO_API_CHARS = 12000
MAX_CONTEXTO_CACHE_CHARS = 24000
MAX_RESUMEN_DIDACTICO_CHARS = _env_int("MAX_RESUMEN_DIDACTICO_CHARS", 5000)
OPENAI_PROMPT_TOKEN_WARN = _env_int("OPENAI_PROMPT_TOKEN_WARN", 100000)
OPENAI_PROMPT_TOKEN_MAX = _env_int("OPENAI_PROMPT_TOKEN_MAX", 180000)


def estimar_tokens_aprox(texto: str) -> int:
    return max(1, (len(str(texto or "")) + 3) // 4)


def _normalizar_linea_comparable(valor: str) -> str:
    normalizado = unicodedata.normalize("NFKD", str(valor or ""))
    return "".join(c for c in normalizado if not unicodedata.combining(c)).lower()


def limpiar_bloque_carm_para_prompt(texto: str, max_chars: int = MAX_CONTEXTO_PROMPT_CHARS) -> str:
    texto = unescape(texto or "")
    texto = re.sub(r"//<!\[CDATA\[.*//\]\]>", "\n", texto, flags=re.S)
    texto = re.sub(r"<script\b.*</script>", "\n", texto, flags=re.S | re.I)
    texto = texto.replace("\r", "\n")

    patrones_ruido = (
        "salta al contenido principal",
        "panel lateral",
        "notificaciones",
        "no tienes notificaciones",
        "ver todo",
        "area personal",
        "ver perfil",
        "calificaciones",
        "calendario",
        "cambiar rol",
        "cerrar sesion",
        "administracion del sitio",
        "mis cursos",
        "este curso",
        "cuestionarios",
        "foros",
        "herramientas externas",
        "paquetes scorm",
        "manual uso de la plataforma",
        "video tutorial",
        "manual acogida",
        "expediente",
        "javascript",
        "document.body",
        "jsenabled",
        "haga clic en",
        "actividad previa",
        "proxima actividad",
        "ir a...",
        "avisos",
        "notas importantes",
        "readspeaker",
        "tiempo invertido",
        "novedades",
        "dudas y consultas",
        "glosario",
        "hipervinculos",
        "guia didactica",
        "conexion",
        "contenido multimedia",
        "para saber mas",
        "cuestionario de evaluacion",
        "video clase",
    )
    patrones_normalizados = tuple(_normalizar_linea_comparable(p) for p in patrones_ruido)

    lineas_limpias: list[str] = []
    vistas: set[str] = set()
    for linea in texto.splitlines():
        linea = re.sub(r"\s+", " ", linea).strip()
        if not linea or len(linea) <= 2:
            continue
        normalizada = _normalizar_linea_comparable(linea)
        if any(patron in normalizada for patron in patrones_normalizados):
            continue
        if re.fullmatch(r"[{}()[\];,./\\|:_\-*=+<>!¡¿\"'`~0-9\s]+", linea):
            continue
        if normalizada in vistas:
            continue
        vistas.add(normalizada)
        lineas_limpias.append(linea)

    casos_o_recursos = sum(
        1
        for linea in lineas_limpias
        if re.search(r"\bud\d{2}\b|\bcaso pr[áa]ctico\b|contenido imprimible|contenido multimedia", linea, flags=re.I)
    )
    if casos_o_recursos >= 8 and len("\n".join(lineas_limpias)) < 8000:
        return (
            "La cache contiene una pagina indice de Moodle, no contenido didactico util. "
            "No se incluye para evitar ruido en la correccion."
        )

    limpio = re.sub(r"\n{3,}", "\n\n", "\n".join(lineas_limpias)).strip()
    if len(limpio) < 400:
        return (
            "No hay contexto didactico limpio suficiente en cache. "
            "Usa el enunciado, la rubrica y la respuesta del alumno."
        )
    if max_chars > 0 and len(limpio) > max_chars:
        recortado = limpio[:max_chars].rsplit("\n", 1)[0].strip()
        limpio = recortado or limpio[:max_chars].strip()
        limpio += "\n\n[Contexto didactico recortado para ahorrar tokens.]"
    return limpio or "No hay contexto didactico limpio disponible en cache."


def es_contexto_didactico_util(texto: str) -> bool:
    limpio = str(texto or "").strip()
    if len(limpio) < 400:
        return False
    normalizado = _normalizar_linea_comparable(limpio)
    fallbacks = (
        "no hay contexto didactico limpio suficiente en cache",
        "no hay contexto didactico limpio disponible en cache",
        "la cache contiene una pagina indice de moodle",
    )
    return not any(fallback in normalizado for fallback in fallbacks)


def hash_contenido_didactico(texto: str) -> str:
    return hashlib.sha256(str(texto or "").encode("utf-8", errors="ignore")).hexdigest()


def generar_resumen_didactico_local(
    contenido: str,
    codigo: str = "",
    nombre: str = "",
    max_chars: int = MAX_RESUMEN_DIDACTICO_CHARS,
) -> str:
    contenido_limpio = limpiar_bloque_carm_para_prompt(contenido, max_chars=MAX_CONTEXTO_CACHE_CHARS)
    if not es_contexto_didactico_util(contenido_limpio):
        return ""

    lineas = [
        re.sub(r"\s+", " ", linea).strip()
        for linea in contenido_limpio.splitlines()
        if re.sub(r"\s+", " ", linea).strip()
    ]
    if not lineas:
        return ""

    keywords = (
        "objetivo",
        "concepto",
        "definicion",
        "definición",
        "importante",
        "clave",
        "ejemplo",
        "aplicacion",
        "aplicación",
        "herramienta",
        "riesgo",
        "seguridad",
        "etica",
        "ética",
        "privacidad",
        "dato",
        "turistico",
        "turístico",
        "visitante",
        "promocion",
        "promoción",
        "recomendacion",
        "recomendación",
        "buenas practicas",
        "buenas prácticas",
        "debe",
        "evitar",
    )

    seleccionadas: list[str] = []
    vistas: set[str] = set()

    def add(linea: str) -> None:
        normalizada = _normalizar_linea_comparable(linea)
        if not normalizada or normalizada in vistas:
            return
        vistas.add(normalizada)
        seleccionadas.append(linea)

    encabezado = f"Resumen didactico local {codigo.upper()}".strip()
    if nombre:
        encabezado += f" - {nombre}"
    add(encabezado)

    for linea in lineas[:18]:
        add(linea)

    for linea in lineas:
        normalizada = _normalizar_linea_comparable(linea)
        parece_titulo = len(linea) <= 120 and linea.upper() == linea and any(c.isalpha() for c in linea)
        relevante = any(keyword in normalizada for keyword in (_normalizar_linea_comparable(k) for k in keywords))
        if parece_titulo or relevante:
            add(linea)
        if len("\n".join(seleccionadas)) >= max_chars * 1.4:
            break

    resumen = "\n".join(seleccionadas)
    if len(resumen) > max_chars:
        resumen = resumen[:max_chars].rsplit("\n", 1)[0].strip() or resumen[:max_chars].strip()
        resumen += "\n\n[Resumen didactico local recortado para ahorrar tokens.]"
    return resumen.strip()


def seleccionar_contexto_para_actividad(contexto: str, actividad_codigo: str) -> str:
    texto = str(contexto or "").strip()
    unidad = re.match(r"^(ud\d{2})cp\d{2}$", str(actividad_codigo or "").strip().lower())
    if not texto or not unidad:
        return texto
    unidad_codigo = unidad.group(1).upper()
    patron = re.compile(r"^##\s+(UD\d{2})\b.*$", flags=re.I | re.M)
    matches = list(patron.finditer(texto))
    for idx, match in enumerate(matches):
        if match.group(1).upper() != unidad_codigo:
            continue
        inicio = match.start()
        fin = matches[idx + 1].start() if idx + 1 < len(matches) else len(texto)
        return texto[inicio:fin].strip()
    return texto


@dataclass
class EnvioPendiente:
    alumno: str
    archivo: Path
    actividad_codigo: str = DEFAULT_ACTIVIDAD_CODIGO
    actividad_nombre: str = ""
    actividad_enunciado: str = ""
    estado_entrega: str = ""
    archivo_original_nombre: str = ""


@dataclass
class LecturaEntrega:
    texto: str
    requiere_revision_manual: bool = False
    motivo: str = ""
    advertencia: str = ""


class TextoVisibleHTMLParser(HTMLParser):
    BLOQUES_OCULTOS = {"script", "style", "noscript", "svg", "canvas", "template", "head", "meta", "link"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._oculto = 0
        self.fragmentos: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in self.BLOQUES_OCULTOS:
            self._oculto += 1
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr", "section", "article"}:
            self.fragmentos.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.BLOQUES_OCULTOS and self._oculto:
            self._oculto -= 1
        if tag in {"p", "div", "li", "h1", "h2", "h3", "h4", "tr", "section", "article"}:
            self.fragmentos.append("\n")

    def handle_data(self, data: str) -> None:
        if self._oculto:
            return
        texto = data.strip()
        if texto:
            self.fragmentos.append(texto)

    def texto(self) -> str:
        unido = " ".join(self.fragmentos)
        unido = unescape(unido)
        unido = re.sub(r"[ \t\r\f\v]+", " ", unido)
        unido = re.sub(r"\n\s*", "\n", unido)
        unido = re.sub(r"\n{3,}", "\n\n", unido)
        return unido.strip()


class CacheCursoCarm:
    def __init__(
        self,
        path: Path | None = None,
        course_url: str = CARM_COURSE_URL,
        fecha_fin: str = CARM_COURSE_END_DATE,
    ):
        self.course_url = course_url
        self.course_id = self._extraer_course_id(course_url)
        self.fecha_fin = (fecha_fin or "").strip()
        self.path = path or CACHE_DIR / f"curso_{self.course_id or 'carm'}.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._inicializar()

    @staticmethod
    def _extraer_course_id(url: str) -> str:
        query = dict(parse_qsl(urlparse(url).query))
        return query.get("id", "carm")

    @staticmethod
    def _ahora() -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _conectar(self):
        return sqlite3.connect(self.path)

    def _inicializar(self) -> None:
        with self._conectar() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS curso (
                    course_id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    titulo TEXT,
                    fecha_fin TEXT,
                    actualizado_en TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS unidad (
                    course_id TEXT NOT NULL,
                    codigo TEXT NOT NULL,
                    nombre TEXT,
                    contenido_imprimible TEXT,
                    resumen_didactico TEXT,
                    hash_contenido TEXT,
                    actualizado_en TEXT NOT NULL,
                    PRIMARY KEY (course_id, codigo)
                );

                CREATE TABLE IF NOT EXISTS actividad (
                    course_id TEXT NOT NULL,
                    codigo TEXT NOT NULL,
                    unidad_codigo TEXT,
                    nombre TEXT,
                    tipo TEXT,
                    url TEXT,
                    url_grading TEXT,
                    filtro TEXT,
                    enunciado TEXT,
                    actualizado_en TEXT NOT NULL,
                    PRIMARY KEY (course_id, codigo)
                );
                """
            )
            columnas = {
                row[1]
                for row in con.execute("PRAGMA table_info(curso)").fetchall()
            }
            if "fecha_fin" not in columnas:
                con.execute("ALTER TABLE curso ADD COLUMN fecha_fin TEXT")
            columnas_unidad = {
                row[1]
                for row in con.execute("PRAGMA table_info(unidad)").fetchall()
            }
            if "resumen_didactico" not in columnas_unidad:
                con.execute("ALTER TABLE unidad ADD COLUMN resumen_didactico TEXT")
            if "hash_contenido" not in columnas_unidad:
                con.execute("ALTER TABLE unidad ADD COLUMN hash_contenido TEXT")

    def guardar_curso(self, titulo: str = "") -> None:
        with self._conectar() as con:
            con.execute(
                """
                INSERT INTO curso (course_id, url, titulo, fecha_fin, actualizado_en)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(course_id) DO UPDATE SET
                    url=excluded.url,
                    titulo=excluded.titulo,
                    fecha_fin=excluded.fecha_fin,
                    actualizado_en=excluded.actualizado_en
                """,
                (self.course_id, self.course_url, titulo, self.fecha_fin, self._ahora()),
            )

    def curso_expirado(self) -> bool:
        if not self.fecha_fin:
            return False
        try:
            fecha_fin = datetime.strptime(self.fecha_fin, "%Y-%m-%d").date()
        except ValueError:
            logger.warning(
                "CARM_COURSE_END_DATE no tiene formato YYYY-MM-DD; no se purga cache automáticamente."
            )
            return False
        return datetime.now().date() > fecha_fin

    def purgar_si_expirada(self) -> bool:
        if self.curso_expirado() and self.path.exists():
            self.path.unlink()
            self._inicializar()
            logger.info(f"Cache del curso expirada y borrada automáticamente: {self.path}")
            return True
        return False

    def guardar_unidad(self, codigo: str, nombre: str = "", contenido_imprimible: str = "") -> None:
        if not codigo:
            return
        contenido_limpio = (
            limpiar_bloque_carm_para_prompt(contenido_imprimible, max_chars=MAX_CONTEXTO_CACHE_CHARS)
            if str(contenido_imprimible or "").strip()
            else ""
        )
        if contenido_limpio and not es_contexto_didactico_util(contenido_limpio):
            logger.info("No se guarda contenido imprimible de %s porque no contiene contexto didactico util.", codigo)
            contenido_limpio = ""
        resumen_didactico = (
            generar_resumen_didactico_local(contenido_limpio, codigo=codigo, nombre=nombre)
            if contenido_limpio
            else ""
        )
        hash_contenido = hash_contenido_didactico(contenido_limpio) if contenido_limpio else ""
        with self._conectar() as con:
            con.execute(
                """
                INSERT INTO unidad (
                    course_id, codigo, nombre, contenido_imprimible,
                    resumen_didactico, hash_contenido, actualizado_en
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(course_id, codigo) DO UPDATE SET
                    nombre=COALESCE(NULLIF(excluded.nombre, ''), unidad.nombre),
                    contenido_imprimible=COALESCE(NULLIF(excluded.contenido_imprimible, ''), unidad.contenido_imprimible),
                    resumen_didactico=COALESCE(NULLIF(excluded.resumen_didactico, ''), unidad.resumen_didactico),
                    hash_contenido=COALESCE(NULLIF(excluded.hash_contenido, ''), unidad.hash_contenido),
                    actualizado_en=excluded.actualizado_en
                """,
                (self.course_id, codigo, nombre, contenido_limpio, resumen_didactico, hash_contenido, self._ahora()),
            )
        if contenido_imprimible and len(contenido_limpio) + 1000 < len(contenido_imprimible):
            logger.info(
                "Contexto didactico optimizado al guardar %s: %s -> %s caracteres.",
                codigo,
                len(contenido_imprimible),
                len(contenido_limpio),
            )

    def guardar_actividad(self, actividad: dict) -> None:
        codigo = actividad.get("codigo", "")
        if not codigo:
            return
        with self._conectar() as con:
            con.execute(
                """
                INSERT INTO actividad (
                    course_id, codigo, unidad_codigo, nombre, tipo, url, url_grading,
                    filtro, enunciado, actualizado_en
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(course_id, codigo) DO UPDATE SET
                    unidad_codigo=excluded.unidad_codigo,
                    nombre=excluded.nombre,
                    tipo=excluded.tipo,
                    url=excluded.url,
                    url_grading=excluded.url_grading,
                    filtro=excluded.filtro,
                    enunciado=COALESCE(NULLIF(excluded.enunciado, ''), actividad.enunciado),
                    actualizado_en=excluded.actualizado_en
                """,
                (
                    self.course_id,
                    codigo,
                    actividad.get("unidad_codigo", ""),
                    actividad.get("nombre", ""),
                    actividad.get("tipo", ""),
                    actividad.get("url", ""),
                    actividad.get("url_grading", ""),
                    actividad.get("filtro", ""),
                    actividad.get("enunciado", ""),
                    self._ahora(),
                ),
            )

    def obtener_contexto_unidades(self, unidades: set[str] | None = None) -> str:
        unidades = unidades or set()
        with self._conectar() as con:
            columnas_unidad = {
                row[1]
                for row in con.execute("PRAGMA table_info(unidad)").fetchall()
            }
            tiene_resumen = "resumen_didactico" in columnas_unidad
            if unidades:
                placeholders = ",".join("?" for _ in unidades)
                select_cols = (
                    "codigo, nombre, contenido_imprimible, COALESCE(resumen_didactico, ''), COALESCE(hash_contenido, '')"
                    if tiene_resumen
                    else "codigo, nombre, contenido_imprimible, '', ''"
                )
                rows = con.execute(
                    f"""
                    SELECT {select_cols}
                    FROM unidad
                    WHERE course_id = ? AND codigo IN ({placeholders})
                    ORDER BY codigo
                    """,
                    (self.course_id, *sorted(unidades)),
                ).fetchall()
            else:
                select_cols = (
                    "codigo, nombre, contenido_imprimible, COALESCE(resumen_didactico, ''), COALESCE(hash_contenido, '')"
                    if tiene_resumen
                    else "codigo, nombre, contenido_imprimible, '', ''"
                )
                rows = con.execute(
                    f"""
                    SELECT {select_cols}
                    FROM unidad
                    WHERE course_id = ?
                    ORDER BY codigo
                    """,
                    (self.course_id,),
                ).fetchall()
        partes = []
        actualizaciones: list[tuple[str, str, str, str]] = []
        for codigo, nombre, contenido, resumen, hash_guardado in rows:
            if contenido:
                contenido_limpio = limpiar_bloque_carm_para_prompt(
                    contenido,
                    max_chars=MAX_CONTEXTO_CACHE_CHARS,
                )
                if not es_contexto_didactico_util(contenido_limpio):
                    actualizaciones.append(("", "", "", codigo))
                    logger.info("Contexto didactico cache descartado para %s por ser fallback o ruido.", codigo)
                    continue
                hash_actual = hash_contenido_didactico(contenido_limpio)
                resumen_limpio = str(resumen or "").strip()
                if not resumen_limpio or hash_guardado != hash_actual:
                    resumen_limpio = generar_resumen_didactico_local(contenido_limpio, codigo=codigo, nombre=nombre)
                if contenido_limpio != contenido or resumen_limpio != resumen or hash_guardado != hash_actual:
                    actualizaciones.append((contenido_limpio, resumen_limpio, hash_actual, codigo))
                    logger.info(
                        "Contexto didactico cache preparado para %s: completo %s chars, resumen %s chars.",
                        codigo,
                        len(contenido_limpio),
                        len(resumen_limpio),
                    )
                contexto_para_prompt = resumen_limpio or contenido_limpio
                partes.append(f"## {codigo.upper()} - {nombre or 'Contenido imprimible'}\n{contexto_para_prompt}")
        if actualizaciones:
            with self._conectar() as con:
                con.executemany(
                    """
                    UPDATE unidad
                    SET contenido_imprimible = ?, resumen_didactico = ?, hash_contenido = ?, actualizado_en = ?
                    WHERE course_id = ? AND codigo = ?
                    """,
                    [
                        (contenido_limpio, resumen_limpio, hash_actual, self._ahora(), self.course_id, codigo)
                        for contenido_limpio, resumen_limpio, hash_actual, codigo in actualizaciones
                    ],
                )
        return "\n\n".join(partes)

    def enriquecer_actividad(self, actividad: dict) -> dict:
        codigo = actividad.get("codigo", "")
        if not codigo:
            return actividad
        with self._conectar() as con:
            row = con.execute(
                """
                SELECT unidad_codigo, nombre, url, url_grading, filtro, enunciado
                FROM actividad
                WHERE course_id = ? AND codigo = ?
                """,
                (self.course_id, codigo),
            ).fetchone()
        if not row:
            return actividad
        unidad_codigo, nombre, url, url_grading, filtro, enunciado = row
        actividad.setdefault("unidad_codigo", unidad_codigo or "")
        actividad.setdefault("nombre", nombre or "")
        actividad.setdefault("url", url or "")
        actividad["url_grading"] = actividad.get("url_grading") or url_grading or ""
        actividad["filtro"] = actividad.get("filtro") or filtro or ""
        actividad["enunciado"] = actividad.get("enunciado") or enunciado or ""
        return actividad

    def borrar(self) -> bool:
        if self.path.exists():
            self.path.unlink()
            return True
        return False


class GestorPrompts:
    DEFAULT_PROMPTS_PATH = Path("prompts_correccion.json")

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else self.DEFAULT_PROMPTS_PATH
        self.config = self._cargar()

    def _cargar(self) -> dict:
        if not self.path.exists():
            logger.warning(f"No se encontró archivo de prompts {self.path}; usando prompts internos.")
            return {}

        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"No se pudo leer {self.path}: {e}. Usando prompts internos.")
            return {}

    def obtener(self, actividad_codigo: str) -> dict:
        prompts = self.config.get("prompts", {})
        bloque = (
            prompts.get(actividad_codigo)
            or prompts.get(actividad_codigo.lower())
            or prompts.get("default")
            or {}
        )
        return {
            "sistema": bloque.get("sistema", PROMPT_SISTEMA),
            "criterios": bloque.get("criterios", PROMPT_CRITERIOS),
        }


class CorrectorIA:
    def __init__(
        self,
        api_key: str | None = None,
        modelo: str | None = None,
        usar_ia: bool = True,
        prompts_path: str | Path | None = None,
        requerir_ia: bool = False,
    ):
        self.api_key = (api_key or os.getenv("OPENAI_API_KEY") or "").strip()
        if self.api_key.lower() in {"tu_api_key_aqui", "sk-...", "none", "null"}:
            self.api_key = ""
        self.modelo = modelo or os.getenv("OPENAI_MODEL", "gpt-5-mini")
        self.requerir_ia = requerir_ia
        self.cliente = OpenAI(api_key=self.api_key) if (usar_ia and OpenAI and self.api_key) else None
        self.prompts = GestorPrompts(prompts_path)

    def corregir(
        self,
        respuesta: str,
        contexto_unidad: str,
        actividad_codigo: str = DEFAULT_ACTIVIDAD_CODIGO,
        enunciado_actividad: str = "",
    ) -> dict:
        if not respuesta.strip():
            return self._correccion_vacia()

        if self.cliente is None:
            if self.requerir_ia:
                raise RuntimeError("OPENAI_API_KEY o paquete openai no disponible; correccion API bloqueada.")
            logger.warning("OPENAI_API_KEY o paquete openai no disponible; usando corrección de respaldo")
            return self._correccion_respaldo()

        prompt_cfg = self.prompts.obtener(actividad_codigo)
        contexto_relevante = seleccionar_contexto_para_actividad(contexto_unidad, actividad_codigo)
        contexto_api = limpiar_bloque_carm_para_prompt(contexto_relevante, max_chars=MAX_CONTEXTO_API_CHARS)
        enunciado_api = limpiar_bloque_carm_para_prompt(enunciado_actividad, max_chars=5000) if enunciado_actividad else ""
        prompt_usuario = (
            f"{prompt_cfg['criterios']}\n\n"
            "REGLA DE IDIOMA: redacta todo el feedback en espanol usando solo alfabeto latino, numeros y puntuacion comun. "
            "No uses caracteres de otros alfabetos.\n\n"
            f"ACTIVIDAD: {actividad_codigo}\n\n"
            f"ENUNCIADO EXTRAÍDO DE CARM:\n{enunciado_api or 'No disponible'}\n\n"
            f"CONTEXTO DE UNIDAD (Contenido imprimible):\n{contexto_api}\n\n"
            f"RESPUESTA DEL ALUMNO A EVALUAR:\n{respuesta}"
        )

        try:
            respuesta_api = self.cliente.chat.completions.create(
                model=self.modelo,
                messages=[
                    {"role": "system", "content": prompt_cfg["sistema"]},
                    {"role": "user", "content": prompt_usuario},
                ],
                response_format={"type": "json_object"},
                max_completion_tokens=1400,
            )
            contenido = respuesta_api.choices[0].message.content or "{}"
            data = json.loads(contenido)
            data["nota"] = self._normalizar_nota(data.get("nota", 0))
            data.setdefault("criterios", [])
            data.setdefault("retroalimentacion", "Sin retroalimentación generada.")
            return data
        except Exception as e:
            if self.requerir_ia:
                raise RuntimeError(f"Error corrigiendo con OpenAI API: {e}") from e
            logger.error(f"Error corrigiendo con IA: {e}")
            return {
                "nota": 0,
                "criterios": [],
                "retroalimentacion": f"No se pudo generar corrección automática: {e}",
            }

    def corregir_lote(
        self,
        entregas: list[tuple[EnvioPendiente, str]],
        contexto_unidad: str,
        actividad_codigo: str,
    ) -> list[dict]:
        if not entregas:
            return []

        if self.cliente is None:
            if self.requerir_ia:
                raise RuntimeError("OPENAI_API_KEY o paquete openai no disponible; correccion API bloqueada.")
            logger.warning(
                "OPENAI_API_KEY o paquete openai no disponible; usando corrección de respaldo por lote"
            )
            return [
                self._correccion_vacia() if not respuesta.strip() else self._correccion_respaldo()
                for _, respuesta in entregas
            ]

        payload_entregas = [
            {
                "id": str(idx),
                "alumno": envio.alumno,
                "archivo": envio.archivo.name,
                "respuesta": respuesta,
            }
            for idx, (envio, respuesta) in enumerate(entregas)
        ]
        enunciado_actividad = next((envio.actividad_enunciado for envio, _ in entregas if envio.actividad_enunciado), "")

        prompt_cfg = self.prompts.obtener(actividad_codigo)
        contexto_relevante = seleccionar_contexto_para_actividad(contexto_unidad, actividad_codigo)
        contexto_api = limpiar_bloque_carm_para_prompt(contexto_relevante, max_chars=MAX_CONTEXTO_API_CHARS)
        enunciado_api = limpiar_bloque_carm_para_prompt(enunciado_actividad, max_chars=5000) if enunciado_actividad else ""
        prompt_usuario = (
            f"{prompt_cfg['criterios']}\n\n"
            "REGLA DE IDIOMA: redacta todo el feedback en espanol usando solo alfabeto latino, numeros y puntuacion comun. "
            "No uses caracteres de otros alfabetos.\n\n"
            f"ACTIVIDAD: {actividad_codigo}\n\n"
            f"ENUNCIADO EXTRAÍDO DE CARM:\n{enunciado_api or 'No disponible'}\n\n"
            f"CONTEXTO DE UNIDAD (Contenido imprimible):\n{contexto_api}\n\n"
            "Corrige todas las entregas siguientes en una sola respuesta. "
            "Devuelve JSON con este formato exacto:\n"
            "{\n"
            '  "correcciones": [\n'
            "    {\n"
            '      "id": "0",\n'
            '      "alumno": "Nombre del alumno",\n'
            '      "nota": 0-10,\n'
            '      "criterios": [\n'
            '        {"nombre": "Presentación del trabajo", "maximo": 3, "puntuacion": 0-3, "comentario": "..."},\n'
            '        {"nombre": "Adecuación al enunciado", "maximo": 4, "puntuacion": 0-4, "comentario": "..."},\n'
            '        {"nombre": "Aplicación práctica", "maximo": 3, "puntuacion": 0-3, "comentario": "..."}\n'
            "      ],\n"
            '      "retroalimentacion": "Feedback final, coloquial pero formal, adaptado al caso y la unidad"\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "ENTREGAS A EVALUAR:\n"
            f"{json.dumps(payload_entregas, ensure_ascii=False, indent=2)}"
        )

        try:
            respuesta_api = self.cliente.chat.completions.create(
                model=self.modelo,
                messages=[
                    {"role": "system", "content": prompt_cfg["sistema"]},
                    {"role": "user", "content": prompt_usuario},
                ],
                response_format={"type": "json_object"},
                max_completion_tokens=min(16000, 900 + (1200 * len(entregas))),
            )
            contenido = respuesta_api.choices[0].message.content or "{}"
            data = json.loads(contenido)
            correcciones = data.get("correcciones", [])
            por_id = {
                str(c.get("id")): self._normalizar_correccion(c)
                for c in correcciones
                if isinstance(c, dict)
            }
            return [
                por_id.get(str(idx), self._correccion_error("La IA no devolvió corrección para esta entrega."))
                for idx, _ in enumerate(entregas)
            ]
        except Exception as e:
            if self.requerir_ia:
                raise RuntimeError(f"Error corrigiendo lote {actividad_codigo} con OpenAI API: {e}") from e
            logger.error(f"Error corrigiendo lote {actividad_codigo} con IA: {e}")
            return [
                self.corregir(
                    respuesta,
                    contexto_unidad,
                    actividad_codigo=actividad_codigo,
                    enunciado_actividad=envio.actividad_enunciado,
                )
                for envio, respuesta in entregas
            ]

    @staticmethod
    def _normalizar_nota(valor) -> float:
        try:
            nota = float(str(valor).replace(",", "."))
        except Exception:
            return 0.0
        return max(0.0, min(10.0, round(nota, 2)))

    @classmethod
    def _normalizar_correccion(cls, correccion: dict) -> dict:
        return {
            "nota": cls._normalizar_nota(correccion.get("nota", 0)),
            "criterios": correccion.get("criterios", []),
            "retroalimentacion": correccion.get(
                "retroalimentacion",
                "Sin retroalimentación generada.",
            ),
        }

    @staticmethod
    def _correccion_vacia() -> dict:
        return {
            "nota": 0,
            "criterios": [
                {
                    "nombre": "Presentación del trabajo",
                    "maximo": 3,
                    "puntuacion": 0,
                    "comentario": "No se pudo evaluar la presentación por falta de contenido.",
                },
                {
                    "nombre": "Adecuación al enunciado",
                    "maximo": 4,
                    "puntuacion": 0,
                    "comentario": "No hay desarrollo suficiente para responder a lo pedido en el enunciado.",
                },
                {
                    "nombre": "Aplicación práctica",
                    "maximo": 3,
                    "puntuacion": 0,
                    "comentario": "No se aportan ideas aplicables al caso.",
                },
            ],
            "retroalimentacion": "No he podido corregir este ejercicio porque el archivo aparece vacío o ilegible.",
        }

    @staticmethod
    def _correccion_respaldo() -> dict:
        return {
            "nota": 7.0,
            "criterios": [
                {
                    "nombre": "Presentación del trabajo",
                    "maximo": 3,
                    "puntuacion": 2.2,
                    "comentario": "La presentación es correcta, aunque se puede ordenar mejor la estructura.",
                },
                {
                    "nombre": "Adecuación al enunciado",
                    "maximo": 4,
                    "puntuacion": 2.8,
                    "comentario": "Responde a una parte importante del enunciado, aunque faltan detalles o precisión.",
                },
                {
                    "nombre": "Aplicación práctica",
                    "maximo": 3,
                    "puntuacion": 2.0,
                    "comentario": "Aplica ideas útiles, aunque conviene aterrizarlas mejor al contexto práctico.",
                },
            ],
            "retroalimentacion": "Buen trabajo general. Vas en la línea correcta, pero te recomiendo ajustar mejor la respuesta al enunciado y proponer acciones más concretas para el caso.",
        }

    @staticmethod
    def _correccion_error(mensaje: str) -> dict:
        return {
            "nota": 0,
            "criterios": [],
            "retroalimentacion": mensaje,
        }

    @staticmethod
    def correccion_revision_manual(motivo: str) -> dict:
        return {
            "nota": 0,
            "criterios": [
                {
                    "nombre": "Revisión manual",
                    "maximo": 10,
                    "puntuacion": 0,
                    "comentario": motivo,
                }
            ],
            "retroalimentacion": (
                "Esta entrega necesita revisión manual antes de calificarla. "
                f"Motivo: {motivo}"
            ),
            "estado": "revision_manual_necesaria",
        }


class ExtractorCarm:
    def __init__(
        self,
        usuario: str,
        contrasena: str,
        pendientes_dir: Path,
        mantener_navegador: bool = False,
        guardar_evidencias: bool = False,
        guardar_trace_subida: bool = False,
        unidades: set[str] | None = None,
        actividades: set[str] | None = None,
        cache: CacheCursoCarm | None = None,
        usar_cache: bool = False,
        recordar_cuenta: bool = CARM_RECORDAR_CUENTA,
    ):
        self.usuario = usuario
        self.contrasena = contrasena
        self.pendientes_dir = pendientes_dir
        self.mantener_navegador = mantener_navegador
        self.guardar_evidencias = guardar_evidencias
        self.guardar_trace_subida = guardar_trace_subida
        self.unidades = unidades or set()
        self.actividades = actividades or set()
        self.cache = cache
        self.usar_cache = usar_cache
        self.recordar_cuenta = recordar_cuenta
        self.registros_envios: list[dict] = []

    @staticmethod
    def _normalizar(texto: str) -> str:
        texto = re.sub(r"\s+", " ", (texto or "")).strip().lower()
        normalizado = unicodedata.normalize("NFKD", texto)
        return "".join(c for c in normalizado if not unicodedata.combining(c))

    @classmethod
    def _coincide_alumno(cls, alumno: str, texto: str) -> bool:
        alumno_norm = cls._normalizar(alumno)
        texto_norm = cls._normalizar(texto)
        if not alumno_norm or not texto_norm:
            return False
        if alumno_norm in texto_norm:
            return True
        tokens = [token for token in alumno_norm.split() if len(token) > 1]
        if len(tokens) < 2:
            return False
        coincidencias = sum(1 for token in tokens if token in texto_norm)
        minimo = len(tokens) if len(tokens) <= 3 else len(tokens) - 1
        return coincidencias >= minimo

    @staticmethod
    def _sanitizar_nombre(nombre: str) -> str:
        limpio = re.sub(r"[\\/:*\"<>|]", "_", nombre.strip())
        return re.sub(r"\s+", " ", limpio)[:120] or "alumno"

    @staticmethod
    def _texto_limpio(texto: str) -> str:
        return re.sub(r"\s+", " ", (texto or "")).strip()

    @staticmethod
    def _normalizar_codigo_unidad(valor: str) -> str:
        texto = (valor or "").strip().lower()
        m = re.search(r"(:ud|unidad)\s*0*(\d{1,2})", texto)
        if not m:
            return texto
        return f"ud{int(m.group(1)):02d}"

    @staticmethod
    def _unidad_desde_codigo_actividad(codigo: str) -> str:
        m = re.match(r"^(ud\d{2})cp\d{2}$", (codigo or "").lower())
        return m.group(1) if m else ""

    @classmethod
    def _actividad_permitida(cls, codigo: str, unidades: set[str], actividades: set[str]) -> bool:
        codigo = (codigo or "").lower()
        if actividades and codigo not in actividades:
            return False
        if unidades and cls._unidad_desde_codigo_actividad(codigo) not in unidades:
            return False
        return True

    @staticmethod
    def _redactar_texto_sensible(texto: str) -> str:
        texto = re.sub(r"[\w.\-+%]+@[\w.\-]+\.[A-Za-z]{2,}", "[email-redactado]", texto or "")
        texto = re.sub(r"(sesskey=)[^&\"'>\s]+", r"\1[redactado]", texto, flags=re.I)
        texto = re.sub(r'("sesskey"\s*:\s*")[^"]+', r'\1[redactado]', texto, flags=re.I)
        texto = re.sub(r"(password|contrasena|contraseña)(=|%3D)[^&\"'>\s]+", r"\1\2[redactado]", texto, flags=re.I)
        return texto

    @classmethod
    def _limpiar_diagnostico_json(cls, diagnostico: dict, incluir_enlaces: bool = False) -> dict:
        actividades = []
        for act in diagnostico.get("actividades_obligatorias", []):
            limpio = {
                "nombre": act.get("nombre", ""),
                "codigo": act.get("codigo", ""),
                "filtro": act.get("filtro", ""),
            }
            for clave in ("filas_grading_detectadas", "columnas_grading", "error_grading"):
                if clave in act:
                    limpio[clave] = act[clave]
            if incluir_enlaces:
                limpio["url"] = cls._redactar_texto_sensible(act.get("url", ""))
                limpio["url_grading"] = cls._redactar_texto_sensible(act.get("url_grading", ""))
            actividades.append(limpio)

        return {
            "course_url": cls._redactar_texto_sensible(diagnostico.get("course_url", "")),
            "title": diagnostico.get("title", ""),
            "assign_links_count": diagnostico.get("assign_links_count", 0),
            "actividades_obligatorias_count": diagnostico.get("actividades_obligatorias_count", 0),
            "actividades_obligatorias": actividades,
        }

    @classmethod
    def _es_estado_sin_entrega(cls, estado: str) -> bool:
        normalizado = cls._normalizar(estado)
        return any(
            patron in normalizado
            for patron in (
                "sin entregar",
                "no entregado",
                "no ha enviado",
                "no se ha enviado",
                "borrador",
            )
        )

    @classmethod
    def _inferir_codigo_actividad(cls, nombre_actividad: str, nombre_unidad: str = "") -> str:
        texto = cls._normalizar(f"{nombre_unidad} {nombre_actividad}")

        unidad = None
        for patron in (
            r"\bud\s*0*(\d{1,2})\b",
            r"\bunidad\s*0*(\d{1,2})\b",
            r"\btema\s*0*(\d{1,2})\b",
        ):
            m = re.search(patron, texto)
            if m:
                unidad = int(m.group(1))
                break

        caso = None
        for patron in (
            r"\bcp\s*0*(\d{1,2})\b",
            r"\bcaso\s+practico\s*0*(\d{1,2})\b",
            r"\bcaso\s+practico\b.*\b0*(\d{1,2})\b",
        ):
            m = re.search(patron, texto)
            if m:
                caso = int(m.group(1))
                break

        if unidad is None:
            unidad = int(DEFAULT_ACTIVIDAD_CODIGO[2:4])
            logger.warning(
                "No se pudo detectar la unidad en '%s'. Usando %s.",
                nombre_actividad,
                DEFAULT_ACTIVIDAD_CODIGO[:4],
            )
        if caso is None:
            caso = int(DEFAULT_ACTIVIDAD_CODIGO[6:8])
            logger.warning(
                "No se pudo detectar el caso práctico en '%s'. Usando %s.",
                nombre_actividad,
                DEFAULT_ACTIVIDAD_CODIGO[4:],
            )

        return f"ud{unidad:02d}cp{caso:02d}"

    @classmethod
    async def _obtener_nombre_unidad(cls, enlace) -> str:
        try:
            return await enlace.evaluate(
                """(el) => {
                    const section = el.closest('li.section, section, .course-section, .section, [data-sectionid]');
                    if (!section) return '';
                    const heading = section.querySelector(
                        '.sectionname, .section-title, h2, h3, h4, [role="heading"]'
                    );
                    return heading ? heading.textContent.trim() : '';
                }"""
            )
        except Exception:
            return ""

    @staticmethod
    def _agregar_action_grading(url: str) -> str:
        p = urlparse(url)
        q = dict(parse_qsl(p.query))
        q["action"] = "grading"
        return urlunparse((p.scheme, p.netloc, p.path, p.params, urlencode(q), p.fragment))

    @staticmethod
    def _url_grading_requiere_calificacion(url: str) -> str:
        p = urlparse(url)
        q = dict(parse_qsl(p.query))
        q["action"] = "grading"
        q["filter"] = "require_grading"
        q["perpage"] = "1000"
        for clave in (
            "page",
            "tifirst",
            "tilast",
            "tfirst",
            "tlast",
            "ifirst",
            "ilast",
            "sifirst",
            "silast",
            "firstname",
            "lastname",
            "firstinitial",
            "lastinitial",
            "initial",
        ):
            q.pop(clave, None)
        return urlunparse((p.scheme, p.netloc, p.path, p.params, urlencode(q), p.fragment))

    @staticmethod
    def _url_grading_todos(url: str) -> str:
        p = urlparse(url)
        q = dict(parse_qsl(p.query))
        q["action"] = "grading"
        q["perpage"] = "1000"
        q.pop("filter", None)
        for clave in (
            "page",
            "tifirst",
            "tilast",
            "tfirst",
            "tlast",
            "ifirst",
            "ilast",
            "sifirst",
            "silast",
            "firstname",
            "lastname",
            "firstinitial",
            "lastinitial",
            "initial",
        ):
            q.pop(clave, None)
        return urlunparse((p.scheme, p.netloc, p.path, p.params, urlencode(q), p.fragment))

    @staticmethod
    def _url_vista_actividad(url: str) -> str:
        p = urlparse(url)
        q = dict(parse_qsl(p.query))
        q.pop("action", None)
        q.pop("filter", None)
        q.pop("tsort", None)
        q.pop("tdir", None)
        return urlunparse((p.scheme, p.netloc, p.path, p.params, urlencode(q), p.fragment))

    @classmethod
    def _extraer_resumen_accion_actividad(cls, texto: str) -> dict:
        normalizado = cls._normalizar(texto)

        def numero_antes_de(patron: str) -> int | None:
            match = re.search(patron, normalizado)
            if not match:
                return None
            try:
                return int(match.group(1).replace(".", ""))
            except ValueError:
                return None

        return {
            "texto": texto.strip(),
            "enviados": numero_antes_de(r"(\d[\d.]*)\s+(:de\s+\d[\d.]*\s+)enviad"),
            "total": numero_antes_de(r"\d[\d.]*\s+de\s+(\d[\d.]*)\s+enviad"),
            "sin_calificar": numero_antes_de(r"(\d[\d.]*)\s+sin\s+calificar"),
            "menciona_enviados": "enviad" in normalizado,
            "menciona_sin_calificar": "sin calificar" in normalizado,
        }

    async def _login(self, page) -> None:
        await page.goto(CARM_MY_URL, wait_until="domcontentloaded")
        if not await page.locator("input[name='username'], #username").count():
            return

        await page.goto(CARM_LOGIN_URL, wait_until="networkidle")
        await page.fill("input[name='username'], #username", self.usuario)
        await page.fill("input[name='password'], #password", self.contrasena)
        if self.recordar_cuenta:
            await self._marcar_recordar_cuenta(page)
        await page.click("button[type='submit'], input[type='submit']")
        await page.wait_for_load_state("networkidle")

        if await page.locator("input[name='username'], #username").count():
            raise RuntimeError("El login parece seguir mostrando el formulario. Revisa credenciales o flujo de acceso.")
        if self.recordar_cuenta:
            await page.context.storage_state(path=str(CARM_STORAGE_STATE))

    @staticmethod
    async def _marcar_recordar_cuenta(page) -> None:
        try:
            await page.evaluate(
                """() => {
                    const normalizar = (txt) => (txt || '').toLowerCase()
                      .normalize('NFD').replace(/[\\u0300-\\u036f]/g, '');
                    const checks = [...document.querySelectorAll('input[type="checkbox"]')];
                    for (const check of checks) {
                        const id = check.id || '';
                        const name = check.name || '';
                        const label = id ? document.querySelector(`label[for="${CSS.escape(id)}"]`) : null;
                        const wrap = check.closest('label');
                        const text = normalizar(`${id} ${name} ${label ? label.textContent : ''} ${wrap ? wrap.textContent : ''}`);
                        if (/(recordar|remember|mantener|sesion|session|cuenta|usuario)/.test(text)) {
                            check.checked = true;
                            check.dispatchEvent(new Event('change', {bubbles: true}));
                        }
                    }
                }"""
            )
        except Exception:
            pass

    async def _crear_contexto(self, browser):
        if self.recordar_cuenta and CARM_STORAGE_STATE.exists():
            try:
                return await browser.new_context(storage_state=str(CARM_STORAGE_STATE))
            except Exception as exc:
                logger.warning(f"No se pudo reutilizar sesión CARM guardada: {exc}")
        return await browser.new_context()

    @staticmethod
    def _configurar_page(page) -> None:
        page.set_default_timeout(CARM_NAV_TIMEOUT_MS)
        page.set_default_navigation_timeout(CARM_NAV_TIMEOUT_MS)

    async def _cerrar_contexto(self, context, page) -> None:
        if self.recordar_cuenta:
            try:
                await context.storage_state(path=str(CARM_STORAGE_STATE))
            except Exception:
                pass
            return
        try:
            await context.clear_cookies()
            await page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
        except Exception:
            pass

    @staticmethod
    async def _guardar_diagnostico_pagina(page, destino_dir: Path, nombre: str) -> None:
        destino_dir.mkdir(parents=True, exist_ok=True)
        html = ExtractorCarm._redactar_texto_sensible(await page.content())
        (destino_dir / f"{nombre}.html").write_text(html, encoding="utf-8")
        try:
            await page.screenshot(path=str(destino_dir / f"{nombre}.png"), full_page=True)
        except Exception as e:
            logger.warning(f"No se pudo guardar captura de diagnóstico {nombre}: {e}")

    @staticmethod
    def _extension_contexto_desde_url(url: str, headers: dict | None = None, nombre: str = "") -> str:
        headers = headers or {}
        candidates = [nombre, urlparse(url).path]
        disposition = str(headers.get("content-disposition") or headers.get("Content-Disposition") or "")
        filename_match = re.search(r"filename\*=(:UTF-8''|\")([^\";]+)", disposition, flags=re.I)
        if filename_match:
            candidates.insert(0, filename_match.group(1))
        for candidate in candidates:
            suffix = Path(urlparse(candidate).path).suffix.lower()
            if suffix:
                return suffix
        content_type = str(headers.get("content-type") or headers.get("Content-Type") or "").lower()
        if "pdf" in content_type:
            return ".pdf"
        if "presentation" in content_type or "powerpoint" in content_type:
            return ".pptx"
        if "spreadsheet" in content_type or "excel" in content_type:
            return ".xlsx"
        if "wordprocessingml" in content_type or "msword" in content_type:
            return ".docx"
        if "html" in content_type:
            return ".html"
        if "text" in content_type or "json" in content_type or "xml" in content_type:
            return ".txt"
        return ""

    async def _extraer_texto_url_contexto(self, page, url: str, nombre: str = "") -> str:
        try:
            response = await page.request.get(url, timeout=CARM_NAV_TIMEOUT_MS)
            if not response.ok:
                return ""
            headers = response.headers
            data = await response.body()
        except Exception as exc:
            logger.warning("No se pudo descargar recurso de contenido imprimible %s: %s", url, exc)
            return ""

        ext = self._extension_contexto_desde_url(url, headers, nombre)
        content_type = str(headers.get("content-type") or "").lower()
        if ext in {".html", ".htm", ".txt", ".md", ".csv", ".json", ".xml"} or "text" in content_type or "html" in content_type:
            for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
                try:
                    return data.decode(enc, errors="replace")
                except Exception:
                    continue
            return ""

        if ext not in {".pdf", ".docx", ".odt", ".rtf", ".pptx", ".xlsx", ".zip"}:
            return ""

        with tempfile.TemporaryDirectory(prefix="carm_contexto_") as tmp:
            path = Path(tmp) / f"contenido{ext}"
            path.write_bytes(data)
            try:
                lector = GeneradorSalidas(Path(tmp), Path(tmp))
                lectura = lector.leer_entrega(path)
                if lectura.requiere_revision_manual:
                    logger.warning("Recurso didactico %s requiere revision manual: %s", url, lectura.motivo)
                return lectura.texto
            except Exception as exc:
                logger.warning("No se pudo extraer texto de recurso didactico %s: %s", url, exc)
                return ""

    async def _urls_archivos_embebidos_contexto(self, page) -> list[str]:
        urls: list[str] = []
        for selector, attr in (
            ("a[href]", "href"),
            ("iframe[src]", "src"),
            ("object[data]", "data"),
            ("embed[src]", "src"),
        ):
            try:
                elementos = await page.query_selector_all(selector)
            except Exception:
                continue
            for elemento in elementos:
                try:
                    raw = await elemento.get_attribute(attr)
                except Exception:
                    continue
                if not raw:
                    continue
                url = urljoin(page.url, raw)
                normalizada = url.lower()
                if (
                    "pluginfile.php" in normalizada
                    or "forcedownload=1" in normalizada
                    or re.search(r"\.(pdf|docx|odt|rtf|pptx|xlsx|txt|html)(:[#]|$)", normalizada)
                ):
                    if url not in urls:
                        urls.append(url)
        return urls

    async def _extraer_contexto_imprimible(self, page) -> str:
        if self.usar_cache and self.cache:
            contexto_cache = self.cache.obtener_contexto_unidades(self.unidades)
            if contexto_cache.strip():
                logger.info("Contexto imprimible cargado desde cache local.")
                return contexto_cache

        contexto_partes: list[str] = []
        enlaces = await page.query_selector_all("a")
        urls_contexto: list[tuple[str, str, str]] = []
        for a in enlaces:
            try:
                txt = (await a.text_content() or "").strip().lower()
                txt_normalizado = self._normalizar(txt)
                if "contenido imprimible" not in txt_normalizado:
                    continue
                m = re.search(r"\bud\s*0*(\d{1,2})\b", txt_normalizado)
                unidad_enlace = f"ud{int(m.group(1)):02d}" if m else ""
                unidades_actividades = {
                    self._unidad_desde_codigo_actividad(codigo)
                    for codigo in self.actividades
                }
                unidades_permitidas = self.unidades or unidades_actividades
                if unidades_permitidas and unidad_enlace not in unidades_permitidas:
                    continue
                href = await a.get_attribute("href")
                if href:
                    urls_contexto.append((href, unidad_enlace, txt))
            except Exception as e:
                logger.warning(f"No se pudo leer enlace de contenido imprimible: {e}")
                continue

        for href, unidad_codigo, nombre in urls_contexto:
            try:
                url_contexto = urljoin(CARM_COURSE_URL or page.url, href)
                await page.goto(url_contexto, wait_until="domcontentloaded")
                body = await page.text_content("body")
                textos_candidatos: list[str] = [body or ""]
                for archivo_url in await self._urls_archivos_embebidos_contexto(page):
                    texto_archivo = await self._extraer_texto_url_contexto(page, archivo_url, nombre)
                    if texto_archivo:
                        textos_candidatos.append(texto_archivo)
                if len(textos_candidatos) == 1:
                    texto_directo = await self._extraer_texto_url_contexto(page, url_contexto, nombre)
                    if texto_directo:
                        textos_candidatos.append(texto_directo)

                mejor_contexto = ""
                for candidato in textos_candidatos:
                    contexto_limpio = limpiar_bloque_carm_para_prompt(
                        candidato.strip(),
                        max_chars=MAX_CONTEXTO_CACHE_CHARS,
                    )
                    if es_contexto_didactico_util(contexto_limpio) and len(contexto_limpio) > len(mejor_contexto):
                        mejor_contexto = contexto_limpio

                if mejor_contexto:
                    contexto_partes.append(mejor_contexto)
                    if self.cache and unidad_codigo:
                        self.cache.guardar_unidad(unidad_codigo, nombre=nombre, contenido_imprimible=mejor_contexto)
                else:
                    logger.warning("No se encontro contenido didactico util en %s (%s).", nombre, url_contexto)
            except Exception as e:
                logger.warning(f"No se pudo leer contenido imprimible {href}: {e}")
        await page.goto(CARM_COURSE_URL or CARM_MY_URL, wait_until="domcontentloaded")
        return "\n\n".join(contexto_partes)

    async def _extraer_enunciado_actividad(self, page, actividad_url: str) -> str:
        try:
            await page.goto(self._url_vista_actividad(actividad_url), wait_until="domcontentloaded")
        except Exception as e:
            logger.warning(f"No se pudo extraer enunciado de {actividad_url}: {e}")
            return ""

        for selector in (
            ".activity-description",
            ".intro",
            "#intro",
            ".box.generalbox",
            "[role='main']",
        ):
            try:
                texto = await page.locator(selector).first.text_content(timeout=800)
            except Exception:
                continue
            texto = self._texto_limpio(texto or "")
            if texto:
                return texto[:12000]
        return ""

    async def _obtener_actividades_prioritarias(self, page) -> list[dict]:
        actividades: list[dict] = []
        vistos: set[str] = set()
        modulos = await page.query_selector_all("li.activity.assign, .activity.assign, li.modtype_assign")
        if not modulos:
            modulos = await page.query_selector_all("a[href*='mod/assign/view.php']")

        for modulo in modulos:
            enlace_actividad = await modulo.query_selector("a[href*='mod/assign/view.php']:not(.ad-activity-action)")
            if enlace_actividad is None:
                enlace_actividad = modulo

            nombre = (await enlace_actividad.text_content() or "").strip()
            if not nombre:
                continue
            base = self._normalizar(nombre)
            if "caso practico" not in base:
                continue
            es_obligatorio = "(obligatorio)" in base or " obligatorio" in base
            es_opcional = "(opcional)" in base or " opcional" in base
            if not es_obligatorio and not es_opcional:
                continue
            href = await enlace_actividad.get_attribute("href")
            if not href:
                continue
            vista_url = self._url_vista_actividad(href)
            if vista_url in vistos:
                continue
            vistos.add(vista_url)
            enlace_require_grading = await modulo.query_selector(
                "a[href*='action=grading'][href*='filter=require_grading']"
            )
            href_require_grading = (
                await enlace_require_grading.get_attribute("href")
                if enlace_require_grading is not None
                else ""
            )
            texto_require_grading = (
                (await enlace_require_grading.text_content() or "").strip()
                if enlace_require_grading is not None
                else ""
            )
            unidad = await self._obtener_nombre_unidad(enlace_actividad)
            codigo = self._inferir_codigo_actividad(nombre, unidad)
            if not self._actividad_permitida(codigo, self.unidades, self.actividades):
                continue
            resumen_accion = self._extraer_resumen_accion_actividad(texto_require_grading)
            sin_calificar = resumen_accion.get("sin_calificar")
            if sin_calificar is None and resumen_accion.get("menciona_enviados") and not resumen_accion.get("menciona_sin_calificar"):
                sin_calificar = 0
                resumen_accion["sin_calificar"] = 0
            if sin_calificar == 0:
                logger.info(
                    "Se omite %s desde el contador de CARM: sin casos por calificar.",
                    codigo,
                )
                continue
            unidad_codigo = self._unidad_desde_codigo_actividad(codigo)
            actividades.append(
                {
                    "nombre": nombre,
                    "unidad": unidad,
                    "unidad_codigo": unidad_codigo,
                    "codigo": codigo,
                    "tipo": "obligatorio" if es_obligatorio else "opcional",
                    "url": vista_url,
                    "url_grading": self._url_grading_requiere_calificacion(
                        href_require_grading or self._agregar_action_grading(vista_url)
                    ),
                    "filtro": "require_grading",
                    "resumen_carm": resumen_accion,
                    "sin_calificar_carm": resumen_accion.get("sin_calificar"),
                }
            )
        return sorted(
            actividades,
            key=lambda act: (0 if act.get("tipo") == "obligatorio" else 1, act.get("codigo", "")),
        )

    async def _obtener_actividades_obligatorias(self, page) -> list[dict]:
        return await self._obtener_actividades_prioritarias(page)

    async def _listar_enlaces_assign(self, page) -> list[dict]:
        enlaces = await page.query_selector_all("a[href*='mod/assign/view.php']")
        resultado: list[dict] = []
        for a in enlaces:
            nombre = (await a.text_content() or "").strip()
            resultado.append(
                {
                    "texto": nombre,
                    "unidad": await self._obtener_nombre_unidad(a),
                    "href": await a.get_attribute("href"),
                    "normalizado": self._normalizar(nombre),
                }
            )
        return resultado

    async def _mapear_columnas_grading(self, page) -> dict[str, int]:
        headers = await page.query_selector_all("table.generaltable thead th")
        columnas: dict[str, int] = {}
        for idx, th in enumerate(headers):
            texto = self._normalizar(await th.text_content() or "")
            if "nombre" in texto and ("apellido" in texto or "completo" in texto):
                columnas["alumno"] = idx
            elif texto.startswith("estado"):
                columnas["estado"] = idx
            elif "archivos enviados" in texto or "archivo enviado" in texto:
                columnas["archivos"] = idx
        return columnas

    @staticmethod
    async def _texto_celda(celdas: list, indice: int | None) -> str:
        if indice is None or indice >= len(celdas):
            return ""
        return ExtractorCarm._texto_limpio(await celdas[indice].text_content() or "")

    async def _nombre_alumno_desde_celda(self, celda) -> str:
        enlace_usuario = await celda.query_selector("a[href*='user/view.php']")
        if enlace_usuario is not None:
            texto = await enlace_usuario.text_content()
            if texto and texto.strip():
                return self._texto_limpio(texto)
        return self._texto_limpio(await celda.text_content() or "")

    async def _asegurar_filtros_grading(self, page, actividad: dict) -> None:
        url_normalizada = self._url_grading_requiere_calificacion(actividad["url_grading"])
        if page.url != url_normalizada:
            await page.goto(url_normalizada, wait_until="domcontentloaded")
        actividad["url_grading"] = url_normalizada

        try:
            selects = await page.query_selector_all("select")
            for select in selects:
                name = (await select.get_attribute("name") or "").lower()
                option_texts = [
                    self._normalizar(await option.text_content() or "")
                    for option in await select.query_selector_all("option")
                ]
                if "filter" in name or any("requiere calificacion" in text for text in option_texts):
                    try:
                        await select.select_option("require_grading")
                        await page.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception:
                        pass
                    break
        except Exception as exc:
            logger.warning(f"No se pudo verificar selector de filtro en {actividad.get('codigo')}: {exc}")

        url_actual = self._url_grading_requiere_calificacion(page.url)
        if page.url != url_actual:
            await page.goto(url_actual, wait_until="domcontentloaded")

        parsed = dict(parse_qsl(urlparse(page.url).query))
        filtro = parsed.get("filter", "")
        filtros_letra = {
            clave: valor
            for clave, valor in parsed.items()
            if clave.lower()
            in {
                "tifirst",
                "tilast",
                "tfirst",
                "tlast",
                "ifirst",
                "ilast",
                "sifirst",
                "silast",
                "firstname",
                "lastname",
                "firstinitial",
                "lastinitial",
                "initial",
            }
        }
        if filtro != "require_grading" or filtros_letra:
            raise RuntimeError(
                f"Filtros de grading no seguros en {actividad.get('codigo')}: "
                f"filter={filtro or 'vacio'}, iniciales={filtros_letra or 'todos'}"
            )

    async def _descargar_envios_actividad(self, page, actividad: dict, descargar: bool = True) -> list[EnvioPendiente]:
        descargados: list[EnvioPendiente] = []
        actividad["url_grading"] = self._url_grading_requiere_calificacion(actividad["url_grading"])
        await page.goto(actividad["url_grading"], wait_until="domcontentloaded")
        await self._asegurar_filtros_grading(page, actividad)

        columnas = await self._mapear_columnas_grading(page)
        if "alumno" not in columnas:
            logger.warning(f"No se detectó la columna de alumno en {actividad.get('codigo')}")

        filas = await page.query_selector_all("table.generaltable tbody tr")
        if not filas:
            logger.info("Sin entregas pendientes en %s.", actividad.get("codigo", ""))
            return descargados
        for fila in filas:
            clase = await fila.get_attribute("class") or ""
            if "emptyrow" in clase:
                continue

            celdas = await fila.query_selector_all("td")
            if len(celdas) < 2:
                continue

            indice_alumno = columnas.get("alumno", 0)
            if indice_alumno >= len(celdas):
                continue
            alumno = await self._nombre_alumno_desde_celda(celdas[indice_alumno])
            if not alumno:
                continue

            estado = await self._texto_celda(celdas, columnas.get("estado"))
            celda_archivos = celdas[columnas["archivos"]] if "archivos" in columnas and columnas["archivos"] < len(celdas) else fila
            enlaces_archivo = await celda_archivos.query_selector_all(
                "a[href*='pluginfile.php'], a[href*='forcedownload=1'], a[download]"
            )

            registro_base = {
                "alumno": self._sanitizar_nombre(alumno),
                "alumno_original": alumno,
                "actividad_codigo": actividad.get("codigo", DEFAULT_ACTIVIDAD_CODIGO),
                "actividad_nombre": actividad.get("nombre", ""),
                "estado_entrega": estado,
                "tiene_archivo": bool(enlaces_archivo),
                "archivos": [],
            }

            if not enlaces_archivo:
                if self._es_estado_sin_entrega(estado):
                    registro_base["resultado"] = "sin_entrega"
                    logger.info(f"Sin entrega en {actividad.get('codigo')}: {alumno}")
                else:
                    registro_base["resultado"] = "sin_archivo_detectado"
                    logger.warning(
                        f"Entrega sin archivo descargable en {actividad.get('codigo')}: {alumno} ({estado or 'sin estado'})"
                    )
                self.registros_envios.append(registro_base)
                continue

            alumno_limpio = self._sanitizar_nombre(alumno)
            actividad_codigo = actividad.get("codigo", DEFAULT_ACTIVIDAD_CODIGO)
            destino_dir = self.pendientes_dir / actividad_codigo
            if descargar:
                destino_dir.mkdir(parents=True, exist_ok=True)

            for idx, enlace_archivo in enumerate(enlaces_archivo, start=1):
                file_url = await enlace_archivo.get_attribute("href")
                if not file_url:
                    continue

                nombre_archivo = self._texto_limpio(await enlace_archivo.text_content() or "entrega")
                ext = Path(nombre_archivo).suffix or ".txt"
                sufijo = "" if len(enlaces_archivo) == 1 else f"_{idx:02d}"
                destino = destino_dir / f"{alumno_limpio}{sufijo}{ext}"

                if not descargar:
                    registro_base["archivos"].append(
                        {
                            "nombre": nombre_archivo,
                            "descargado": False,
                            "motivo": "solo_listado",
                        }
                    )
                    continue

                try:
                    resp = await page.context.request.get(file_url)
                    if resp.status != 200:
                        logger.warning(f"No se pudo descargar envio de {alumno}: HTTP {resp.status}")
                        registro_base["archivos"].append(
                            {
                                "nombre": nombre_archivo,
                                "descargado": False,
                                "http_status": resp.status,
                            }
                        )
                        continue
                    body = await resp.body()
                    destino.write_bytes(body)
                    descargados.append(
                        EnvioPendiente(
                            alumno=alumno_limpio,
                            archivo=destino,
                            actividad_codigo=actividad_codigo,
                            actividad_nombre=actividad.get("nombre", ""),
                            actividad_enunciado=actividad.get("enunciado", ""),
                            estado_entrega=estado,
                            archivo_original_nombre=nombre_archivo,
                        )
                    )
                    registro_base["archivos"].append(
                        {
                            "nombre": nombre_archivo,
                            "descargado": True,
                            "destino": str(destino),
                        }
                    )
                    logger.info(f"Descargado envio de {alumno_limpio}: {destino}")
                except Exception as e:
                    registro_base["archivos"].append(
                        {
                            "nombre": nombre_archivo,
                            "descargado": False,
                            "error": str(e),
                        }
                    )
                    logger.warning(f"Error descargando envio de {alumno}: {e}")

            registro_base["resultado"] = (
                "descargado"
                if any(a.get("descargado") for a in registro_base["archivos"])
                else ("pendiente_descarga" if not descargar else "error_descarga")
            )
            self.registros_envios.append(registro_base)

        return descargados

    async def _buscar_url_calificador_en_tabla(self, page, alumno: str) -> tuple[str, bool]:
        filas = await page.query_selector_all("table.generaltable tbody tr")
        for fila in filas:
            texto_fila = await fila.text_content() or ""
            if not self._coincide_alumno(alumno, texto_fila):
                continue
            enlace = await fila.query_selector("a[href*='action=grader'][href*='userid=']")
            if enlace is None:
                enlace = await fila.query_selector("a[href*='action=grader']")
            if enlace is None:
                return "", True
            href = await enlace.get_attribute("href")
            if href:
                return href, True
            return "", True
        return "", False

    @staticmethod
    async def _contar_filas_grading(page) -> int:
        total = 0
        filas = await page.query_selector_all("table.generaltable tbody tr")
        for fila in filas:
            clase = await fila.get_attribute("class") or ""
            texto = (await fila.text_content() or "").strip()
            if not texto or "emptyrow" in clase:
                continue
            total += 1
        return total

    async def _actividad_tiene_filas_pendientes(self, page, actividad: dict) -> bool:
        actividad["url_grading"] = self._url_grading_requiere_calificacion(actividad["url_grading"])
        await page.goto(actividad["url_grading"], wait_until="domcontentloaded")
        await self._asegurar_filtros_grading(page, actividad)
        total = await self._contar_filas_grading(page)
        if total <= 0:
            logger.info("Sin filas en Requiere calificacion para %s; se omite.", actividad.get("codigo", ""))
            return False
        return True

    async def _buscar_url_calificador(self, page, actividad: dict, alumno: str) -> tuple[str, str]:
        actividad["url_grading"] = self._url_grading_requiere_calificacion(actividad["url_grading"])
        await page.goto(actividad["url_grading"], wait_until="domcontentloaded")
        await self._asegurar_filtros_grading(page, actividad)
        href, encontrado = await self._buscar_url_calificador_en_tabla(page, alumno)
        filas_requieren_calificacion = await self._contar_filas_grading(page)
        if href:
            return href, "pendiente"

        url_todos = self._url_grading_todos(actividad["url_grading"])
        logger.warning(
            "No se encontro %s en Requiere calificacion para %s; probando vista completa de la actividad.",
            alumno,
            actividad.get("codigo", ""),
        )
        await page.goto(url_todos, wait_until="domcontentloaded")
        href, encontrado_todos = await self._buscar_url_calificador_en_tabla(page, alumno)
        if href:
            return href, "fuera_de_requiere_calificacion"
        if encontrado or encontrado_todos or filas_requieren_calificacion == 0:
            return "", "ya_no_requiere_calificacion"
        return "", "no_encontrado"

    async def _rellenar_primero(self, page, selectores: list[str], valor: str) -> str:
        for selector in selectores:
            locator = page.locator(selector).first
            try:
                if await locator.count():
                    await locator.scroll_into_view_if_needed()
                    await locator.click()
                    await locator.press("Control+A")
                    await locator.fill("")
                    await locator.fill(str(valor))
                    await locator.dispatch_event("input")
                    await locator.dispatch_event("change")
                    return selector
            except Exception:
                continue
        return ""

    @staticmethod
    async def _hay_formulario_calificacion(page) -> bool:
        for selector in (
            "input[name='grade']",
            "#id_grade",
            "input[id*='grade'][type='text']",
            "input[name*='grade'][type='text']",
        ):
            try:
                if await page.locator(selector).first.count():
                    return True
            except Exception:
                continue
        return False

    async def _esperar_formulario_calificacion(self, page, timeout_ms: int = 7000) -> bool:
        limite = datetime.now().timestamp() + (timeout_ms / 1000)
        while datetime.now().timestamp() < limite:
            try:
                if await self._hay_formulario_calificacion(page):
                    return True
            except Exception:
                return False
            await page.wait_for_timeout(300)
        return False

    async def _pulsar_calificar_en_fila(self, page, alumno: str) -> str:
        filas = await page.query_selector_all("table.generaltable tbody tr, tr")
        for fila in filas:
            texto_fila = await fila.text_content() or ""
            if not self._coincide_alumno(alumno, texto_fila):
                continue
            for selector in (
                "a[href*='action=grader'][href*='userid=']",
                "a[href*='action=grader']",
                "a:has-text('Calificar')",
                "button:has-text('Calificar')",
                "input[value*='Calificar']",
            ):
                try:
                    enlace = await fila.query_selector(selector)
                    if enlace is None:
                        continue
                    await enlace.scroll_into_view_if_needed()
                    await enlace.click()
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception:
                        pass
                    if await self._esperar_formulario_calificacion(page):
                        return f"fila:{selector}"
                except Exception:
                    continue
        return ""

    async def _abrir_formulario_calificacion(self, page, url_calificador: str, alumno: str) -> str:
        for intento in range(1, 3):
            await page.goto(url_calificador, wait_until="domcontentloaded")
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass
            if await self._esperar_formulario_calificacion(page):
                return "url_directa" if intento == 1 else f"url_directa_reintento_{intento}"

        origen = await self._pulsar_calificar_en_fila(page, alumno)
        if origen:
            return origen

        for selector in (
            "a[href*='action=grader'][href*='userid=']",
            "a[href*='action=grader']",
            "a:has-text('Calificar')",
            "button:has-text('Calificar')",
            "input[value*='Calificar']",
            "a:has-text('Editar calificación')",
            "button:has-text('Editar calificación')",
        ):
            locator = page.locator(selector).first
            try:
                if await locator.count():
                    await locator.scroll_into_view_if_needed()
                    await locator.click()
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception:
                        pass
                    if await self._esperar_formulario_calificacion(page):
                        return f"fallback:{selector}"
            except Exception:
                continue
        return ""

    async def _rellenar_feedback(self, page, feedback: str) -> str:
        await page.wait_for_timeout(500)

        selector_visible = await self._rellenar_feedback_visible(page, feedback)

        selector_js = await page.evaluate(
            """(value) => {
                const html = value
                    .split(/\\n+/)
                    .map(line => line.trim())
                    .filter(Boolean)
                    .map(line => `<p>${line
                        .replace(/&/g, '&amp;')
                        .replace(/</g, '&lt;')
                        .replace(/>/g, '&gt;')}</p>`)
                    .join('');

                const textareas = Array.from(document.querySelectorAll('textarea')).filter(el => {
                    const key = `${el.name || ''} ${el.id || ''}`.toLowerCase();
                    return (
                        key.includes('assignfeedbackcomments') ||
                        key.includes('feedbackcomments') ||
                        key.includes('comments_editor')
                    );
                });

                const visibles = Array.from(document.querySelectorAll('[contenteditable="true"], .editor_atto_content')).filter(el => {
                    const key = `${el.id || ''} ${el.className || ''} ${el.getAttribute('aria-label') || ''}`.toLowerCase();
                    const parent = `${el.closest('[id], [class]').id || ''} ${el.closest('[id], [class]').className || ''}`.toLowerCase();
                    return (
                        key.includes('assignfeedbackcomments') ||
                        key.includes('feedbackcomments') ||
                        key.includes('retroaliment') ||
                        parent.includes('assignfeedbackcomments') ||
                        parent.includes('feedbackcomments')
                    );
                });

                for (const textarea of textareas) {
                    const key = `${textarea.name || ''} ${textarea.id || ''}`.toLowerCase();
                    const payload = key.includes('_editor') ? (html || value.replace(/\\n/g, '<br>')) : value;
                    textarea.value = payload;
                    textarea.textContent = payload;
                    textarea.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: value}));
                    textarea.dispatchEvent(new Event('change', {bubbles: true}));

                    const explicitEditable = document.getElementById(`${textarea.id}editable`)
                        || document.getElementById(textarea.id.replace(/_editor$/, '_editable'))
                        || textarea.closest('.fitem, .form-group, .felement').querySelector('[contenteditable="true"], .editor_atto_content');
                    if (explicitEditable) {
                        explicitEditable.innerHTML = html || value.replace(/\\n/g, '<br>');
                        explicitEditable.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: value}));
                        explicitEditable.dispatchEvent(new Event('change', {bubbles: true}));
                    }
                }

                for (const editor of visibles) {
                    editor.innerHTML = html || value.replace(/\\n/g, '<br>');
                    editor.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: value}));
                    editor.dispatchEvent(new Event('change', {bubbles: true}));
                }

                if (window.YUI) {
                    try {
                        window.YUI().use('node-event-simulate', function(Y) {
                            for (const textarea of textareas) {
                                if (textarea.id) {
                                    const node = Y.one(`#${textarea.id}`);
                                    if (node) {
                                        node.simulate('change');
                                    }
                                }
                            }
                        });
                    } catch (e) {}
                }

                if (textareas.length) {
                    return textareas.map(el => el.name || el.id).join(', ');
                }
                if (visibles.length) {
                    return visibles.map(el => el.id || el.className || 'editor_visible').join(', ');
                }
                return '';
            }""",
            feedback,
        )
        if selector_js:
            return f"{selector_visible + ' | ' if selector_visible else ''}moodle_feedback:{selector_js}"
        if selector_visible:
            return selector_visible
        return ""

    @staticmethod
    async def _rellenar_feedback_visible(page, feedback: str) -> str:
        html = "".join(
            f"<p>{html_escape(line.strip())}</p>"
            for line in feedback.splitlines()
            if line.strip()
        ) or f"<p>{html_escape(feedback)}</p>"
        for selector in (
            "#id_assignfeedbackcomments_editoreditable",
            "#id_assignfeedbackcomments_editor_editable",
            "#id_assignfeedbackcommentseditable",
            "[id*='assignfeedbackcomments'][contenteditable='true']",
            ".editor_atto_content[contenteditable='true']",
        ):
            locator = page.locator(selector).first
            try:
                if await locator.count():
                    await locator.scroll_into_view_if_needed()
                    await locator.evaluate(
                        """(el, html) => {
                            el.innerHTML = html;
                            el.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText'}));
                            el.dispatchEvent(new Event('change', {bubbles: true}));
                        }""",
                        html,
                    )
                    await locator.dispatch_event("input")
                    await locator.dispatch_event("change")
                    return f"visible:{selector}"
            except Exception:
                continue

        for frame in page.frames:
            try:
                editable = frame.locator("body[contenteditable='true'], body, [contenteditable='true']").first
                if not await editable.count():
                    continue
                frame_name = (frame.name or frame.url or "").lower()
                body_text = (await editable.text_content(timeout=500) or "").strip()
                if (
                    "assignfeedbackcomments" not in frame_name
                    and "feedback" not in frame_name
                    and body_text
                ):
                    continue
                await frame.evaluate(
                    """(html) => {
                        const el = document.querySelector('body[contenteditable="true"], body, [contenteditable="true"]');
                        if (!el) return;
                        el.innerHTML = html;
                        el.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText'}));
                        el.dispatchEvent(new Event('change', {bubbles: true}));
                    }""",
                    html,
                )
                return f"frame:{frame.name or frame.url or 'editor'}"
            except Exception:
                continue

        return ""

    @staticmethod
    async def _diagnosticar_campos_feedback(page) -> list[dict]:
        try:
            elementos = await page.evaluate(
                """() => Array.from(document.querySelectorAll('textarea, [contenteditable="true"], .editor_atto_content'))
                    .map((el) => {
                        const text = (el.value || el.innerText || el.textContent || '').slice(0, 120);
                        return {
                            tag: el.tagName.toLowerCase(),
                            name: el.getAttribute('name') || '',
                            id: el.id || '',
                            class: typeof el.className === 'string' ? el.className : '',
                            aria: el.getAttribute('aria-label') || '',
                            visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
                            muestra: text
                        };
                    })
                    .filter((item) => {
                        const key = `${item.name} ${item.id} ${item.class} ${item.aria}`.toLowerCase();
                        return key.includes('feedback') || key.includes('comment') || key.includes('retroaliment') || item.muestra;
                    })"""
            )
            for frame in page.frames:
                if frame == page.main_frame:
                    continue
                try:
                    elementos.append(
                        {
                            "tag": "iframe",
                            "name": frame.name,
                            "id": "",
                            "class": "",
                            "aria": "",
                            "visible": True,
                            "muestra": (await frame.locator("body").first.text_content(timeout=500) or "")[:120],
                        }
                    )
                except Exception:
                    continue
            return elementos
        except Exception:
            return []

    async def _guardar_calificacion(self, page, mostrar_siguiente: bool = False) -> str:
        selectores_guardar = (
            "#id_savegrade",
            "button[name='savechanges']",
            "input[name='savechanges']",
            "button:has-text('Guardar cambios')",
            "input[value='Guardar cambios']",
            "button:has-text('Guardar')",
            "input[value='Guardar']",
        )

        selectores = selectores_guardar
        for selector in selectores:
            locator = page.locator(selector).first
            try:
                if await locator.count():
                    await locator.click()
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=8000)
                    except Exception:
                        pass
                    return selector
            except Exception:
                continue
        raise RuntimeError("No se encontró botón de guardado en el formulario de calificación.")

    @staticmethod
    async def _mostrar_guia_subida_asistida(
        page,
        indice: int,
        total: int,
        actividad_codigo: str,
        alumno: str,
        usar_siguiente: bool,
        guardado_detectado: bool = False,
        confirmacion_invalida: bool = False,
        permitir_confirmacion_manual: bool = False,
    ) -> None:
        boton = "Guardar cambios"
        mensaje = (
            f"Revision humana {indice}/{total} - {actividad_codigo.upper()} - "
            f"{pseudonimo(alumno)}. Revisa nota y feedback."
        )
        if confirmacion_invalida:
            detalle = (
                "No he podido detectar automaticamente el guardado. Si ya pulsaste 'Guardar cambios' en CARM "
                "y la pagina termino de responder, confirma manualmente para avanzar."
            )
        elif guardado_detectado:
            detalle = "CARM parece haber guardado. Puedes confirmar aqui para pasar al siguiente alumno."
        else:
            detalle = (
                f"Paso 1: pulsa '{boton}' dentro de CARM. Paso 2: cuando CARM haya guardado, "
                "pulsa el boton de confirmacion de este panel."
            )
        await page.evaluate(
            """({message, detail, invalid, allowManual}) => {
                const signature = `${message}\\n${detail}\\n${invalid ? 'invalid' : ''}\\n${allowManual ? 'manual' : ''}`;
                const previous = document.getElementById('corrector-carm-assisted-banner');
                if (previous && previous.dataset.signature === signature) return;
                if (previous) previous.remove();
                window.__correctorCarmDecision = window.__correctorCarmDecision || '';
                const banner = document.createElement('div');
                banner.id = 'corrector-carm-assisted-banner';
                banner.dataset.signature = signature;
                banner.style.position = 'fixed';
                banner.style.right = '16px';
                banner.style.top = '16px';
                banner.style.maxWidth = '420px';
                banner.style.zIndex = '2147483647';
                banner.style.padding = '12px 14px';
                banner.style.background = invalid ? '#fff1f1' : '#fff8ea';
                banner.style.border = invalid ? '1px solid #c94c4c' : '1px solid #d6a84f';
                banner.style.color = invalid ? '#5a1111' : '#3f2a00';
                banner.style.font = '14px Segoe UI, Arial, sans-serif';
                banner.style.boxShadow = '0 8px 28px rgba(0,0,0,.18)';
                banner.style.borderRadius = '8px';
                banner.style.pointerEvents = 'auto';
                const title = document.createElement('div');
                title.textContent = message;
                title.style.fontWeight = '700';
                title.style.marginBottom = '6px';
                const body = document.createElement('div');
                body.textContent = detail;
                body.style.lineHeight = '1.35';
                body.style.marginBottom = '10px';
                const warning = document.createElement('div');
                warning.textContent = 'Este panel no guarda en CARM. Solo avanza cuando ya has guardado en Moodle.';
                warning.style.fontWeight = '700';
                warning.style.marginBottom = '10px';
                const actions = document.createElement('div');
                actions.style.display = 'flex';
                actions.style.gap = '8px';
                actions.style.justifyContent = 'flex-end';
                const next = document.createElement('button');
                next.type = 'button';
                next.textContent = allowManual ? 'Confirmar guardado manual' : 'Ya he guardado en CARM';
                next.style.padding = '7px 12px';
                next.style.border = '1px solid #6f520f';
                next.style.borderRadius = '6px';
                next.style.background = '#6f520f';
                next.style.color = '#fff';
                next.style.cursor = 'pointer';
                next.onclick = () => { window.__correctorCarmDecision = allowManual ? 'confirmar_manual' : 'continuar'; };
                const skip = document.createElement('button');
                skip.type = 'button';
                skip.textContent = 'Omitir';
                skip.style.padding = '7px 12px';
                skip.style.border = '1px solid #b58b2a';
                skip.style.borderRadius = '6px';
                skip.style.background = '#fff';
                skip.style.color = '#3f2a00';
                skip.style.cursor = 'pointer';
                skip.onclick = () => { window.__correctorCarmDecision = 'omitir'; };
                actions.appendChild(skip);
                actions.appendChild(next);
                banner.appendChild(title);
                banner.appendChild(body);
                banner.appendChild(warning);
                banner.appendChild(actions);
                document.body.appendChild(banner);
            }""",
            {
                "message": mensaje,
                "detail": detalle,
                "invalid": confirmacion_invalida,
                "allowManual": permitir_confirmacion_manual,
            },
        )

    async def _submission_sin_calificar_presente(self, page) -> bool:
        selectores = (
            ".submissionnotgraded",
            "#region-main .submissionnotgraded",
            "div.submissionnotgraded",
        )
        for selector in selectores:
            try:
                locator = page.locator(selector).first
                if await locator.count():
                    texto = self._normalizar(await locator.text_content(timeout=500) or "")
                    if "sin calificar" in texto or "not graded" in texto:
                        return True
            except Exception:
                continue
        return False

    async def _submission_calificado_presente(self, page) -> bool:
        selectores = (
            ".submissiongraded",
            "#region-main .submissiongraded",
            "div.submissiongraded",
        )
        for selector in selectores:
            try:
                locator = page.locator(selector).first
                if await locator.count():
                    texto = self._normalizar(await locator.text_content(timeout=500) or "")
                    if "calificado" in texto or "graded" in texto:
                        return True
            except Exception:
                continue
        return False

    async def _guardado_carm_detectado(self, page, url_formulario: str, sin_calificar_inicial: bool = False) -> bool:
        try:
            if page.url != url_formulario and not await self._hay_formulario_calificacion(page):
                return True
            if await self._submission_calificado_presente(page):
                return True
            if sin_calificar_inicial and not await self._submission_sin_calificar_presente(page):
                return True
            texto = self._normalizar(await page.locator("body").first.text_content(timeout=1000) or "")
            return any(
                patron in texto
                for patron in (
                    "cambios guardados",
                    "se han guardado",
                    "guardado correctamente",
                    "calificacion guardada",
                    "grade saved",
                    "changes saved",
                )
            )
        except Exception:
            return False

    async def _guardado_confirmado_por_tabla_pendientes(
        self,
        page,
        url_formulario: str,
        alumno: str,
    ) -> bool:
        try:
            url_grading = self._url_grading_requiere_calificacion(url_formulario)
            await page.goto(url_grading, wait_until="domcontentloaded")
            await self._asegurar_filtros_grading(page, {"codigo": "", "url_grading": url_grading})
            href, encontrado = await self._buscar_url_calificador_en_tabla(page, alumno)
            filas = await self._contar_filas_grading(page)
            if href:
                return False
            if not encontrado:
                return True
            return filas == 0
        except Exception as exc:
            logger.warning("No se pudo verificar guardado en tabla de pendientes: %s", exc)
            return False

    async def _esperar_confirmacion_subida_asistida(
        self,
        page,
        indice: int,
        total: int,
        actividad_codigo: str,
        alumno: str,
        usar_siguiente: bool,
    ) -> str:
        url_formulario = page.url
        sin_calificar_inicial = await self._submission_sin_calificar_presente(page)
        logger.info(
            "Esperando confirmacion humana tras guardar en CARM: "
            f"{actividad_codigo} {pseudonimo(alumno)}"
        )
        while True:
            try:
                if page.is_closed():
                    return "cerrado_por_usuario"
                decision = await page.evaluate("window.__correctorCarmDecision || ''")
                if decision in {"continuar", "confirmar_manual", "omitir"}:
                    if decision == "confirmar_manual":
                        logger.info(
                            "Guardado confirmado manualmente sin deteccion automatica: %s %s",
                            actividad_codigo,
                            pseudonimo(alumno),
                        )
                        return decision
                    if decision == "continuar" and not await self._guardado_carm_detectado(page, url_formulario, sin_calificar_inicial):
                        await page.wait_for_timeout(1500)
                    if decision == "continuar" and not await self._guardado_carm_detectado(page, url_formulario, sin_calificar_inicial):
                        if await self._guardado_confirmado_por_tabla_pendientes(page, url_formulario, alumno):
                            logger.info(
                                "Guardado confirmado porque el alumno ya no aparece en Requiere calificacion: %s %s",
                                actividad_codigo,
                                pseudonimo(alumno),
                            )
                            return decision
                        await page.evaluate("window.__correctorCarmDecision = ''")
                        await self._mostrar_guia_subida_asistida(
                            page,
                            indice=indice,
                            total=total,
                            actividad_codigo=actividad_codigo,
                            alumno=alumno,
                            usar_siguiente=usar_siguiente,
                            confirmacion_invalida=True,
                            permitir_confirmacion_manual=True,
                        )
                        await page.wait_for_timeout(1200)
                        continue
                    return decision
                guardado_detectado = await self._guardado_carm_detectado(page, url_formulario, sin_calificar_inicial)
                await self._mostrar_guia_subida_asistida(
                    page,
                    indice=indice,
                    total=total,
                    actividad_codigo=actividad_codigo,
                    alumno=alumno,
                    usar_siguiente=usar_siguiente,
                    guardado_detectado=guardado_detectado,
                )
                await page.wait_for_timeout(1000)
            except Exception:
                try:
                    await page.wait_for_timeout(1000)
                except Exception:
                    return "cerrado_por_usuario"

    @staticmethod
    async def _esperar_revision_o_cierre(page, mensaje: str) -> None:
        logger.info(mensaje)
        logger.info("El navegador quedara abierto hasta que cierres la pestana o detengas la tarea desde la interfaz.")
        while True:
            try:
                if page.is_closed():
                    return
                await page.wait_for_timeout(1000)
            except Exception:
                return

    async def _subir_correccion_actividad(
        self,
        page,
        actividad: dict,
        correccion: dict,
        publicar: bool,
        mostrar_siguiente: bool = False,
        asistida: bool = False,
        indice: int = 1,
        total: int = 1,
    ) -> dict:
        alumno = str(correccion.get("alumno", "")).strip()
        actividad_codigo = str(correccion.get("actividad") or correccion.get("actividad_codigo") or "").strip().lower()
        nota = str(correccion.get("nota", "")).replace(",", ".")
        feedback = GeneradorSalidas._texto_feedback(correccion)

        url_calificador, estado_busqueda = await self._buscar_url_calificador(page, actividad, alumno)
        if not url_calificador:
            if estado_busqueda == "ya_no_requiere_calificacion":
                return {
                    "alumno": alumno,
                    "actividad": actividad_codigo,
                    "nota": nota,
                    "estado": "pendiente_no_abierto_sin_filas_requiere_calificacion",
                    "mensaje": "No se abrio el formulario porque el alumno no aparecio en la tabla Requiere calificacion. Queda pendiente de revision/subida manual.",
                }
            return {
                "alumno": alumno,
                "actividad": actividad_codigo,
                "estado": "no_encontrado",
                "mensaje": "No se encontró enlace de calificación para el alumno en la tabla.",
            }

        apertura_calificador = await self._abrir_formulario_calificacion(page, url_calificador, alumno)
        grade_selector = await self._rellenar_primero(
            page,
            [
                "input[name='grade']",
                "#id_grade",
                "input[id*='grade'][type='text']",
                "input[name*='grade'][type='text']",
            ],
            nota,
        )
        feedback_selector = await self._rellenar_feedback(page, feedback)

        resultado = {
            "alumno": alumno,
            "actividad": actividad_codigo,
            "nota": nota,
            "url_calificador": self._redactar_texto_sensible(url_calificador),
            "apertura_calificador": apertura_calificador,
            "campo_nota": grade_selector,
            "campo_feedback": feedback_selector,
            "diagnostico_feedback": await self._diagnosticar_campos_feedback(page),
            "guardar_y_mostrar_siguiente": bool(mostrar_siguiente),
            "estado_busqueda": estado_busqueda,
            "estado": "previsualizado",
        }

        if not grade_selector:
            resultado["estado"] = "error"
            resultado["mensaje"] = "No se encontró campo de nota."
            return resultado
        if not feedback_selector:
            resultado["estado"] = "error"
            resultado["mensaje"] = "No se encontró campo de retroalimentación."
            return resultado

        if publicar:
            boton = await self._guardar_calificacion(page, mostrar_siguiente=mostrar_siguiente)
            resultado["boton_guardado"] = boton
            resultado["estado"] = "publicado"
        elif asistida:
            await self._mostrar_guia_subida_asistida(
                page,
                indice=indice,
                total=total,
                actividad_codigo=actividad_codigo,
                alumno=alumno,
                usar_siguiente=mostrar_siguiente,
            )
            resultado["estado"] = "esperando_guardado_manual"
            resultado["boton_recomendado"] = "guardar_cambios"
            decision = await self._esperar_confirmacion_subida_asistida(
                page,
                indice=indice,
                total=total,
                actividad_codigo=actividad_codigo,
                alumno=alumno,
                usar_siguiente=mostrar_siguiente,
            )
            resultado["confirmacion_asistida"] = decision
            if decision in {"continuar", "confirmar_manual"}:
                resultado["estado"] = "guardado_manual_confirmado_por_usuario"
                if decision == "confirmar_manual":
                    resultado["confirmacion_manual_sin_deteccion"] = True
            elif decision == "omitir":
                resultado["estado"] = "omitido_por_usuario"
            else:
                resultado["estado"] = "interrumpido_por_usuario"

        return resultado

    async def subir_correcciones_carm(
        self,
        correcciones: list[dict],
        publicar: bool = False,
        asistida: bool = False,
        solo_primera_previsualizacion: bool = False,
    ) -> list[dict]:
        if async_playwright is None:
            raise RuntimeError(
                "Playwright no esta disponible. Ejecuta: pip install -r requirements.txt y luego playwright install chromium"
            )

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False if (asistida or solo_primera_previsualizacion or self.mantener_navegador) else CARM_HEADLESS
            )
            context = await self._crear_contexto(browser)
            trace_path: Path | None = None
            trace_started = False
            if self.guardar_trace_subida:
                trace_dir = RESPUESTAS_DIR / "traces"
                trace_dir.mkdir(parents=True, exist_ok=True)
                trace_path = trace_dir / f"trace_subida_carm_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
                try:
                    await context.tracing.start(screenshots=True, snapshots=True, sources=False)
                    trace_started = True
                    logger.warning(
                        "Trace de subida CARM activado. Puede contener datos personales. Se guardara en: %s",
                        trace_path,
                    )
                except Exception as exc:
                    logger.warning("No se pudo iniciar trace de subida CARM: %s", exc)
            page = await context.new_page()
            self._configurar_page(page)
            resultados: list[dict] = []
            try:
                await self._login(page)
                destino = CARM_COURSE_URL or CARM_MY_URL
                await page.goto(destino, wait_until="domcontentloaded")
                actividades = await self._obtener_actividades_obligatorias(page)
                actividades_por_codigo = {act["codigo"]: act for act in actividades}
                if self.cache:
                    for codigo, act in list(actividades_por_codigo.items()):
                        actividades_por_codigo[codigo] = self.cache.enriquecer_actividad(act)

                correcciones_a_procesar = correcciones

                total = len(correcciones_a_procesar)
                for indice, correccion in enumerate(correcciones_a_procesar):
                    actividad_codigo = str(
                        correccion.get("actividad") or correccion.get("actividad_codigo") or ""
                    ).strip().lower()
                    siguiente_codigo = ""
                    if indice + 1 < total:
                        siguiente_codigo = str(
                            correcciones_a_procesar[indice + 1].get("actividad")
                            or correcciones_a_procesar[indice + 1].get("actividad_codigo")
                            or ""
                        ).strip().lower()
                    mostrar_siguiente = publicar and bool(siguiente_codigo) and siguiente_codigo == actividad_codigo
                    actividad = actividades_por_codigo.get(actividad_codigo)
                    if not actividad:
                        resultados.append(
                            {
                                "alumno": correccion.get("alumno", ""),
                                "actividad": actividad_codigo,
                                "estado": "no_encontrado",
                                "mensaje": "No se encontró la actividad en CARM.",
                            }
                        )
                        continue

                    resultado = (
                        await self._subir_correccion_actividad(
                            page,
                            actividad,
                            correccion,
                            publicar=publicar,
                            mostrar_siguiente=mostrar_siguiente,
                            asistida=asistida,
                            indice=indice + 1,
                            total=total,
                        )
                    )
                    resultados.append(resultado)
                    if solo_primera_previsualizacion and not publicar and not asistida and resultado.get("estado") == "previsualizado":
                        break

                if trace_path:
                    for resultado in resultados:
                        resultado["trace_path"] = str(trace_path)
                return resultados
            finally:
                if trace_started and trace_path:
                    try:
                        await context.tracing.stop(path=str(trace_path))
                        registrar_auditoria("trace_subida_carm", salida=trace_path)
                        logger.warning("Trace de subida CARM generado en: %s", trace_path)
                    except Exception as exc:
                        logger.warning("No se pudo guardar trace de subida CARM: %s", exc)
                if self.mantener_navegador and not asistida:
                    await self._esperar_revision_o_cierre(page, "Navegador abierto para revision.")
                await self._cerrar_contexto(context, page)
                await context.close()
                await browser.close()

    async def ejecutar(self, solo_listar: bool = False) -> tuple[str, list[EnvioPendiente]]:
        if async_playwright is None:
            raise RuntimeError(
                "Playwright no esta disponible. Ejecuta: pip install -r requirements.txt y luego playwright install chromium"
            )

        self.pendientes_dir.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=CARM_HEADLESS)
            context = await self._crear_contexto(browser)
            page = await context.new_page()
            self._configurar_page(page)
            try:
                await self._login(page)

                await page.goto(CARM_MY_URL, wait_until="domcontentloaded")
                await page.goto(CARM_COURSE_URL, wait_until="domcontentloaded")
                if self.cache:
                    self.cache.guardar_curso(await page.title())

                actividades = await self._obtener_actividades_obligatorias(page)
                logger.info(f"Actividades prioritarias encontradas: {len(actividades)}")
                if not actividades:
                    logger.info("No hay casos practicos coincidentes para promptear en el filtro seleccionado.")
                    return "", []

                todos_envios: list[EnvioPendiente] = []
                for act in actividades:
                    logger.info(f"Procesando grading {act['codigo']}: {act['nombre']}")
                    if self.usar_cache and self.cache:
                        act = self.cache.enriquecer_actividad(act)
                    if not await self._actividad_tiene_filas_pendientes(page, act):
                        continue
                    if not act.get("enunciado"):
                        act["enunciado"] = await self._extraer_enunciado_actividad(page, act["url"])
                    if self.cache:
                        self.cache.guardar_actividad(act)
                    envios = await self._descargar_envios_actividad(page, act, descargar=not solo_listar)
                    todos_envios.extend(envios)

                if todos_envios:
                    await page.goto(CARM_COURSE_URL, wait_until="domcontentloaded")
                    contexto = await self._extraer_contexto_imprimible(page)
                else:
                    contexto = ""

                (RESPUESTAS_DIR / "envios_descargados.json").write_text(
                    json.dumps(
                        [
                            {
                                "alumno": e.alumno,
                                "archivo": str(e.archivo),
                                "actividad_codigo": e.actividad_codigo,
                                "actividad_nombre": e.actividad_nombre,
                                "estado_entrega": e.estado_entrega,
                                "archivo_original_nombre": e.archivo_original_nombre,
                            }
                            for e in todos_envios
                        ],
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                (RESPUESTAS_DIR / "envios_carm_registros.json").write_text(
                    json.dumps(self.registros_envios, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )

                return contexto, todos_envios
            finally:
                if self.mantener_navegador:
                    await self._esperar_revision_o_cierre(page, "Navegador abierto para revision.")
                await self._cerrar_contexto(context, page)
                await context.close()
                await browser.close()

    async def cachear_curso(self) -> tuple[str, list[dict]]:
        if async_playwright is None:
            raise RuntimeError(
                "Playwright no esta disponible. Ejecuta: pip install -r requirements.txt y luego playwright install chromium"
            )

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=CARM_HEADLESS)
            context = await self._crear_contexto(browser)
            page = await context.new_page()
            self._configurar_page(page)
            try:
                await self._login(page)
                await page.goto(CARM_MY_URL, wait_until="domcontentloaded")
                await page.goto(CARM_COURSE_URL, wait_until="domcontentloaded")
                if self.cache:
                    self.cache.guardar_curso(await page.title())

                actividades = await self._obtener_actividades_obligatorias(page)
                contexto = await self._extraer_contexto_imprimible(page)
                logger.info(f"Actividades prioritarias encontradas: {len(actividades)}")

                for act in actividades:
                    logger.info(f"Cacheando actividad {act['codigo']}: {act['nombre']}")
                    if not act.get("enunciado"):
                        act["enunciado"] = await self._extraer_enunciado_actividad(page, act["url"])
                    if self.cache:
                        self.cache.guardar_actividad(act)

                return contexto, actividades
            finally:
                if self.mantener_navegador:
                    await self._esperar_revision_o_cierre(page, "Navegador abierto para revision.")
                await self._cerrar_contexto(context, page)
                await context.close()
                await browser.close()

    async def comprobar_login(self) -> None:
        if async_playwright is None:
            raise RuntimeError(
                "Playwright no esta disponible. Ejecuta: pip install -r requirements.txt y luego playwright install chromium"
            )

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await self._crear_contexto(browser)
            page = await context.new_page()
            self._configurar_page(page)
            try:
                await self._login(page)
                destino = CARM_COURSE_URL or CARM_MY_URL
                await page.goto(destino, wait_until="domcontentloaded")
                if await page.locator("input[name='username'], #username").count():
                    raise RuntimeError("CARM volvió a mostrar el formulario de login.")
                logger.info("Credenciales CARM verificadas correctamente.")
            finally:
                await self._cerrar_contexto(context, page)
                await context.close()
                await browser.close()

    async def listar_cursos_disponibles(self) -> list[dict]:
        if async_playwright is None:
            raise RuntimeError(
                "Playwright no esta disponible. Ejecuta: pip install -r requirements.txt y luego playwright install chromium"
            )

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=CARM_HEADLESS)
            context = await self._crear_contexto(browser)
            page = await context.new_page()
            self._configurar_page(page)
            try:
                await self._login(page)
                await page.goto(CARM_MY_URL, wait_until="domcontentloaded")
                enlaces = await page.query_selector_all("a[href*='course/view.php']")
                cursos: dict[str, dict] = {}
                for enlace in enlaces:
                    href = await enlace.get_attribute("href")
                    if not href:
                        continue
                    url = urljoin(CARM_MY_URL, href)
                    course_id = CacheCursoCarm._extraer_course_id(url)
                    if not course_id:
                        continue
                    titulo = self._texto_limpio(await enlace.text_content() or "")
                    if not titulo:
                        try:
                            titulo = self._texto_limpio(
                                await enlace.evaluate(
                                    """(el) => {
                                        const card = el.closest('.coursebox, .card, li, article, .dashboard-card');
                                        return card ? card.textContent : el.textContent;
                                    }"""
                                )
                            )
                        except Exception:
                            titulo = ""
                    titulo_normalizado = self._normalizar(titulo)
                    if titulo_normalizado in {"faq", "faqs", "curso carm", "carm curso carm", "carm - curso carm"}:
                        continue
                    if "faq" in titulo_normalizado:
                        continue
                    cursos[course_id] = {
                        "id": course_id,
                        "url": self._url_vista_actividad(url),
                        "titulo": titulo[:180] or f"Curso {course_id}",
                    }
                resultado = sorted(cursos.values(), key=lambda item: item["titulo"].lower())
                RESPUESTAS_DIR.mkdir(parents=True, exist_ok=True)
                salida = RESPUESTAS_DIR / "cursos_detectados.json"
                salida.write_text(json.dumps(resultado, indent=2, ensure_ascii=False), encoding="utf-8")
                logger.info("Cursos CARM detectados: %s", len(resultado))
                logger.info("Listado de cursos guardado en: %s", salida)
                return resultado
            finally:
                await self._cerrar_contexto(context, page)
                await context.close()
                await browser.close()

    async def diagnosticar(self, incluir_enlaces: bool = False) -> Path:
        if async_playwright is None:
            raise RuntimeError(
                "Playwright no esta disponible. Ejecuta: pip install -r requirements.txt y luego playwright install chromium"
            )

        diagnostico_dir = LOG_DIR / "diagnostico_carm"
        diagnostico_dir.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=CARM_HEADLESS)
            context = await self._crear_contexto(browser)
            page = await context.new_page()
            self._configurar_page(page)
            try:
                await self._login(page)
                if self.guardar_evidencias:
                    await self._guardar_diagnostico_pagina(page, diagnostico_dir, "01_post_login")

                await page.goto(CARM_MY_URL, wait_until="domcontentloaded")
                if self.guardar_evidencias:
                    await self._guardar_diagnostico_pagina(page, diagnostico_dir, "02_my")

                await page.goto(CARM_COURSE_URL, wait_until="domcontentloaded")
                if self.cache:
                    self.cache.guardar_curso(await page.title())
                if self.guardar_evidencias:
                    await self._guardar_diagnostico_pagina(page, diagnostico_dir, "03_course")

                enlaces_assign = await self._listar_enlaces_assign(page)
                actividades = await self._obtener_actividades_obligatorias(page)
                diagnostico = {
                    "login_url": CARM_LOGIN_URL,
                    "my_url": CARM_MY_URL,
                    "course_url": CARM_COURSE_URL,
                    "current_url": page.url,
                    "title": await page.title(),
                    "assign_links_count": len(enlaces_assign),
                    "assign_links": enlaces_assign,
                    "actividades_obligatorias_count": len(actividades),
                    "actividades_obligatorias": actividades,
                }

                for actividad in actividades[:3]:
                    try:
                        actividad["enunciado"] = await self._extraer_enunciado_actividad(page, actividad["url"])
                        if self.cache:
                            self.cache.guardar_actividad(actividad)
                        actividad["url_grading"] = self._url_grading_requiere_calificacion(actividad["url_grading"])
                        await page.goto(actividad["url_grading"], wait_until="domcontentloaded")
                        await self._asegurar_filtros_grading(page, actividad)
                        if self.guardar_evidencias:
                            await self._guardar_diagnostico_pagina(
                                page,
                                diagnostico_dir,
                                f"04_grading_{actividad['codigo']}",
                            )
                        filas = await page.query_selector_all("table.generaltable tbody tr")
                        actividad["filas_grading_detectadas"] = len(filas)
                        actividad["columnas_grading"] = await self._mapear_columnas_grading(page)
                    except Exception as e:
                        actividad["error_grading"] = str(e)

                diagnostico_path = diagnostico_dir / "diagnostico.json"
                diagnostico_limpio = self._limpiar_diagnostico_json(
                    diagnostico,
                    incluir_enlaces=incluir_enlaces,
                )
                diagnostico_path.write_text(
                    json.dumps(diagnostico_limpio, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                return diagnostico_path
            finally:
                if self.mantener_navegador:
                    await self._esperar_revision_o_cierre(page, "Navegador abierto para revision.")
                await self._cerrar_contexto(context, page)
                await context.close()
                await browser.close()


class GeneradorSalidas:
    MAX_ARCHIVO_BYTES = 50 * 1024 * 1024
    MAX_ZIP_ENTRADAS = 40
    MAX_ZIP_TOTAL_BYTES = 50 * 1024 * 1024
    MAX_ZIP_ENTRADA_BYTES = 8 * 1024 * 1024
    MAX_CONTEXTO_PROMPT_CHARS = MAX_CONTEXTO_PROMPT_CHARS
    EXTENSIONES_TEXTO = {
        ".txt",
        ".md",
        ".csv",
        ".tsv",
        ".json",
        ".xml",
        ".html",
        ".htm",
        ".log",
    }
    EXTENSIONES_OFFICE_TEXTO = {".docx", ".odt", ".rtf"}
    EXTENSIONES_REVISION_MANUAL = {
        ".doc",
        ".ppt",
        ".pages",
        ".numbers",
        ".key",
    }
    EXTENSIONES_MULTIMEDIA = {
        ".gif",
        ".webp",
        ".bmp",
        ".tif",
        ".tiff",
        ".svg",
        ".mp3",
        ".wav",
        ".m4a",
        ".ogg",
        ".mp4",
        ".mov",
        ".avi",
        ".mkv",
        ".webm",
        ".rar",
        ".7z",
    }
    EXTENSIONES_OCR = {".jpg", ".jpeg", ".png"}

    def __init__(self, pendientes_dir: Path, temporal_dir: Path, actividad_codigo: str = DEFAULT_ACTIVIDAD_CODIGO):
        self.pendientes_dir = pendientes_dir
        self.temporal_dir = temporal_dir
        self.actividad_codigo = actividad_codigo

    @staticmethod
    def _leer_archivo_texto(path: Path) -> str:
        if not path.exists() or not path.is_file():
            return ""

        for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
            try:
                return path.read_text(encoding=enc)
            except Exception:
                continue

        return ""

    @staticmethod
    def _limpiar_texto_extraido(texto: str) -> str:
        lineas: list[str] = []
        vistos: set[str] = set()
        patrones_ruido = (
            "gemini puede cometer errores",
            "google apps",
            "privacy policy",
            "terms of service",
            "activar modo oscuro",
            "new chat",
            "saved from url",
            "appsgm",
            "mat-icon",
            "aria-label",
        )
        for linea in str(texto or "").splitlines():
            limpia = re.sub(r"\s+", " ", linea).strip()
            if len(limpia) < 3:
                continue
            baja = limpia.lower()
            if any(p in baja for p in patrones_ruido):
                continue
            if len(limpia) > 4000:
                continue
            clave = baja[:240]
            if clave in vistos:
                continue
            vistos.add(clave)
            lineas.append(limpia)
        return "\n".join(lineas).strip()

    @staticmethod
    def _leer_html(path: Path) -> str:
        raw = GeneradorSalidas._leer_archivo_texto(path)
        if not raw:
            return ""
        raw = re.sub(r"<!--.*-->", " ", raw, flags=re.S)
        raw = re.sub(r"<(script|style|noscript|svg|canvas|template|head)\b[^>]*>.*</\1>", " ", raw, flags=re.I | re.S)
        parser = TextoVisibleHTMLParser()
        try:
            parser.feed(raw)
            texto = parser.texto()
        except Exception:
            texto = re.sub(r"<[^>]+>", " ", raw)
            texto = unescape(texto)
        texto = GeneradorSalidas._limpiar_texto_extraido(texto)
        texto = GeneradorSalidas._recortar_html_conversacion_ia(texto)
        if len(texto) > 120000:
            texto = texto[:120000].rstrip() + "\n\n[HTML recortado tras extraer texto visible.]"
        return texto

    @staticmethod
    def _html_limpieza_insuficiente(texto: str, raw_size: int) -> bool:
        limpio = str(texto or "").strip()
        if not limpio:
            return True
        if raw_size > 500_000 and len(limpio) > 120_000:
            return True
        if raw_size > 500_000 and len(limpio) < 300:
            return True
        ruido = sum(
            limpio.lower().count(patron)
            for patron in (
                "function(",
                "webpack",
                "appsgm",
                "aria-label",
                "mat-icon",
                ".css",
                "{color:",
                "data:image",
            )
        )
        if ruido >= 8:
            return True
        palabras = re.findall(r"\w+", limpio, flags=re.UNICODE)
        return raw_size > 500_000 and len(palabras) < 80

    @staticmethod
    def _texto_extraido_insuficiente(texto: str) -> bool:
        limpio = GeneradorSalidas._limpiar_texto_extraido(texto)
        if not limpio:
            return True
        palabras = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]{3,}", limpio)
        letras = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", limpio)
        marcadores = re.sub(r"[\s\wÁÉÍÓÚÜÑáéíóúüñ]", "", limpio)
        solo_listas = bool(marcadores) and not letras
        if solo_listas:
            return True
        if len(palabras) < 12:
            return True
        if len(letras) < 80:
            return True
        return False

    @staticmethod
    def _recortar_html_conversacion_ia(texto: str) -> str:
        marcas = (
            "Tu ai spus",
            "Tú dijiste",
            "You said",
            "Conversația cu Gemini",
            "Conversación con Gemini",
            "Chat with Gemini",
        )
        inicio = -1
        for marca in marcas:
            idx = texto.find(marca)
            if idx >= 0:
                inicio = idx if inicio < 0 else min(inicio, idx)
        actividad = re.search(r"\bUD\s*0\d+\s*-\s*CASO\s+PR[ÁA]CTICO\s+\d+", texto, flags=re.I)
        if actividad:
            inicio = actividad.start() if inicio < 0 else min(inicio, actividad.start())
        if inicio > 0:
            texto = texto[inicio:]
        lineas = []
        for linea in texto.splitlines():
            limpia = linea.strip()
            if limpia.lower() in {"gemini", "chat nou", "new chat", "articolele mele", "gems", "chaturi"}:
                continue
            lineas.append(limpia)
        return "\n".join(lineas).strip()

    def leer_entrega(self, path: Path) -> LecturaEntrega:
        if not path.exists() or not path.is_file():
            return LecturaEntrega("", True, "El archivo no existe o no es un archivo válido.")

        ext = path.suffix.lower()
        validacion = self._validar_archivo_entrega(path, ext)
        if validacion:
            return LecturaEntrega("", True, validacion)

        if ext in self.EXTENSIONES_MULTIMEDIA:
            return LecturaEntrega(
                "",
                True,
                f"Archivo multimedia o comprimido ({ext}); requiere revisión manual.",
            )

        if ext in self.EXTENSIONES_REVISION_MANUAL:
            return LecturaEntrega(
                "",
                True,
                f"Formato no textual no extraído automáticamente ({ext}); requiere revisión manual.",
            )

        try:
            advertencia = ""
            if ext in {".html", ".htm"}:
                texto = self._leer_html(path)
                raw_size = path.stat().st_size
                if self._html_limpieza_insuficiente(texto, raw_size):
                    return LecturaEntrega(
                        "",
                        True,
                        "HTML exportado demasiado grande o con mucho ruido tras limpieza; requiere revision manual.",
                    )
                if raw_size > 500_000:
                    advertencia = f"HTML limpiado automaticamente desde {raw_size} bytes."
            elif ext in self.EXTENSIONES_TEXTO or not ext:
                texto = self._leer_archivo_texto(path)
            elif ext == ".docx":
                texto = self._leer_docx(path)
            elif ext == ".odt":
                texto = self._leer_odt(path)
            elif ext == ".rtf":
                texto = self._leer_rtf(path)
            elif ext == ".pdf":
                texto = self._leer_pdf(path)
            elif ext == ".pptx":
                texto = self._leer_pptx(path)
            elif ext == ".xlsx":
                texto = self._leer_xlsx(path)
            elif ext == ".zip":
                texto = self._leer_zip(path)
            elif ext in self.EXTENSIONES_OCR:
                texto = self._leer_imagen_ocr(path)
            else:
                texto = self._leer_archivo_texto(path)
                if not texto.strip():
                    return LecturaEntrega(
                        "",
                        True,
                        f"Formato no reconocido ({ext or 'sin extensión'}); requiere revisión manual.",
                    )
        except Exception as e:
            return LecturaEntrega(
                "",
                True,
                f"No se pudo extraer texto de {path.name}: {e}",
            )

        if not texto.strip():
            return LecturaEntrega("", True, "El archivo esta vacio o no contiene texto legible; requiere revision manual.")

        texto_limpio = self._limpiar_texto_extraido(texto)
        if self._texto_extraido_insuficiente(texto_limpio):
            return LecturaEntrega(
                "",
                True,
                "Texto extraido insuficiente o formado solo por marcas/listas; requiere revision manual del archivo original.",
            )

        return LecturaEntrega(texto_limpio, advertencia=advertencia)

    def _validar_archivo_entrega(self, path: Path, ext: str) -> str:
        try:
            size = path.stat().st_size
        except OSError:
            return "No se pudo leer el tamaño del archivo; requiere revisión manual."
        if size > self.MAX_ARCHIVO_BYTES:
            return (
                f"Archivo demasiado grande ({size} bytes, limite {self.MAX_ARCHIVO_BYTES}); "
                "requiere revisión manual."
            )
        permitidas = (
            self.EXTENSIONES_TEXTO
            | self.EXTENSIONES_OFFICE_TEXTO
            | self.EXTENSIONES_REVISION_MANUAL
            | self.EXTENSIONES_MULTIMEDIA
            | self.EXTENSIONES_OCR
            | {".pdf", ".pptx", ".xlsx", ".zip", ""}
        )
        if ext not in permitidas:
            return f"Extension no permitida ({ext or 'sin extensión'}); requiere revisión manual."
        return ""

    @staticmethod
    def _leer_docx(path: Path) -> str:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml")
        root = ElementTree.fromstring(xml)
        textos = [
            node.text
            for node in root.iter()
            if node.tag.endswith("}t") and node.text
        ]
        return "\n".join(textos)

    @staticmethod
    def _leer_odt(path: Path) -> str:
        with zipfile.ZipFile(path) as z:
            xml = z.read("content.xml")
        root = ElementTree.fromstring(xml)
        textos = [node.text for node in root.iter() if node.text and node.text.strip()]
        return "\n".join(textos)

    @staticmethod
    def _leer_rtf(path: Path) -> str:
        raw = GeneradorSalidas._leer_archivo_texto(path)
        texto = re.sub(r"\\'[0-9a-fA-F]{2}", " ", raw)
        texto = re.sub(r"\\[a-zA-Z]+\d* ", " ", texto)
        texto = texto.replace("{", " ").replace("}", " ").replace("\\", " ")
        return unescape(re.sub(r"\s+", " ", texto)).strip()

    @staticmethod
    def _leer_pdf(path: Path) -> str:
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise RuntimeError("Instala pypdf para extraer texto de PDF") from e

        reader = PdfReader(str(path))
        textos = []
        for page in reader.pages:
            textos.append(page.extract_text() or "")
        return "\n".join(textos)

    @staticmethod
    def _leer_pptx(path: Path) -> str:
        try:
            from pptx import Presentation
        except ImportError as e:
            raise RuntimeError("Instala python-pptx para extraer texto de PPTX") from e

        prs = Presentation(str(path))
        textos = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text:
                    textos.append(shape.text)
        return "\n".join(textos)

    @staticmethod
    def _leer_xlsx(path: Path) -> str:
        try:
            from openpyxl import load_workbook
        except ImportError as e:
            raise RuntimeError("Instala openpyxl para extraer texto de XLSX") from e

        wb = load_workbook(str(path), read_only=True, data_only=True)
        textos = []
        for ws in wb.worksheets:
            textos.append(f"Hoja: {ws.title}")
            for row in ws.iter_rows(values_only=True):
                valores = [str(v) for v in row if v is not None and str(v).strip()]
                if valores:
                    textos.append(" | ".join(valores))
        return "\n".join(textos)

    def _leer_zip(self, path: Path) -> str:
        textos = []
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if len(infos) > self.MAX_ZIP_ENTRADAS:
                raise RuntimeError(f"ZIP con demasiados archivos ({len(infos)}).")
            total = sum(info.file_size for info in infos)
            if total > self.MAX_ZIP_TOTAL_BYTES:
                raise RuntimeError(f"ZIP demasiado grande al descomprimir ({total} bytes).")

            for info in infos:
                nombre_zip = PurePosixPath(info.filename.replace("\\", "/"))
                if nombre_zip.is_absolute() or ".." in nombre_zip.parts:
                    raise RuntimeError(f"Ruta insegura dentro del ZIP: {info.filename}")
                if info.is_dir():
                    continue
                if info.file_size > self.MAX_ZIP_ENTRADA_BYTES:
                    textos.append(f"[{info.filename}: omitido por tamaño excesivo]")
                    continue
                nombre = Path(nombre_zip.name)
                ext = nombre.suffix.lower()
                if ext in self.EXTENSIONES_MULTIMEDIA or ext in self.EXTENSIONES_OCR:
                    textos.append(f"[{info.filename}: omitido, requiere revisión manual]")
                    continue
                if ext not in self.EXTENSIONES_TEXTO and ext not in self.EXTENSIONES_OFFICE_TEXTO and ext not in {".pdf", ".pptx", ".xlsx"}:
                    textos.append(f"[{info.filename}: formato no soportado dentro del ZIP]")
                    continue

                temporal = self.temporal_dir / "_tmp_zip_extract" / nombre.name
                temporal.parent.mkdir(parents=True, exist_ok=True)
                temporal.write_bytes(z.read(info))
                lectura = self.leer_entrega(temporal)
                try:
                    temporal.unlink()
                except Exception:
                    pass
                textos.append(f"--- {info.filename} ---")
                textos.append(lectura.texto or lectura.motivo)
        return "\n".join(textos)

    @staticmethod
    def _leer_imagen_ocr(path: Path) -> str:
        try:
            from PIL import Image
            import pytesseract
        except ImportError as e:
            raise RuntimeError("Instala pillow y pytesseract para OCR de imágenes") from e

        return pytesseract.image_to_string(Image.open(path), lang="spa+eng")

    @staticmethod
    def _sanitizar(nombre: str) -> str:
        limpio = re.sub(r"[\\/:*\"<>|]", "_", nombre.strip())
        return re.sub(r"\s+", " ", limpio)[:120] or "alumno"

    @staticmethod
    def _ruta_prompt_disponible(prompts_dir: Path, nombre_archivo: str) -> Path:
        base = prompts_dir / nombre_archivo
        correccion = base.with_name(f"{base.stem}_correccion.json")
        if not base.exists() and not correccion.exists():
            return base
        marca = datetime.now().strftime("%Y%m%d_%H%M%S")
        for indice in range(1, 100):
            sufijo = f"_{marca}" if indice == 1 else f"_{marca}_{indice:02d}"
            candidata = base.with_name(f"{base.stem}{sufijo}{base.suffix}")
            candidata_correccion = candidata.with_name(f"{candidata.stem}_correccion.json")
            if not candidata.exists() and not candidata_correccion.exists():
                return candidata
        raise RuntimeError(f"No se pudo encontrar un nombre libre para {nombre_archivo}.")

    @staticmethod
    def _guardar_manifiesto_acumulado(manifiesto_path: Path, nuevos: list[dict]) -> None:
        existentes: list[dict] = []
        if manifiesto_path.exists():
            try:
                datos = json.loads(manifiesto_path.read_text(encoding="utf-8"))
                if isinstance(datos, list):
                    existentes = [item for item in datos if isinstance(item, dict)]
            except Exception as exc:
                logger.warning("No se pudo leer el manifiesto previo; se regenerara con las nuevas entregas: %s", exc)

        acumulado: dict[tuple[str, str, str, str, str], dict] = {}
        for item in [*existentes, *nuevos]:
            clave = (
                str(item.get("actividad", "")),
                str(item.get("id", "")),
                str(item.get("alumno", "")),
                str(item.get("archivo", "")),
                str(item.get("archivo_original", "")),
            )
            acumulado[clave] = item
        manifiesto_path.write_text(
            json.dumps(list(acumulado.values()), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _limpiar_bloque_carm_para_prompt(texto: str, max_chars: int = MAX_CONTEXTO_PROMPT_CHARS) -> str:
        texto = unescape(texto or "")
        texto = re.sub(r"//<!\[CDATA\[.*//\]\]>", "\n", texto, flags=re.S)
        texto = re.sub(r"<script\b.*</script>", "\n", texto, flags=re.S | re.I)
        texto = texto.replace("\r", "\n")

        def normalizar_linea(valor: str) -> str:
            normalizado = unicodedata.normalize("NFKD", valor)
            return "".join(c for c in normalizado if not unicodedata.combining(c)).lower()

        patrones_ruido = (
            "salta al contenido principal",
            "panel lateral",
            "notificaciones",
            "no tienes notificaciones",
            "ver todo",
            "área personal",
            "area personal",
            "ver perfil",
            "calificaciones",
            "calendario",
            "cambiar rol",
            "cerrar sesión",
            "cerrar sesion",
            "administración del sitio",
            "administracion del sitio",
            "mis cursos",
            "este curso",
            "cuestionarios",
            "foros",
            "herramientas externas",
            "paquetes scorm",
            "manual uso de la plataforma",
            "video tutorial",
            "manual acogida",
            "expediente",
            "javascript",
            "document.body",
            "jsenabled",
            "haga clic en",
            "actividad previa",
            "próxima actividad",
            "proxima actividad",
            "ir a...",
            "avisos",
            "notas importantes",
            "readspeaker",
            "tiempo invertido",
            "novedades",
            "dudas y consultas",
            "glosario",
            "hipervínculos",
            "hipervinculos",
            "guía didáctica",
            "guia didactica",
            "conexión",
            "conexion",
            "contenido multimedia",
            "para saber más",
            "para saber mas",
            "cuestionario de evaluación",
            "cuestionario de evaluacion",
            "vídeo clase",
            "video clase",
        )

        lineas_limpias: list[str] = []
        vistas: set[str] = set()
        for linea in texto.splitlines():
            linea = re.sub(r"\s+", " ", linea).strip()
            if not linea or len(linea) <= 2:
                continue
            normalizada = normalizar_linea(linea)
            if any(normalizar_linea(patron) in normalizada for patron in patrones_ruido):
                continue
            if re.fullmatch(r"[{}()[\];,./\\|:_\-*=+<>!¡¿\"'`~0-9\s]+", linea):
                continue
            if normalizada in vistas:
                continue
            vistas.add(normalizada)
            lineas_limpias.append(linea)

        casos_o_recursos = sum(
            1
            for linea in lineas_limpias
            if re.search(r"\bud\d{2}\b|\bcaso práctico\b|contenido imprimible|contenido multimedia", linea, flags=re.I)
        )
        if casos_o_recursos >= 8 and len("\n".join(lineas_limpias)) < 8000:
            return (
                "La cache contiene una página índice de Moodle, no contenido didáctico útil. "
                "No se incluye para evitar ruido en la corrección."
            )

        limpio = re.sub(r"\n{3,}", "\n\n", "\n".join(lineas_limpias)).strip()
        if len(limpio) < 400:
            return (
                "No hay contexto didáctico limpio suficiente en cache. "
                "Usa el enunciado, la rúbrica y la respuesta del alumno."
            )
        if max_chars > 0 and len(limpio) > max_chars:
            limpio = limpio[:max_chars].rsplit("\n", 1)[0].strip()
            limpio += "\n\n[Contexto didáctico recortado para ahorrar tokens.]"
        return limpio or "No hay contexto didáctico limpio disponible en cache."

    def _codigo_para_archivo(self, path: Path) -> str:
        partes = [path.stem, path.parent.name]
        for parte in partes:
            m = re.search(r"\bud\d{2}cp\d{2}\b", parte.lower())
            if m:
                return m.group(0)
        return self.actividad_codigo

    def obtener_pendientes(self) -> list[EnvioPendiente]:
        self.pendientes_dir.mkdir(parents=True, exist_ok=True)
        pendientes: list[EnvioPendiente] = []
        for f in sorted(self.pendientes_dir.rglob("*")):
            if f.is_file():
                try:
                    partes_relativas = {parte.lower() for parte in f.relative_to(self.pendientes_dir).parts}
                except ValueError:
                    partes_relativas = set()
                if partes_relativas & {"prompts_codex", "archivados_prompt"}:
                    continue
                codigo = self._codigo_para_archivo(f)
                alumno = self._sanitizar(re.sub(r"[_ -]*ud\d{2}cp\d{2}[_ -]*", " ", f.stem, flags=re.I))
                pendientes.append(
                    EnvioPendiente(
                        alumno=alumno,
                        archivo=f,
                        actividad_codigo=codigo,
                        actividad_nombre=codigo.upper(),
                    )
                )
        return pendientes

    def escribir_salidas(self, envio: EnvioPendiente, correccion: dict) -> dict:
        alumno_dir = self.temporal_dir / envio.alumno
        alumno_dir.mkdir(parents=True, exist_ok=True)

        actividad_codigo = envio.actividad_codigo or self.actividad_codigo
        ext = envio.archivo.suffix or ".txt"
        copia_entrega = alumno_dir / self._nombre_copia_entrega(actividad_codigo, ext)
        shutil.copy2(envio.archivo, copia_entrega)

        texto_correccion = self._formatear_correccion(correccion, actividad_codigo)
        archivo_correccion = alumno_dir / f"{actividad_codigo}.txt"
        archivo_correccion.write_text(texto_correccion, encoding="utf-8")

        return {
            "alumno": envio.alumno,
            "actividad": actividad_codigo,
            "actividad_nombre": envio.actividad_nombre,
            "nota": float(correccion.get("nota", 0)),
            "retroalimentacion": self._texto_feedback(correccion),
            "archivo_original": str(envio.archivo),
            "archivo_copiado": str(copia_entrega),
            "archivo_correccion": str(archivo_correccion),
            "estado": correccion.get("estado", "borrador_pendiente_de_revision"),
        }

    @staticmethod
    def _nombre_copia_entrega(actividad_codigo: str, extension: str) -> str:
        if extension.lower() == ".txt":
            return f"{actividad_codigo}_respuesta.txt"
        return f"{actividad_codigo}{extension}"

    @staticmethod
    def _texto_feedback(correccion: dict) -> str:
        for clave in ("retroalimentacion", "comentario", "feedback", "observaciones"):
            valor = correccion.get(clave)
            if valor:
                return sanitizar_feedback(str(valor))
        return ""

    def eliminar_pendiente_calificado(self, envio: EnvioPendiente) -> None:
        try:
            if envio.archivo.exists() and envio.archivo.is_file():
                envio.archivo.unlink()
                logger.info(f"Eliminado pendiente ya calificado: {envio.archivo}")

            padre = envio.archivo.parent
            if padre != self.pendientes_dir and padre.exists() and not any(padre.iterdir()):
                padre.rmdir()
                logger.info(f"Eliminada carpeta de pendientes vacía: {padre}")
        except Exception as e:
            logger.warning(f"No se pudo eliminar pendiente ya calificado {envio.archivo}: {e}")

    @staticmethod
    def _formatear_correccion(correccion: dict, actividad_codigo: str) -> str:
        lineas = []
        titulo = actividad_codigo.upper().replace("UD", "UD").replace("CP", " CP")
        lineas.append(f"Corrección del caso práctico {titulo}")
        lineas.append("")
        lineas.append(f"Nota final: {correccion.get('nota', 0)}/10")
        lineas.append("")
        criterios = correccion.get("criterios", [])
        if criterios:
            lineas.append("Detalle por criterios:")

        for crit in criterios:
            nombre = crit.get("nombre", "Criterio")
            p = crit.get("puntuacion", 0)
            m = crit.get("maximo", "")
            c = crit.get("comentario", "")
            lineas.append(f"- {nombre}: {p}/{m}. {c}")

        if criterios:
            lineas.append("")
        lineas.append("Retroalimentación:")
        lineas.append(GeneradorSalidas._texto_feedback(correccion))
        lineas.append("")

        return "\n".join(lineas)

    def importar_correcciones_codex(self, correcciones_path: Path) -> tuple[list[dict], Path, list[Path]]:
        correcciones = self._leer_correcciones_codex(correcciones_path)
        manifiesto = self._leer_manifiesto_codex()
        resultados: list[dict] = []

        for correccion in correcciones:
            alumno = self._sanitizar(str(correccion.get("alumno", "")).strip())
            actividad = str(
                correccion.get("actividad")
                or correccion.get("actividad_codigo")
                or self.actividad_codigo
            ).strip().lower()
            if not alumno:
                logger.warning(f"Corrección omitida sin alumno: {correccion}")
                continue

            correccion_normalizada = self._normalizar_correccion_importada(correccion)
            alumno_dir = self.temporal_dir / alumno
            alumno_dir.mkdir(parents=True, exist_ok=True)

            entrada = self._buscar_entrega_en_manifiesto(
                manifiesto,
                alumno=alumno,
                actividad=actividad,
                correccion=correccion,
            )
            archivo_copiado = ""
            archivo_original = ""
            actividad_nombre = actividad
            if entrada:
                archivo_original = str(entrada.get("archivo", ""))
                actividad_nombre = str(entrada.get("actividad_nombre") or actividad)
                origen = Path(str(entrada.get("archivo", "")))
                if origen.exists() and origen.is_file():
                    ext = origen.suffix or ".txt"
                    copia_entrega = alumno_dir / self._nombre_copia_entrega(actividad, ext)
                    shutil.copy2(origen, copia_entrega)
                    archivo_copiado = str(copia_entrega)

            archivo_correccion = alumno_dir / f"{actividad}.txt"
            archivo_correccion.write_text(
                self._formatear_correccion(correccion_normalizada, actividad),
                encoding="utf-8",
            )

            resultados.append(
                {
                    "alumno": alumno,
                    "actividad": actividad,
                    "actividad_nombre": actividad_nombre,
                    "nota": float(correccion_normalizada.get("nota", 0)),
                    "retroalimentacion": self._texto_feedback(correccion_normalizada),
                    "archivo_original": archivo_original,
                    "archivo_copiado": archivo_copiado,
                    "archivo_correccion": str(archivo_correccion),
                    "estado": correccion_normalizada.get("estado", "borrador_pendiente_de_revision"),
                }
            )

        if not resultados:
            raise ValueError("No se encontró ninguna corrección importable en el JSON.")

        resumen_path = self.escribir_resumen(resultados)
        resumenes_actividad = self.escribir_resumenes_por_actividad(resultados)
        revision_path = self.escribir_revision_pendiente(resultados)

        traza_path = CORRECCIONES_DIR / "correcciones_importadas_codex.json"
        traza_path.write_text(json.dumps(resultados, indent=2, ensure_ascii=False), encoding="utf-8")

        return resultados, revision_path, [resumen_path, *resumenes_actividad, traza_path]

    @staticmethod
    def _normalizar_correccion_importada(correccion: dict) -> dict:
        normalizada = dict(correccion)
        normalizada["retroalimentacion"] = GeneradorSalidas._texto_feedback(correccion)
        estado = str(normalizada.get("estado") or normalizada.get("resultado") or "").strip().lower()
        if not estado:
            estado = "borrador_pendiente_de_revision"
        elif estado in {"apta", "apto", "aprobada", "aprobado"}:
            estado = "borrador_pendiente_de_revision"
        elif estado in {"revision", "revisión", "revision manual", "revision_manual"}:
            estado = "revision_manual_necesaria"
        normalizada["estado"] = estado
        normalizada["nota"] = float(str(normalizada.get("nota", 0) or 0).replace(",", "."))
        return normalizada

    def _leer_correcciones_codex(self, correcciones_path: Path) -> list[dict]:
        texto = self._leer_archivo_texto(correcciones_path).strip()
        if not texto:
            raise ValueError(f"No se pudo leer el archivo de correcciones: {correcciones_path}")

        if correcciones_path.suffix.lower() == ".csv":
            with correcciones_path.open("r", encoding="utf-8-sig", newline="") as handle:
                filas = list(csv.DictReader(handle, delimiter=";"))
            if not filas:
                raise ValueError("El CSV de correcciones no contiene filas.")
            correcciones_csv: list[dict] = []
            for fila in filas:
                correccion = {
                    "alumno": (fila.get("alumno") or "").strip(),
                    "actividad": (fila.get("actividad") or "").strip().lower(),
                    "nota": fila.get("nota") or 0,
                    "estado": (fila.get("estado") or "").strip(),
                    "retroalimentacion": fila.get("retroalimentacion") or "",
                    "archivo_correccion": fila.get("archivo_correccion") or "",
                }
                correcciones_csv.append(self._normalizar_correccion_importada(correccion))
            return correcciones_csv

        match = re.search(r"```(:json)\s*(.*)```", texto, flags=re.S | re.I)
        if match:
            texto = match.group(1).strip()

        datos = json.loads(texto)
        if isinstance(datos, dict):
            for clave in ("correcciones", "resultados", "entregas"):
                if isinstance(datos.get(clave), list):
                    actividad_global = datos.get("actividad") or datos.get("actividad_codigo")
                    datos = [
                        {
                            **item,
                            **({"actividad": actividad_global} if actividad_global and not item.get("actividad") else {}),
                        }
                        for item in datos[clave]
                        if isinstance(item, dict)
                    ]
                    break
            else:
                datos = [datos]

        if not isinstance(datos, list):
            raise ValueError("El JSON debe ser una lista de correcciones o un objeto con clave 'correcciones'.")

        return [item for item in datos if isinstance(item, dict)]

    def _leer_manifiesto_codex(self) -> list[dict]:
        manifiesto_path = prompts_pendientes_dir(self.pendientes_dir) / "manifiesto_entregas.json"
        if not manifiesto_path.exists():
            legado_path = self.temporal_dir / "prompts_codex" / "manifiesto_entregas.json"
            manifiesto_path = legado_path
        if not manifiesto_path.exists():
            return []
        try:
            datos = json.loads(manifiesto_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"No se pudo leer manifiesto de entregas: {e}")
            return []
        return datos if isinstance(datos, list) else []

    @staticmethod
    def _buscar_entrega_en_manifiesto(
        manifiesto: list[dict],
        alumno: str,
        actividad: str,
        correccion: dict,
    ) -> dict | None:
        alumno_norm = GeneradorSalidas._sanitizar(alumno).lower()
        actividad_norm = actividad.lower()
        id_correccion = str(correccion.get("id", "")).strip()

        candidatos = [
            item for item in manifiesto
            if GeneradorSalidas._sanitizar(str(item.get("alumno", ""))).lower() == alumno_norm
            and str(item.get("actividad", "")).lower() == actividad_norm
        ]
        if id_correccion:
            for item in candidatos:
                if str(item.get("id", "")).strip() == id_correccion:
                    return item
        return candidatos[0] if candidatos else None

    def escribir_resumen(self, resultados: list[dict]) -> Path:
        self.temporal_dir.mkdir(parents=True, exist_ok=True)
        resumen_path = self.temporal_dir / "resumen.txt"

        lineas = []
        lineas.append("Resumen de puntuaciones y retroalimentación")
        lineas.append("")

        for r in resultados:
            lineas.append(f"Alumno: {r['alumno']}")
            lineas.append(f"Actividad: {r['actividad']}")
            lineas.append(f"Nota: {r['nota']}/10")
            lineas.append(f"Feedback a comunicar: {r['retroalimentacion']}")
            lineas.append("")

        resumen_path.write_text("\n".join(lineas), encoding="utf-8")
        return resumen_path

    def escribir_resumenes_por_actividad(self, resultados: list[dict]) -> list[Path]:
        self.temporal_dir.mkdir(parents=True, exist_ok=True)
        por_actividad: dict[str, list[dict]] = {}
        for r in resultados:
            por_actividad.setdefault(r["actividad"], []).append(r)

        rutas: list[Path] = []
        for actividad, items in sorted(por_actividad.items()):
            resumen_path = self.temporal_dir / f"resumen_{actividad}.txt"
            lineas = [
                f"Resumen de puntuaciones y retroalimentación - {actividad.upper()}",
                "",
            ]

            for r in items:
                lineas.append(f"Alumno: {r['alumno']}")
                lineas.append(f"Nota: {r['nota']}/10")
                lineas.append(f"Feedback a comunicar: {r['retroalimentacion']}")
                lineas.append("")

            resumen_path.write_text("\n".join(lineas), encoding="utf-8")
            rutas.append(resumen_path)

        return rutas

    def escribir_revision_pendiente(self, resultados: list[dict]) -> Path:
        self.temporal_dir.mkdir(parents=True, exist_ok=True)
        revision_path = self.temporal_dir / "revision_pendiente.csv"

        fieldnames = ["alumno", "actividad", "nota", "estado", "retroalimentacion", "archivo_correccion"]
        rows_by_key: dict[tuple[str, str], dict] = {}
        if revision_path.exists():
            try:
                with revision_path.open("r", encoding="utf-8-sig", newline="") as handle:
                    for row in csv.DictReader(handle, delimiter=";"):
                        rows_by_key[_clave_revision_csv(row)] = row
            except Exception as exc:
                logger.warning("No se pudo conservar revision_pendiente.csv existente: %s", exc)

        for r in resultados:
            feedback = str(r["retroalimentacion"]).replace("\n", " ").replace(";", ",")
            row = {
                "alumno": r["alumno"],
                "actividad": r["actividad"],
                "nota": r["nota"],
                "estado": r["estado"],
                "retroalimentacion": feedback,
                "archivo_correccion": r["archivo_correccion"],
            }
            rows_by_key[_clave_revision_csv(row)] = row

        with revision_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter=";")
            writer.writeheader()
            writer.writerows(rows_by_key.values())
        return revision_path

    def escribir_prompts_codex(
        self,
        pendientes_por_actividad: dict[str, list[EnvioPendiente]],
        contexto_unidad: str,
        prompts_path: str | Path | None = None,
        max_entregas_por_prompt: int = 8,
        max_caracteres_entrega: int = 0,
    ) -> list[Path]:
        prompts_dir = prompts_pendientes_dir(self.pendientes_dir)
        prompts_dir.mkdir(parents=True, exist_ok=True)

        gestor_prompts = GestorPrompts(prompts_path)
        rutas: list[Path] = []
        manifiesto: list[dict] = []
        contexto_limpio = self._limpiar_bloque_carm_para_prompt(contexto_unidad)

        for actividad_codigo, envios in sorted(pendientes_por_actividad.items()):
            contexto_actividad = self._limpiar_bloque_carm_para_prompt(
                seleccionar_contexto_para_actividad(contexto_limpio, actividad_codigo)
            )
            entregas: list[dict] = []
            revision_manual: list[dict] = []
            enunciado = self._limpiar_bloque_carm_para_prompt(
                next((e.actividad_enunciado for e in envios if e.actividad_enunciado), ""),
                max_chars=5000,
            )

            for idx, envio in enumerate(envios):
                lectura = self.leer_entrega(envio.archivo)
                texto_entrega = lectura.texto
                entrega_truncada = False
                if max_caracteres_entrega > 0 and len(texto_entrega) > max_caracteres_entrega:
                    texto_entrega = texto_entrega[:max_caracteres_entrega]
                    entrega_truncada = True
                item_base = {
                    "id": str(idx),
                    "alumno": envio.alumno,
                    "actividad": actividad_codigo,
                    "archivo": str(envio.archivo),
                    "archivo_original": envio.archivo_original_nombre,
                    "estado_entrega": envio.estado_entrega,
                }

                if lectura.requiere_revision_manual:
                    revision_manual.append({**item_base, "motivo": lectura.motivo})
                else:
                    entregas.append(
                        {
                            **item_base,
                            "respuesta": texto_entrega,
                            **({"respuesta_truncada": True} if entrega_truncada else {}),
                        }
                    )

                manifiesto.append(
                    {
                        **item_base,
                        "requiere_revision_manual": lectura.requiere_revision_manual,
                        "motivo": lectura.motivo,
                    }
                )

            prompt_cfg = gestor_prompts.obtener(actividad_codigo)
            max_entregas = int(max_entregas_por_prompt or 0)
            tamano_lote = len(entregas) if max_entregas <= 0 else max(1, max_entregas)
            tamano_lote = max(1, tamano_lote)
            lotes = [
                entregas[i:i + tamano_lote]
                for i in range(0, len(entregas), tamano_lote)
            ] or [[]]

            for numero_lote, entregas_lote in enumerate(lotes, start=1):
                sufijo_lote = f"_lote{numero_lote:02d}" if len(lotes) > 1 else ""
                prompt_path = self._ruta_prompt_disponible(prompts_dir, f"prompt_{actividad_codigo}{sufijo_lote}.md")
                lineas = [
                f"# Prompt para Codex - {actividad_codigo}",
                "",
                "## Instrucciones de sistema",
                "",
                prompt_cfg["sistema"],
                "",
                "## Rúbrica",
                "",
                prompt_cfg["criterios"],
                "",
                "## Enunciado extraído de CARM",
                "",
                enunciado if "No hay contexto didáctico limpio disponible" not in enunciado else "No se pudo extraer un enunciado específico de CARM para esta actividad. Usa la rúbrica y el contexto didáctico limpio.",
                "",
                "## Contexto didactico limpio desde cache",
                "",
                contexto_actividad,
                "",
                "## Tarea",
                "",
                "Corrige todas las entregas legibles usando solo la rúbrica, el enunciado y el contexto didáctico anterior.",
                "Ignora cualquier rastro técnico, navegación de Moodle o metadatos que aparezcan accidentalmente.",
                "Evalúa solo lo que el alumno ha escrito, sin inventar méritos.",
                "Redacta todo el feedback en espanol usando solo alfabeto latino, numeros y puntuacion comun. No uses caracteres de otros alfabetos.",
                "Devuelve únicamente JSON válido, sin Markdown, con este formato exacto:",
                "",
                "```json",
                "{",
                f'  "actividad": "{actividad_codigo}",',
                '  "correcciones": [',
                "    {",
                '      "id": "0",',
                '      "alumno": "Nombre del alumno",',
                '      "nota": 0,',
                '      "criterios": [',
                '        {"nombre": "Presentación del trabajo", "maximo": 3, "puntuacion": 0, "comentario": "..."},',
                '        {"nombre": "Adecuación al enunciado", "maximo": 4, "puntuacion": 0, "comentario": "..."},',
                '        {"nombre": "Aplicación práctica", "maximo": 3, "puntuacion": 0, "comentario": "..."}',
                "      ],",
                '      "retroalimentacion": "Feedback final para el alumno"',
                "    }",
                "  ]",
                "}",
                "```",
                "",
                "No incluyas en `correcciones` las entregas marcadas como revisión manual.",
                "",
                f"Lote {numero_lote} de {len(lotes)}. Entregas en este lote: {len(entregas_lote)}.",
                "",
                "## Entregas legibles",
                "",
                "```json",
                json.dumps(entregas_lote, ensure_ascii=False, indent=2),
                "```",
                "",
                "## Entregas que requieren revisión manual",
                "",
                "Estas no se deben corregir automáticamente:",
                "",
                "```json",
                json.dumps(revision_manual, ensure_ascii=False, indent=2),
                "```",
                "",
                ]
                prompt_path.write_text("\n".join(lineas), encoding="utf-8")
                rutas.append(prompt_path)

        manifiesto_path = prompts_dir / "manifiesto_entregas.json"
        self._guardar_manifiesto_acumulado(manifiesto_path, manifiesto)
        rutas.append(manifiesto_path)
        return rutas

    def corregir_prompts_con_openai(
        self,
        rutas_prompts: list[Path] | None = None,
        output_dir: Path | None = None,
        importar: bool = False,
        warn_tokens_prompt: int = OPENAI_PROMPT_TOKEN_WARN,
        max_tokens_prompt: int = OPENAI_PROMPT_TOKEN_MAX,
    ) -> tuple[list[Path], Path | None]:
        if OpenAI is None:
            raise RuntimeError("El paquete openai no esta instalado en la venv.")
        if not openai_api_key_configurada():
            raise RuntimeError("Falta OPENAI_API_KEY en .env o conserva el valor de ejemplo.")

        prompts_dir = prompts_pendientes_dir(self.pendientes_dir)
        if not prompts_dir.exists():
            prompts_dir = self.temporal_dir / "prompts_codex"
        candidatos = [
            ruta for ruta in (rutas_prompts or sorted(prompts_dir.glob("prompt_*.md")))
            if ruta.suffix.lower() == ".md" and ruta.name.startswith("prompt_")
        ]
        prompts_ya_resueltos = [
            ruta
            for ruta in candidatos
            if ruta.with_name(f"{ruta.stem}_correccion.json").exists()
        ]
        if prompts_ya_resueltos:
            archivar_prompts_resueltos(prompts_ya_resueltos, modo="ya_tenian_correccion")
        prompts = [
            ruta
            for ruta in candidatos
            if ruta.exists() and not ruta.with_name(f"{ruta.stem}_correccion.json").exists()
        ]
        if not prompts:
            raise ValueError("No hay prompts .md preparados para enviar a OpenAI API.")

        output_dir = output_dir or prompts_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        for viejo in output_dir.glob("*_correccion.json"):
            archivo_dir = output_dir / "archivados" / datetime.now().strftime("%Y%m%d_%H%M%S_pre_openai")
            moved = _mover_si_existe(viejo, archivo_dir)
            if moved:
                logger.info("Correccion API anterior archivada antes de generar nueva salida: %s", moved)

        cliente = OpenAI(api_key=os.getenv("OPENAI_API_KEY", "").strip())
        modelo = os.getenv("OPENAI_MODEL", "gpt-5-mini").strip() or "gpt-5-mini"
        rutas_correcciones: list[Path] = []
        prompts_resueltos: list[Path] = []

        for prompt_path in prompts:
            salida_path = output_dir / f"{prompt_path.stem}_correccion.json"
            prompt_texto = normalizar_texto_para_cli(prompt_path.read_text(encoding="utf-8"))
            instruccion = (
                f"{prompt_texto}\n\n"
                "IMPORTANTE: responde solo con JSON valido, sin markdown ni explicaciones fuera del JSON."
            )
            tokens_estimados = estimar_tokens_aprox(instruccion)
            logger.info(
                "Prompt preparado para OpenAI API: %s (%s caracteres, ~%s tokens estimados)",
                prompt_path,
                len(instruccion),
                tokens_estimados,
            )
            if warn_tokens_prompt > 0 and tokens_estimados >= warn_tokens_prompt:
                logger.warning(
                    "Prompt grande para API (%s ~%s tokens). Si falla por limite, vuelve a preparar con menos entregas por prompt.",
                    prompt_path.name,
                    tokens_estimados,
                )
            if max_tokens_prompt > 0 and tokens_estimados >= max_tokens_prompt:
                raise RuntimeError(
                    f"Prompt {prompt_path.name} demasiado grande para enviarlo con seguridad "
                    f"(~{tokens_estimados} tokens estimados, limite {max_tokens_prompt}). "
                    "Vuelve a preparar con Entregas por prompt 3, 4 o 6."
                )
            logger.info("Enviando prompt preparado a OpenAI API: %s", prompt_path)
            respuesta_api = cliente.chat.completions.create(
                model=modelo,
                messages=[
                    {
                        "role": "system",
                        "content": "Responde exclusivamente con JSON valido en espanol.",
                    },
                    {"role": "user", "content": instruccion},
                ],
                response_format={"type": "json_object"},
                max_completion_tokens=16000,
            )
            contenido = respuesta_api.choices[0].message.content or "{}"
            salida_path.write_text(contenido, encoding="utf-8")
            rutas_correcciones.append(salida_path)
            prompts_resueltos.append(prompt_path)
            logger.info("Correccion API guardada en: %s", salida_path)

        combinado_path = output_dir / "correcciones_codex_combinadas.json"
        correcciones_combinadas: list[dict] = []
        for ruta in rutas_correcciones:
            correcciones_combinadas.extend(self._leer_correcciones_codex(ruta))
        combinado_path.write_text(
            json.dumps(correcciones_combinadas, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        rutas_correcciones.append(combinado_path)

        revision_path: Path | None = None
        if importar:
            _, revision_path, _ = self.importar_correcciones_codex(combinado_path)

        archivar_prompts_resueltos(prompts_resueltos, modo="resueltos_api")
        archivar_archivos_auxiliares_prompts(output_dir, modo="post_api")
        return rutas_correcciones, revision_path


async def ejecutar_flujo(args) -> None:
    pendientes_dir = Path(args.pendientes)
    temporal_dir = Path(args.temporal)
    if getattr(args, "comprobar_openai_api", False):
        try:
            estado_openai = comprobar_openai_api_configurada()
        except Exception as exc:
            logger.error("OpenAI API no esta lista: %s", exc)
            return
        logger.info("OpenAI API configurada correctamente.")
        logger.info("Modelo OpenAI configurado: %s", estado_openai["model"])
        return

    if getattr(args, "comprobar_codex_cli", False):
        logger.warning(
            "Codex CLI integrado esta desactivado en el flujo actual. "
            "Usa $C desde Codex y despues importa los *_correccion.json desde la interfaz."
        )
        return

    flujo_correccion_carm = getattr(args, "flujo_correccion_carm", False)
    if flujo_correccion_carm:
        args.preparar_carm_codex = True
        args.corregir_con_codex = False
        args.importar_tras_codex = False
        logger.warning(
            "--flujo-correccion-carm ya no llama a Codex CLI; solo prepara prompts. "
            "Resuelvelos con $C e importalos desde la interfaz."
        )
    if getattr(args, "requerir_openai_api", False) or getattr(args, "corregir_prompts_openai", False):
        try:
            estado_openai = comprobar_openai_api_configurada()
        except Exception as exc:
            logger.error("OpenAI API requerida pero no configurada: %s", exc)
            return
        logger.info("OpenAI API preparada. Modelo: %s", estado_openai["model"])
    if getattr(args, "corregir_con_codex", False):
        logger.error(
            "--corregir-con-codex esta desactivado para evitar bloqueos con Codex CLI. "
            "Usa $C sobre los prompts generados e importa los JSON."
        )
        return
    preparar_carm_codex = getattr(args, "preparar_carm_codex", False)
    unidades_filtro = {
        ExtractorCarm._normalizar_codigo_unidad(valor)
        for valor in re.split(r"[,;\s]+", getattr(args, "unidad", "") or "")
        if valor.strip()
    }
    actividades_filtro = {
        valor.strip().lower()
        for valor in re.split(r"[,;\s]+", getattr(args, "actividad", "") or "")
        if valor.strip()
    }

    contexto_unidad = ""
    pendientes_extraidos: list[EnvioPendiente] = []
    cache_curso = CacheCursoCarm()
    if cache_curso.purgar_si_expirada():
        registrar_auditoria("cache_curso_purgada_por_fecha_fin", course_id=cache_curso.course_id)

    if getattr(args, "purgar_datos_personales_locales", False):
        if not getattr(args, "confirmar_purga_datos", False):
            logger.error("Purga bloqueada: anade --confirmar-purga-datos para borrar salidas locales con datos personales.")
            registrar_auditoria("purga_datos_personales_locales", "bloqueada_sin_confirmacion")
            return
        resumen_purga = purgar_datos_personales_locales(pendientes_dir, temporal_dir)
        logger.info("Purga local completada: %s", resumen_purga)
        return

    if getattr(args, "borrar_cache_curso", False):
        if cache_curso.borrar():
            logger.info(f"Cache del curso borrada: {cache_curso.path}")
            registrar_auditoria("cache_curso_borrada", course_id=cache_curso.course_id)
        else:
            logger.info(f"No existía cache del curso en: {cache_curso.path}")
        return

    if getattr(args, "comprobar_login_carm", False):
        credenciales = obtener_credenciales_carm_interactivo("comprobar login CARM")
        if not credenciales:
            return
        usuario, contrasena = credenciales
        extractor = ExtractorCarm(
            usuario,
            contrasena,
            pendientes_dir,
            mantener_navegador=False,
            cache=cache_curso,
            usar_cache=True,
        )
        await extractor.comprobar_login()
        registrar_auditoria("comprobar_login_carm", course_id=cache_curso.course_id)
        return

    if getattr(args, "listar_cursos_carm", False):
        credenciales = obtener_credenciales_carm_interactivo("listar cursos CARM")
        if not credenciales:
            return
        usuario, contrasena = credenciales
        extractor = ExtractorCarm(
            usuario,
            contrasena,
            pendientes_dir,
            mantener_navegador=False,
            cache=cache_curso,
            usar_cache=True,
        )
        cursos = await extractor.listar_cursos_disponibles()
        for curso in cursos:
            logger.info("- %s: %s", curso.get("id", ""), curso.get("titulo", ""))
        registrar_auditoria("listar_cursos_carm", cursos=len(cursos))
        return

    if getattr(args, "importar_correcciones_codex", ""):
        salida = GeneradorSalidas(pendientes_dir, temporal_dir, actividad_codigo=args.actividad_codigo)
        correcciones_path = Path(args.importar_correcciones_codex)
        correcciones_a_importar = (
            sorted(correcciones_path.glob("*_correccion.json"))
            if correcciones_path.exists() and correcciones_path.is_dir()
            else [correcciones_path]
        )
        if not correcciones_a_importar:
            logger.error(f"No hay JSON de correccion pendientes en: {correcciones_path}")
            return
        resultados_totales: list[dict] = []
        revision_path: Path | None = None
        rutas_extra_totales: list[Path] = []
        try:
            for ruta_importar in correcciones_a_importar:
                resultados, revision_path, rutas_extra = salida.importar_correcciones_codex(ruta_importar)
                resultados_totales.extend(resultados)
                rutas_extra_totales.extend(rutas_extra)
                archivo_dir = archivar_correccion_importada_codex(ruta_importar, pendientes_dir, temporal_dir)
                if archivo_dir:
                    logger.info(f"JSON/prompt importado archivado en: {archivo_dir}")
        except Exception as e:
            logger.error(f"No se pudieron importar correcciones Codex: {e}")
            return

        logger.info(f"Archivos JSON importados: {len(correcciones_a_importar)}")
        logger.info(f"Correcciones importadas: {len(resultados_totales)}")
        for ruta in rutas_extra_totales:
            logger.info(f"- {ruta}")
        logger.info(f"Hoja de revisión manual generada en: {revision_path}")
        registrar_auditoria(
            "importar_correcciones_codex",
            archivos=len(correcciones_a_importar),
            correcciones=len(resultados_totales),
            origen=correcciones_path,
            revision=revision_path,
        )
        return

    if getattr(args, "corregir_prompts_openai", False) and not (
        getattr(args, "preparar_prompts_codex", False) or preparar_carm_codex
    ):
        salida = GeneradorSalidas(pendientes_dir, temporal_dir, actividad_codigo=args.actividad_codigo)
        try:
            rutas_correcciones, revision_path = salida.corregir_prompts_con_openai(
                output_dir=Path(args.openai_output_dir) if getattr(args, "openai_output_dir", "") else None,
                importar=getattr(args, "importar_tras_openai", True),
                warn_tokens_prompt=getattr(args, "openai_warn_tokens_prompt", OPENAI_PROMPT_TOKEN_WARN),
                max_tokens_prompt=getattr(args, "openai_max_tokens_prompt", OPENAI_PROMPT_TOKEN_MAX),
            )
        except Exception as e:
            logger.error(f"No se pudieron corregir prompts con OpenAI API: {e}")
            return
        logger.info("Correcciones generadas por OpenAI API:")
        for ruta in rutas_correcciones:
            logger.info(f"- {ruta}")
        if revision_path:
            logger.info(f"Correcciones importadas. Hoja de revision: {revision_path}")
        if not getattr(args, "conservar_pendientes", False):
            manifiesto_path = prompts_pendientes_dir(pendientes_dir) / "manifiesto_entregas.json"
            archivados = archivar_pendientes_con_prompt(manifiesto_path, pendientes_dir)
            if archivados:
                logger.info("Entregas pendientes archivadas tras correccion API correcta: %s", archivados)
        return

    if getattr(args, "subir_correcciones_carm", ""):
        if not requiere_curso_carm_configurado("subir correcciones a CARM"):
            return
        credenciales = obtener_credenciales_carm_interactivo("subir/previsualizar correcciones en CARM")
        if not credenciales:
            return
        usuario, contrasena = credenciales

        salida = GeneradorSalidas(pendientes_dir, temporal_dir, actividad_codigo=args.actividad_codigo)
        correcciones_path = Path(args.subir_correcciones_carm)
        try:
            correcciones = salida._leer_correcciones_codex(correcciones_path)
        except Exception as e:
            logger.error(f"No se pudieron leer correcciones para CARM: {e}")
            return

        publicar = getattr(args, "publicar_carm", False)
        if publicar:
            logger.error(
                "Publicacion automatica directa desactivada por seguridad. "
                "Usa --subida-asistida-carm para mantener guardado humano en CARM."
            )
            registrar_auditoria("publicar_carm", "bloqueada_publicacion_automatica_desactivada")
            return
        asistida = getattr(args, "subida_asistida_carm", False)
        extractor = ExtractorCarm(
            usuario,
            contrasena,
            pendientes_dir,
            mantener_navegador=getattr(args, "mantener_navegador", False),
            guardar_evidencias=getattr(args, "guardar_evidencias", False),
            guardar_trace_subida=getattr(args, "guardar_trace_subida", False),
            unidades=unidades_filtro,
            actividades=actividades_filtro,
            cache=cache_curso,
            usar_cache=True,
        )
        try:
            resultados_subida = await extractor.subir_correcciones_carm(
                correcciones,
                publicar=publicar,
                asistida=asistida,
                solo_primera_previsualizacion=getattr(args, "solo_primera_previsualizacion_carm", False),
            )
        except Exception as e:
            logger.error(f"No se pudo completar la subida a CARM: {e}")
            return

        salida_path = RESPUESTAS_DIR / (
            "subida_carm_asistida.json" if asistida else "subida_carm_previsualizacion.json"
        )
        salida_path.write_text(
            json.dumps(resultados_subida, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        registrar_auditoria(
            "subida_asistida_carm" if asistida else "previsualizar_subida_carm",
            correcciones=len(correcciones),
            resultados=len(resultados_subida),
            salida=salida_path,
        )
        for resultado in resultados_subida:
            logger.info(
                "%s %s %s: %s",
                resultado.get("actividad", ""),
                resultado.get("alumno", ""),
                resultado.get("nota", ""),
                resultado.get("estado", ""),
            )
        logger.info(f"Registro de subida CARM generado en: {salida_path}")
        actualizacion_csv = {"aplicado": False, "eliminadas": 0, "restantes": None}
        if publicar or asistida:
            actualizacion_csv = actualizar_revision_pendiente_tras_subida(correcciones_path, resultados_subida)

        if publicar or asistida:
            restantes = actualizacion_csv.get("restantes")
            if restantes == 0 or not actualizacion_csv.get("aplicado"):
                if correcciones_path.exists() or correcciones_path.suffix.lower() != ".csv":
                    archivar_prompt_y_correccion_usados(
                        correcciones_path=correcciones_path,
                        temporal_dir=temporal_dir,
                        modo="publicada" if publicar else "asistida_confirmada",
                        pendientes_dir=pendientes_dir,
                    )
                archivar_resumenes_usados(
                    resultados_subida,
                    temporal_dir=temporal_dir,
                    modo="publicada" if publicar else "asistida_confirmada",
                )
            elif restantes:
                logger.info(
                    "Quedan %s correccion(es) sin subir; no se archivan los prompts usados todavia.",
                    restantes,
                )
        if asistida:
            logger.info("Modo subida asistida: solo se eliminan del CSV las filas confirmadas por el usuario.")
        elif not publicar:
            logger.info("Modo previsualización: no se ha pulsado guardar en CARM.")
        return

    usar_cache = (
        not getattr(args, "sin_cache", False)
        and not getattr(args, "refrescar_cache", False)
    )

    if args.contexto_unidad:
        contexto_path = Path(args.contexto_unidad)
        if contexto_path.exists() and contexto_path.is_file():
            contexto_unidad = GeneradorSalidas._leer_archivo_texto(contexto_path)
            logger.info(f"Contexto de unidad cargado desde: {contexto_path}")
        else:
            logger.warning(f"No se encontró el archivo de contexto: {contexto_path}")

    if (
        args.extraer_carm
        or preparar_carm_codex
        or getattr(args, "diagnosticar_carm", False)
        or getattr(args, "solo_listar_carm", False)
        or getattr(args, "cachear_curso", False)
    ):
        if not requiere_curso_carm_configurado("extraer/cachear datos del curso"):
            return
        credenciales = obtener_credenciales_carm_interactivo("extraer o cachear datos desde CARM")
        if not credenciales:
            return
        usuario, contrasena = credenciales

        extractor = ExtractorCarm(
            usuario,
            contrasena,
            pendientes_dir,
            mantener_navegador=getattr(args, "mantener_navegador", False),
            guardar_evidencias=getattr(args, "guardar_evidencias", False),
            unidades=unidades_filtro,
            actividades=actividades_filtro,
            cache=cache_curso,
            usar_cache=usar_cache,
        )
        try:
            if getattr(args, "cachear_curso", False) and not (args.extraer_carm or preparar_carm_codex):
                logger.info("Cacheando recursos estables del curso CARM.")
                await extractor.cachear_curso()
                logger.info(f"Cache del curso actualizada en: {cache_curso.path}")
                return

            if getattr(args, "diagnosticar_carm", False):
                diagnostico_path = await extractor.diagnosticar(
                    incluir_enlaces=getattr(args, "incluir_enlaces_diagnostico", False),
                )
                logger.info(f"Diagnóstico CARM generado en: {diagnostico_path}")
                return

            logger.info("Iniciando extraccion en CARM (login -> my -> curso -> grading)")
            contexto_unidad, pendientes_extraidos = await extractor.ejecutar(
                solo_listar=getattr(args, "solo_listar_carm", False) and not preparar_carm_codex,
            )
            if getattr(args, "cachear_curso", False) or preparar_carm_codex:
                logger.info(f"Cache del curso actualizada en: {cache_curso.path}")
            if getattr(args, "solo_listar_carm", False) and not preparar_carm_codex:
                logger.info("Listado CARM generado sin descargar archivos ni corregir.")
                return
        except Exception as e:
            logger.error(f"No se pudo completar extraccion CARM: {e}")
            return

    if not contexto_unidad:
        if usar_cache:
            contexto_unidad = cache_curso.obtener_contexto_unidades(unidades_filtro)
        if not contexto_unidad:
            contexto_unidad = (
                "No se pudo extraer automáticamente el contenido imprimible. "
                "Aplica igualmente criterios de protección de datos y buenas prácticas del caso."
            )

    salida = GeneradorSalidas(pendientes_dir, temporal_dir, actividad_codigo=args.actividad_codigo)
    pendientes = pendientes_extraidos or salida.obtener_pendientes()
    if unidades_filtro or actividades_filtro:
        pendientes = [
            envio for envio in pendientes
            if ExtractorCarm._actividad_permitida(
                envio.actividad_codigo,
                unidades_filtro,
                actividades_filtro,
            )
        ]

    if not pendientes:
        logger.warning(f"No hay archivos pendientes en {pendientes_dir}")
        return

    pendientes_por_actividad: dict[str, list[EnvioPendiente]] = {}
    for envio in pendientes:
        pendientes_por_actividad.setdefault(envio.actividad_codigo, []).append(envio)

    if getattr(args, "preparar_prompts_codex", False) or preparar_carm_codex:
        rutas_prompts = salida.escribir_prompts_codex(
            pendientes_por_actividad,
            contexto_unidad,
            prompts_path=args.prompts,
            max_entregas_por_prompt=getattr(args, "max_entregas_por_prompt", 8),
            max_caracteres_entrega=getattr(args, "max_caracteres_entrega", 0),
        )
        logger.info("Prompts para Codex generados sin llamar a la API:")
        for ruta in rutas_prompts:
            logger.info(f"- {ruta}")
        archivar_tras_codex = (
            not getattr(args, "conservar_pendientes", False)
            and not getattr(args, "corregir_prompts_openai", False)
        )
        if archivar_tras_codex:
            manifiesto_path = prompts_pendientes_dir(pendientes_dir) / "manifiesto_entregas.json"
            archivados = archivar_pendientes_con_prompt(manifiesto_path, pendientes_dir)
            if archivados:
                logger.info("Entregas pendientes archivadas tras generar prompt: %s", archivados)
        if getattr(args, "corregir_prompts_openai", False):
            try:
                rutas_correcciones, revision_path = salida.corregir_prompts_con_openai(
                    rutas_prompts,
                    output_dir=Path(args.openai_output_dir) if getattr(args, "openai_output_dir", "") else None,
                    importar=getattr(args, "importar_tras_openai", True),
                    warn_tokens_prompt=getattr(args, "openai_warn_tokens_prompt", OPENAI_PROMPT_TOKEN_WARN),
                    max_tokens_prompt=getattr(args, "openai_max_tokens_prompt", OPENAI_PROMPT_TOKEN_MAX),
                )
            except Exception as e:
                logger.error(f"No se pudieron corregir prompts con OpenAI API: {e}")
                return
            logger.info("Correcciones generadas por OpenAI API:")
            for ruta in rutas_correcciones:
                logger.info(f"- {ruta}")
            if revision_path:
                logger.info(f"Correcciones importadas. Hoja de revision: {revision_path}")
            if not getattr(args, "conservar_pendientes", False):
                manifiesto_path = prompts_pendientes_dir(pendientes_dir) / "manifiesto_entregas.json"
                archivados = archivar_pendientes_con_prompt(manifiesto_path, pendientes_dir)
                if archivados:
                    logger.info("Entregas pendientes archivadas tras correccion API correcta: %s", archivados)
        return

    corrector = CorrectorIA(
        usar_ia=not args.sin_ia,
        prompts_path=args.prompts,
        requerir_ia=getattr(args, "requerir_openai_api", False),
    )

    resultados: list[dict] = []
    trazas: list[dict] = []

    for actividad_codigo, envios_actividad in sorted(pendientes_por_actividad.items()):
        logger.info(
            f"Corrigiendo lote {actividad_codigo}: {len(envios_actividad)} entrega(s)"
        )
        entregas_automaticas: list[tuple[EnvioPendiente, str]] = []
        correcciones_por_archivo: dict[Path, dict] = {}

        for envio in envios_actividad:
            lectura = salida.leer_entrega(envio.archivo)
            if lectura.requiere_revision_manual:
                correcciones_por_archivo[envio.archivo] = corrector.correccion_revision_manual(lectura.motivo)
                logger.warning(f"Entrega marcada para revisión manual: {envio.archivo} ({lectura.motivo})")
            else:
                if lectura.advertencia:
                    logger.warning("%s: %s", envio.archivo, lectura.advertencia)
                texto_entrega = lectura.texto
                max_chars = getattr(args, "max_caracteres_entrega", 0) or 0
                if max_chars <= 0 and getattr(args, "requerir_openai_api", False):
                    max_chars = 60000
                if max_chars > 0 and len(texto_entrega) > max_chars:
                    texto_entrega = texto_entrega[:max_chars].rstrip()
                    logger.warning(
                        "Entrega recortada para controlar tokens API: %s (%s caracteres)",
                        envio.archivo,
                        max_chars,
                    )
                entregas_automaticas.append((envio, texto_entrega))

        if entregas_automaticas:
            try:
                max_entregas_api = getattr(args, "max_entregas_por_prompt", 0) or 0
                if max_entregas_api <= 0:
                    max_entregas_api = len(entregas_automaticas)
                correcciones = []
                for inicio in range(0, len(entregas_automaticas), max_entregas_api):
                    sublote = entregas_automaticas[inicio:inicio + max_entregas_api]
                    logger.info(
                        "Corrigiendo sublote API %s: %s entrega(s) (%s/%s)",
                        actividad_codigo,
                        len(sublote),
                        inicio + 1,
                        len(entregas_automaticas),
                    )
                    correcciones.extend(
                        corrector.corregir_lote(
                            sublote,
                            contexto_unidad,
                            actividad_codigo,
                        )
                    )
            except Exception as exc:
                logger.error("No se pudo corregir %s con OpenAI API: %s", actividad_codigo, exc)
                return
            for (envio, _), correccion in zip(entregas_automaticas, correcciones):
                correcciones_por_archivo[envio.archivo] = correccion

        for envio in envios_actividad:
            correccion = correcciones_por_archivo.get(
                envio.archivo,
                corrector.correccion_revision_manual("No se generó corrección automática para esta entrega."),
            )
            resultado = salida.escribir_salidas(envio, correccion)
            resultados.append(resultado)
            if not args.conservar_pendientes and resultado["estado"] != "revision_manual_necesaria":
                salida.eliminar_pendiente_calificado(envio)

            trazas.append(
                {
                    "timestamp": __import__("datetime").datetime.now().isoformat(),
                    "alumno": envio.alumno,
                    "actividad_codigo": envio.actividad_codigo,
                    "actividad_nombre": envio.actividad_nombre,
                    "archivo_entrada": str(envio.archivo),
                    "correccion": correccion,
                    "estado": resultado["estado"],
                }
            )

    resumen_path = salida.escribir_resumen(resultados)
    resumenes_actividad = salida.escribir_resumenes_por_actividad(resultados)
    revision_path = salida.escribir_revision_pendiente(resultados)

    traza_path = CORRECCIONES_DIR / "correcciones_lote.json"
    traza_path.write_text(json.dumps(trazas, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info(f"Proceso completado. Resumen generado en: {resumen_path}")
    for resumen_actividad in resumenes_actividad:
        logger.info(f"Resumen por actividad generado en: {resumen_actividad}")
    logger.info(f"Hoja de revisión manual generada en: {revision_path}")
    logger.info(f"Trazabilidad de lote en: {traza_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Corrige ejercicios de pendientes y genera salidas por alumno."
    )
    parser.add_argument(
        "--extraer-carm",
        action="store_true",
        help="Activa extraccion de envios desde CARM antes de corregir.",
    )
    parser.add_argument(
        "--diagnosticar-carm",
        action="store_true",
        help="Entra en CARM, guarda un diagnóstico limpio y sale sin descargar ni corregir.",
    )
    parser.add_argument(
        "--comprobar-login-carm",
        action="store_true",
        help="Comprueba credenciales CARM, guarda sesion recordada y sale.",
    )
    parser.add_argument(
        "--listar-cursos-carm",
        action="store_true",
        help="Lista cursos visibles en CARM y guarda respuestas_extraidas/cursos_detectados.json.",
    )
    parser.add_argument(
        "--guardar-evidencias",
        action="store_true",
        help="Con --diagnosticar-carm, guarda HTML y capturas redactadas. Por defecto no se guardan.",
    )
    parser.add_argument(
        "--incluir-enlaces-diagnostico",
        action="store_true",
        help="Incluye URLs redactadas en diagnostico.json. Por defecto se omiten.",
    )
    parser.add_argument(
        "--solo-listar-carm",
        action="store_true",
        help="Entra en CARM y lista entregas que requieren calificación sin descargar archivos ni corregir.",
    )
    parser.add_argument(
        "--cachear-curso",
        action="store_true",
        help="Recopila recursos estables del curso en cache SQLite local sin descargar entregas.",
    )
    parser.add_argument(
        "--usar-cache",
        action="store_true",
        help="Compatibilidad: la cache ya se usa por defecto salvo que indiques --sin-cache.",
    )
    parser.add_argument(
        "--sin-cache",
        action="store_true",
        help="No lee recursos estables desde cache local en esta ejecución.",
    )
    parser.add_argument(
        "--refrescar-cache",
        action="store_true",
        help="Ignora la lectura de cache y actualiza los recursos estables durante la ejecución.",
    )
    parser.add_argument(
        "--borrar-cache-curso",
        action="store_true",
        help="Borra la cache SQLite local del curso y sale.",
    )
    parser.add_argument(
        "--mantener-navegador",
        action="store_true",
        help="Deja Chromium abierto al terminar hasta pulsar Enter. Útil para revisar CARM en pruebas.",
    )
    parser.add_argument(
        "--pendientes",
        default=str(DEFAULT_PENDIENTES_DIR),
        help="Carpeta de archivos pendientes.",
    )
    parser.add_argument(
        "--temporal",
        default=str(DEFAULT_TEMPORAL_DIR),
        help="Carpeta de salida temporal por alumno.",
    )
    parser.add_argument(
        "--contexto-unidad",
        default="",
        help="Archivo de texto con el manual o contenido imprimible de la unidad.",
    )
    parser.add_argument(
        "--prompts",
        default=str(GestorPrompts.DEFAULT_PROMPTS_PATH),
        help="Archivo JSON con prompts por defecto o por actividad.",
    )
    parser.add_argument(
        "--actividad-codigo",
        default=DEFAULT_ACTIVIDAD_CODIGO,
        help="Nombre base de los archivos generados para la actividad.",
    )
    parser.add_argument(
        "--unidad",
        default="",
        help="Filtra por unidad, por ejemplo ud01 o 1. Acepta varias separadas por coma.",
    )
    parser.add_argument(
        "--actividad",
        default="",
        help="Filtra por actividad concreta, por ejemplo ud01cp01. Acepta varias separadas por coma.",
    )
    parser.add_argument(
        "--sin-ia",
        action="store_true",
        help="Ejecuta el flujo con corrección de respaldo, sin llamar a OpenAI. Útil para probar carpetas y salidas.",
    )
    parser.add_argument(
        "--requerir-openai-api",
        action="store_true",
        help="Falla antes de corregir si OPENAI_API_KEY no esta configurada. Evita usar correcciones de respaldo por accidente.",
    )
    parser.add_argument(
        "--comprobar-openai-api",
        action="store_true",
        help="Comprueba que OPENAI_API_KEY y OPENAI_MODEL estan configurados para el flujo por API.",
    )
    parser.add_argument(
        "--preparar-prompts-codex",
        action="store_true",
        help="Lee o extrae entregas y genera prompts para pegar en Codex/ChatGPT, sin llamar a la API.",
    )
    parser.add_argument(
        "--preparar-carm-codex",
        action="store_true",
        help="Flujo unico: entra en CARM una vez, actualiza cache, registra entregas, descarga archivos y genera prompts Codex sin API.",
    )
    parser.add_argument(
        "--flujo-correccion-carm",
        action="store_true",
        help="Legado: prepara CARM y genera prompts. Ya no llama a Codex CLI; usa $C e importa JSON.",
    )
    parser.add_argument(
        "--corregir-con-codex",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--comprobar-codex-cli",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--importar-tras-codex",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--corregir-prompts-openai",
        action="store_true",
        help="Envia prompts .md ya preparados a OpenAI API, guarda JSON e importa salidas revisables.",
    )
    parser.add_argument(
        "--importar-tras-openai",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Con --corregir-prompts-openai, importa automaticamente el JSON combinado a temporal.",
    )
    parser.add_argument(
        "--openai-output-dir",
        default="",
        help="Carpeta donde guardar las respuestas JSON de OpenAI API. Por defecto pendientes/prompts_codex.",
    )
    parser.add_argument(
        "--openai-warn-tokens-prompt",
        type=int,
        default=OPENAI_PROMPT_TOKEN_WARN,
        help="Aviso si un prompt preparado supera esta estimacion de tokens. 0 desactiva el aviso.",
    )
    parser.add_argument(
        "--openai-max-tokens-prompt",
        type=int,
        default=OPENAI_PROMPT_TOKEN_MAX,
        help="Bloquea el envio API si un prompt preparado supera esta estimacion de tokens. 0 desactiva el bloqueo.",
    )
    parser.add_argument(
        "--codex-output-dir",
        default="",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--codex-timeout",
        type=int,
        default=0,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--importar-correcciones-codex",
        default="",
        help="Importa un JSON de correcciones devuelto por Codex/ChatGPT y genera salidas .txt por alumno.",
    )
    parser.add_argument(
        "--subir-correcciones-carm",
        default="",
        help="Previsualiza en CARM un JSON de correcciones: abre el formulario, rellena nota/feedback y no guarda.",
    )
    parser.add_argument(
        "--subida-asistida-carm",
        action="store_true",
        help="Con --subir-correcciones-carm, rellena cada calificacion y espera a que el usuario pulse guardar.",
    )
    parser.add_argument(
        "--guardar-trace-subida",
        action="store_true",
        help="Con --subida-asistida-carm, guarda un trace Playwright de diagnostico. Puede contener datos personales.",
    )
    parser.add_argument(
        "--solo-primera-previsualizacion-carm",
        action="store_true",
        help="Con --subir-correcciones-carm sin publicar, rellena solo la primera correccion para revisarla con calma.",
    )
    parser.add_argument(
        "--max-entregas-por-prompt",
        type=int,
        default=8,
        help="Divide los prompts de Codex en lotes de este tamaño. Por defecto 8.",
    )
    parser.add_argument(
        "--max-caracteres-entrega",
        type=int,
        default=0,
        help="Recorta cada respuesta a este número de caracteres en prompts Codex. 0 no recorta.",
    )
    parser.add_argument(
        "--conservar-pendientes",
        action="store_true",
        help="No elimina de pendientes los archivos ya copiados y corregidos.",
    )
    parser.add_argument(
        "--purgar-datos-personales-locales",
        action="store_true",
        help="Borra salidas locales con datos personales del flujo de correccion. Requiere --confirmar-purga-datos.",
    )
    parser.add_argument(
        "--confirmar-purga-datos",
        action="store_true",
        help="Confirmacion fuerte para ejecutar --purgar-datos-personales-locales.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    argumentos = parse_args()
    aplicar_retencion_local()
    asyncio.run(ejecutar_flujo(argumentos))
