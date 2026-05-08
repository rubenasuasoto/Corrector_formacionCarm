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
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import datetime
from html import escape as html_escape, unescape
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

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
CARM_MY_URL = "https://formacion.carm.es/my/index.php"
CARM_COURSE_URL = os.getenv("CARM_COURSE_URL", "https://formacion.carm.es/course/view.php?id=1592")
CARM_COURSE_END_DATE = os.getenv("CARM_COURSE_END_DATE", "").strip()
CARM_HEADLESS = os.getenv("CARM_HEADLESS", "0").strip().lower() in {"1", "true", "yes"}
try:
    CARM_NAV_TIMEOUT_MS = int(os.getenv("CARM_NAV_TIMEOUT_MS", "90000"))
except ValueError:
    CARM_NAV_TIMEOUT_MS = 90000

DEFAULT_PENDIENTES_DIR = Path(r"C:\temp\vscodec\pendientes")
DEFAULT_TEMPORAL_DIR = Path(r"C:\temp\vscodec\temporal")
DEFAULT_ACTIVIDAD_CODIGO = "ud01cp01"

LOG_DIR = Path("logs_correcciones")
RESPUESTAS_DIR = Path("respuestas_extraidas")
CORRECCIONES_DIR = Path("correcciones_validadas")
CACHE_DIR = Path("cache_carm")
CARM_RECORDAR_CUENTA = os.getenv("CARM_RECORDAR_CUENTA", "1").strip().lower() not in {"0", "false", "no"}
CARM_STORAGE_STATE = CACHE_DIR / "carm_storage_state.json"
AUDIT_LOG = RESPUESTAS_DIR / "auditoria.jsonl"


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
    texto = re.sub(r"(password|contrasena|contraseña|contraseÃ±a)(=|%3D)[^&\"'>\s]+", r"\1\2[redactado]", texto, flags=re.I)
    texto = re.sub(r"(api[_-]?key|token|authorization|cookie)(\s*[=:]\s*)[^&\"'>\s]+", r"\1\2[redactado]", texto, flags=re.I)
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


def obtener_credenciales_carm_interactivo(motivo: str) -> tuple[str, str] | None:
    usuario = os.getenv("CARM_USUARIO", "").strip()
    contrasena = os.getenv("CARM_CONTRASENA", "").strip()
    if usuario and contrasena:
        return usuario, contrasena
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
    limpio = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", limpio)
    limpio = re.sub(r"</?(script|iframe|object|embed|style|link|meta)[^>]*>", "", limpio, flags=re.I)
    limpio = re.sub(r"\son\w+\s*=\s*(['\"]).*?\1", "", limpio, flags=re.I | re.S)
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


def archivar_prompt_y_correccion_usados(correcciones_path: Path, temporal_dir: Path, modo: str) -> Path:
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

    nombre = correcciones_path.name
    match = re.search(r"(ud\d{2}cp\d{2})", nombre, flags=re.I)
    if match:
        codigo = match.group(1).lower()
        for path in prompts_dir.glob(f"*{codigo}*"):
            if path.is_file() and path.parent != archivo_dir:
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
        with self._conectar() as con:
            con.execute(
                """
                INSERT INTO unidad (course_id, codigo, nombre, contenido_imprimible, actualizado_en)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(course_id, codigo) DO UPDATE SET
                    nombre=COALESCE(NULLIF(excluded.nombre, ''), unidad.nombre),
                    contenido_imprimible=COALESCE(NULLIF(excluded.contenido_imprimible, ''), unidad.contenido_imprimible),
                    actualizado_en=excluded.actualizado_en
                """,
                (self.course_id, codigo, nombre, contenido_imprimible, self._ahora()),
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
            if unidades:
                placeholders = ",".join("?" for _ in unidades)
                rows = con.execute(
                    f"""
                    SELECT codigo, nombre, contenido_imprimible
                    FROM unidad
                    WHERE course_id = ? AND codigo IN ({placeholders})
                    ORDER BY codigo
                    """,
                    (self.course_id, *sorted(unidades)),
                ).fetchall()
            else:
                rows = con.execute(
                    """
                    SELECT codigo, nombre, contenido_imprimible
                    FROM unidad
                    WHERE course_id = ?
                    ORDER BY codigo
                    """,
                    (self.course_id,),
                ).fetchall()
        partes = []
        for codigo, nombre, contenido in rows:
            if contenido:
                partes.append(f"## {codigo.upper()} - {nombre or 'Contenido imprimible'}\n{contenido}")
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
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.modelo = modelo or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
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
            logger.warning("OPENAI_API_KEY o paquete openai no disponible; usando corrección de respaldo")
            return self._correccion_respaldo()

        prompt_cfg = self.prompts.obtener(actividad_codigo)
        prompt_usuario = (
            f"{prompt_cfg['criterios']}\n\n"
            f"ACTIVIDAD: {actividad_codigo}\n\n"
            f"ENUNCIADO EXTRAÍDO DE CARM:\n{enunciado_actividad or 'No disponible'}\n\n"
            f"CONTEXTO DE UNIDAD (Contenido imprimible):\n{contexto_unidad}\n\n"
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
        prompt_usuario = (
            f"{prompt_cfg['criterios']}\n\n"
            f"ACTIVIDAD: {actividad_codigo}\n\n"
            f"ENUNCIADO EXTRAÍDO DE CARM:\n{enunciado_actividad or 'No disponible'}\n\n"
            f"CONTEXTO DE UNIDAD (Contenido imprimible):\n{contexto_unidad}\n\n"
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

    @staticmethod
    def _sanitizar_nombre(nombre: str) -> str:
        limpio = re.sub(r"[\\/:*?\"<>|]", "_", nombre.strip())
        return re.sub(r"\s+", " ", limpio)[:120] or "alumno"

    @staticmethod
    def _texto_limpio(texto: str) -> str:
        return re.sub(r"\s+", " ", (texto or "")).strip()

    @staticmethod
    def _normalizar_codigo_unidad(valor: str) -> str:
        texto = (valor or "").strip().lower()
        m = re.search(r"(?:ud|unidad)?\s*0*(\d{1,2})", texto)
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
            r"\bcaso\s+practico\b.*?\b0*(\d{1,2})\b",
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
                await page.goto(href, wait_until="domcontentloaded")
                body = await page.text_content("body")
                if body and body.strip():
                    contexto_partes.append(body.strip())
                    if self.cache and unidad_codigo:
                        self.cache.guardar_unidad(
                            unidad_codigo,
                            nombre=nombre,
                            contenido_imprimible=body.strip(),
                        )
            except Exception as e:
                logger.warning(f"No se pudo leer contenido imprimible {href}: {e}")
        await page.goto(CARM_COURSE_URL, wait_until="domcontentloaded")
        return "\n\n".join(contexto_partes)

    async def _extraer_enunciado_actividad(self, page, actividad_url: str) -> str:
        try:
            await page.goto(self._url_vista_actividad(actividad_url), wait_until="networkidle")
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
                texto = await page.locator(selector).first.text_content(timeout=1500)
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
            unidad = await self._obtener_nombre_unidad(enlace_actividad)
            codigo = self._inferir_codigo_actividad(nombre, unidad)
            if not self._actividad_permitida(codigo, self.unidades, self.actividades):
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

    async def _buscar_url_calificador(self, page, actividad: dict, alumno: str) -> str:
        actividad["url_grading"] = self._url_grading_requiere_calificacion(actividad["url_grading"])
        await page.goto(actividad["url_grading"], wait_until="domcontentloaded")
        await self._asegurar_filtros_grading(page, actividad)
        alumno_norm = self._normalizar(alumno)
        filas = await page.query_selector_all("table.generaltable tbody tr")
        for fila in filas:
            texto_fila = self._normalizar(await fila.text_content() or "")
            if alumno_norm not in texto_fila:
                continue
            enlace = await fila.query_selector("a[href*='action=grader'][href*='userid=']")
            if enlace is None:
                enlace = await fila.query_selector("a[href*='action=grader']")
            if enlace is None:
                continue
            href = await enlace.get_attribute("href")
            if href:
                return href
        return ""

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
                    const parent = `${el.closest('[id], [class]')?.id || ''} ${el.closest('[id], [class]')?.className || ''}`.toLowerCase();
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
                        || textarea.closest('.fitem, .form-group, .felement')?.querySelector('[contenteditable="true"], .editor_atto_content');
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
        selectores_siguiente = (
            "#id_saveandshownext",
            "button[name='saveandshownext']",
            "input[name='saveandshownext']",
            "button:has-text('Guardar cambios y mostrar siguiente')",
            "input[value='Guardar cambios y mostrar siguiente']",
            "button:has-text('Guardar y mostrar siguiente')",
            "input[value='Guardar y mostrar siguiente']",
        )
        selectores_guardar = (
            "#id_savegrade",
            "button[name='savechanges']",
            "input[name='savechanges']",
            "button:has-text('Guardar cambios')",
            "input[value='Guardar cambios']",
            "button:has-text('Guardar')",
            "input[value='Guardar']",
        )

        selectores = selectores_siguiente + selectores_guardar if mostrar_siguiente else selectores_guardar
        for selector in selectores:
            locator = page.locator(selector).first
            try:
                if await locator.count():
                    await locator.click()
                    await page.wait_for_load_state("networkidle")
                    return selector
            except Exception:
                continue
        raise RuntimeError("No se encontrÃ³ botÃ³n de guardado en el formulario de calificaciÃ³n.")

    @staticmethod
    async def _mostrar_guia_subida_asistida(page, indice: int, total: int, actividad_codigo: str, alumno: str, usar_siguiente: bool) -> None:
        boton = "Guardar cambios y mostrar siguiente" if usar_siguiente else "Guardar cambios"
        mensaje = (
            f"Revision humana {indice}/{total} - {actividad_codigo.upper()} - "
            f"{pseudonimo(alumno)}. Revisa nota y feedback. Pulsa: {boton}."
        )
        await page.evaluate(
            """(message) => {
                const previous = document.getElementById('corrector-carm-assisted-banner');
                if (previous) previous.remove();
                const banner = document.createElement('div');
                banner.id = 'corrector-carm-assisted-banner';
                banner.textContent = message;
                banner.style.position = 'fixed';
                banner.style.left = '16px';
                banner.style.right = '16px';
                banner.style.bottom = '16px';
                banner.style.zIndex = '2147483647';
                banner.style.padding = '12px 14px';
                banner.style.background = '#fff8ea';
                banner.style.border = '1px solid #d6a84f';
                banner.style.color = '#3f2a00';
                banner.style.font = '600 14px Segoe UI, Arial, sans-serif';
                banner.style.boxShadow = '0 8px 28px rgba(0,0,0,.18)';
                banner.style.borderRadius = '8px';
                document.body.appendChild(banner);
            }""",
            mensaje,
        )

    @staticmethod
    async def _esperar_guardado_manual(page) -> None:
        url_inicial = page.url
        await page.wait_for_url(lambda url: url != url_inicial, timeout=0)
        await page.wait_for_load_state("networkidle")

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

        url_calificador = await self._buscar_url_calificador(page, actividad, alumno)
        if not url_calificador:
            return {
                "alumno": alumno,
                "actividad": actividad_codigo,
                "estado": "no_encontrado",
                "mensaje": "No se encontrÃ³ enlace de calificaciÃ³n para el alumno en la tabla.",
            }

        await page.goto(url_calificador, wait_until="networkidle")
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
            "campo_nota": grade_selector,
            "campo_feedback": feedback_selector,
            "diagnostico_feedback": await self._diagnosticar_campos_feedback(page),
            "guardar_y_mostrar_siguiente": bool(mostrar_siguiente),
            "estado": "previsualizado",
        }

        if not grade_selector:
            resultado["estado"] = "error"
            resultado["mensaje"] = "No se encontrÃ³ campo de nota."
            return resultado
        if not feedback_selector:
            resultado["estado"] = "error"
            resultado["mensaje"] = "No se encontrÃ³ campo de retroalimentaciÃ³n."
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
            resultado["boton_recomendado"] = (
                "guardar_cambios_y_mostrar_siguiente" if mostrar_siguiente else "guardar_cambios"
            )
            await self._esperar_guardado_manual(page)
            resultado["estado"] = "guardado_manual_por_usuario"

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
            browser = await p.chromium.launch(headless=False if asistida else CARM_HEADLESS)
            context = await self._crear_contexto(browser)
            page = await context.new_page()
            self._configurar_page(page)
            resultados: list[dict] = []
            try:
                await self._login(page)
                await page.goto(CARM_COURSE_URL, wait_until="domcontentloaded")
                actividades = await self._obtener_actividades_obligatorias(page)
                actividades_por_codigo = {act["codigo"]: act for act in actividades}
                if self.cache:
                    for codigo, act in list(actividades_por_codigo.items()):
                        actividades_por_codigo[codigo] = self.cache.enriquecer_actividad(act)

                correcciones_a_procesar = correcciones
                if solo_primera_previsualizacion and not publicar and not asistida:
                    correcciones_a_procesar = correcciones[:1]

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
                    mostrar_siguiente = (publicar or asistida) and bool(siguiente_codigo) and siguiente_codigo == actividad_codigo
                    actividad = actividades_por_codigo.get(actividad_codigo)
                    if not actividad:
                        resultados.append(
                            {
                                "alumno": correccion.get("alumno", ""),
                                "actividad": actividad_codigo,
                                "estado": "no_encontrado",
                                "mensaje": "No se encontrÃ³ la actividad en CARM.",
                            }
                        )
                        continue

                    resultados.append(
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

                return resultados
            finally:
                if self.mantener_navegador:
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
                contexto = await self._extraer_contexto_imprimible(page)

                logger.info(f"Actividades prioritarias encontradas: {len(actividades)}")

                todos_envios: list[EnvioPendiente] = []
                for act in actividades:
                    logger.info(f"Procesando grading {act['codigo']}: {act['nombre']}")
                    if self.usar_cache and self.cache:
                        act = self.cache.enriquecer_actividad(act)
                    if not act.get("enunciado"):
                        act["enunciado"] = await self._extraer_enunciado_actividad(page, act["url"])
                    if self.cache:
                        self.cache.guardar_actividad(act)
                    envios = await self._descargar_envios_actividad(page, act, descargar=not solo_listar)
                    todos_envios.extend(envios)

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
                await page.goto(CARM_COURSE_URL, wait_until="domcontentloaded")
                if await page.locator("input[name='username'], #username").count():
                    raise RuntimeError("CARM volvió a mostrar el formulario de login.")
                logger.info("Credenciales CARM verificadas correctamente.")
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
            if ext in self.EXTENSIONES_TEXTO or not ext:
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
            return LecturaEntrega("", False, "El archivo está vacío o no contiene texto legible.")

        return LecturaEntrega(texto)

    def _validar_archivo_entrega(self, path: Path, ext: str) -> str:
        try:
            size = path.stat().st_size
        except OSError:
            return "No se pudo leer el tamaÃ±o del archivo; requiere revisiÃ³n manual."
        if size > self.MAX_ARCHIVO_BYTES:
            return (
                f"Archivo demasiado grande ({size} bytes, limite {self.MAX_ARCHIVO_BYTES}); "
                "requiere revisiÃ³n manual."
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
            return f"Extension no permitida ({ext or 'sin extensiÃ³n'}); requiere revisiÃ³n manual."
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
        texto = re.sub(r"\\[a-zA-Z]+\d* ?", " ", texto)
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
                    textos.append(f"[{info.filename}: omitido por tamaÃ±o excesivo]")
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
        limpio = re.sub(r"[\\/:*?\"<>|]", "_", nombre.strip())
        return re.sub(r"\s+", " ", limpio)[:120] or "alumno"

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
            m = crit.get("maximo", "?")
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
        normalizada["nota"] = float(normalizada.get("nota", 0) or 0)
        return normalizada

    def _leer_correcciones_codex(self, correcciones_path: Path) -> list[dict]:
        texto = self._leer_archivo_texto(correcciones_path).strip()
        if not texto:
            raise ValueError(f"No se pudo leer el archivo de correcciones: {correcciones_path}")

        match = re.search(r"```(?:json)?\s*(.*?)```", texto, flags=re.S | re.I)
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
        manifiesto_path = self.temporal_dir / "prompts_codex" / "manifiesto_entregas.json"
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

        lineas = ["alumno;actividad;nota;estado;retroalimentacion;archivo_correccion"]
        for r in resultados:
            feedback = str(r["retroalimentacion"]).replace("\n", " ").replace(";", ",")
            lineas.append(
                f"{r['alumno']};{r['actividad']};{r['nota']};{r['estado']};{feedback};{r['archivo_correccion']}"
            )

        revision_path.write_text("\n".join(lineas), encoding="utf-8-sig")
        return revision_path

    def escribir_prompts_codex(
        self,
        pendientes_por_actividad: dict[str, list[EnvioPendiente]],
        contexto_unidad: str,
        prompts_path: str | Path | None = None,
        max_entregas_por_prompt: int = 8,
        max_caracteres_entrega: int = 0,
    ) -> list[Path]:
        prompts_dir = self.temporal_dir / "prompts_codex"
        prompts_dir.mkdir(parents=True, exist_ok=True)

        gestor_prompts = GestorPrompts(prompts_path)
        rutas: list[Path] = []
        manifiesto: list[dict] = []

        for actividad_codigo, envios in sorted(pendientes_por_actividad.items()):
            entregas: list[dict] = []
            revision_manual: list[dict] = []
            enunciado = next((e.actividad_enunciado for e in envios if e.actividad_enunciado), "")

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
                prompt_path = prompts_dir / f"prompt_{actividad_codigo}{sufijo_lote}.md"
                lineas = [
                f"# Prompt para Codex - {actividad_codigo}",
                "",
                f"Lote {numero_lote} de {len(lotes)}. Entregas en este lote: {len(entregas_lote)}.",
                "",
                "Copia todo este archivo en Codex/ChatGPT y pide la corrección.",
                "No hace falta usar la API de OpenAI para este paso.",
                "",
                "## Instrucciones de sistema",
                "",
                prompt_cfg["sistema"],
                "",
                "## Rúbrica y enunciado",
                "",
                prompt_cfg["criterios"],
                "",
                "## Enunciado extraído de CARM",
                "",
                enunciado or "No se pudo extraer un enunciado específico de CARM para esta actividad.",
                "",
                "## Contexto de unidad",
                "",
                contexto_unidad,
                "",
                "## Tarea",
                "",
                "Corrige todas las entregas legibles. Evalúa solo lo que el alumno ha escrito, sin inventar méritos.",
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
        manifiesto_path.write_text(
            json.dumps(manifiesto, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        rutas.append(manifiesto_path)
        return rutas

    def corregir_prompts_con_codex(
        self,
        rutas_prompts: list[Path],
        output_dir: Path | None = None,
        importar: bool = False,
        timeout_segundos: int = 0,
    ) -> tuple[list[Path], Path | None]:
        prompts = [
            ruta for ruta in rutas_prompts
            if ruta.suffix.lower() == ".md" and ruta.name.startswith("prompt_")
        ]
        if not prompts:
            raise ValueError("No hay prompts .md para enviar a Codex.")

        output_dir = output_dir or (self.temporal_dir / "prompts_codex")
        output_dir.mkdir(parents=True, exist_ok=True)
        for viejo in output_dir.glob("*_correccion.json"):
            archivo_dir = output_dir / "archivados" / datetime.now().strftime("%Y%m%d_%H%M%S_pre_codex")
            moved = _mover_si_existe(viejo, archivo_dir)
            if moved:
                logger.info("Correccion Codex anterior archivada antes de generar nueva salida: %s", moved)

        rutas_correcciones: list[Path] = []
        timeout = timeout_segundos if timeout_segundos and timeout_segundos > 0 else None
        for prompt_path in prompts:
            salida_path = output_dir / f"{prompt_path.stem}_correccion.json"
            prompt_texto = normalizar_texto_para_cli(prompt_path.read_text(encoding="utf-8"))
            instruccion = normalizar_texto_para_cli(
                f"{prompt_texto}\n\n"
                "IMPORTANTE: responde solo con JSON valido, sin markdown, sin explicaciones fuera del JSON. "
                "Usa una lista JSON de correcciones."
            )
            logger.info(f"Enviando prompt a Codex CLI: {prompt_path}")
            try:
                env_codex = os.environ.copy()
                env_codex.update(
                    {
                        "PYTHONIOENCODING": "utf-8",
                        "PYTHONUTF8": "1",
                        "LC_ALL": "C.UTF-8",
                        "LANG": "C.UTF-8",
                    }
                )
                resultado = subprocess.run(
                    [
                        "codex",
                        "exec",
                        "-C",
                        str(Path.cwd()),
                        "-s",
                        "read-only",
                        "--output-last-message",
                        str(salida_path),
                        "-",
                    ],
                    input=instruccion,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    timeout=timeout,
                    check=False,
                    env=env_codex,
                )
            except FileNotFoundError as e:
                raise RuntimeError("No se encontro el comando 'codex'. Abre Codex/VS Code o revisa PATH.") from e

            if resultado.returncode != 0:
                stderr = (resultado.stderr or resultado.stdout or "").strip()
                raise RuntimeError(f"Codex CLI fallo con {prompt_path.name}: {stderr[:2000]}")
            if not salida_path.exists() or not salida_path.read_text(encoding="utf-8").strip():
                salida_path.write_text(resultado.stdout or "", encoding="utf-8")
            rutas_correcciones.append(salida_path)
            logger.info(f"Correccion Codex guardada en: {salida_path}")

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

        return rutas_correcciones, revision_path


async def ejecutar_flujo(args) -> None:
    pendientes_dir = Path(args.pendientes)
    temporal_dir = Path(args.temporal)
    flujo_correccion_carm = getattr(args, "flujo_correccion_carm", False)
    if flujo_correccion_carm:
        args.preparar_carm_codex = True
        args.corregir_con_codex = True
        args.importar_tras_codex = True
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

    if getattr(args, "importar_correcciones_codex", ""):
        salida = GeneradorSalidas(pendientes_dir, temporal_dir, actividad_codigo=args.actividad_codigo)
        correcciones_path = Path(args.importar_correcciones_codex)
        try:
            resultados, revision_path, rutas_extra = salida.importar_correcciones_codex(correcciones_path)
        except Exception as e:
            logger.error(f"No se pudieron importar correcciones Codex: {e}")
            return

        logger.info(f"Correcciones importadas: {len(resultados)}")
        for ruta in rutas_extra:
            logger.info(f"- {ruta}")
        logger.info(f"Hoja de revisión manual generada en: {revision_path}")
        registrar_auditoria(
            "importar_correcciones_codex",
            correcciones=len(resultados),
            origen=correcciones_path,
            revision=revision_path,
        )
        return

    if getattr(args, "subir_correcciones_carm", ""):
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
        asistida = getattr(args, "subida_asistida_carm", False)
        extractor = ExtractorCarm(
            usuario,
            contrasena,
            pendientes_dir,
            mantener_navegador=getattr(args, "mantener_navegador", False),
            guardar_evidencias=getattr(args, "guardar_evidencias", False),
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
            "subida_carm_publicada.json" if publicar else (
                "subida_carm_asistida.json" if asistida else "subida_carm_previsualizacion.json"
            )
        )
        salida_path.write_text(
            json.dumps(resultados_subida, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        registrar_auditoria(
            "publicar_carm" if publicar else ("subida_asistida_carm" if asistida else "previsualizar_subida_carm"),
            correcciones=len(correcciones),
            resultados=len(resultados_subida),
            salida=salida_path,
        )
        for resultado in resultados_subida:
            logger.info(
                "%s %s %s: %s",
                resultado.get("actividad", ""),
                pseudonimo(resultado.get("alumno", "")),
                resultado.get("nota", ""),
                resultado.get("estado", ""),
            )
        logger.info(f"Registro de subida CARM generado en: {salida_path}")
        if publicar or asistida:
            archivar_prompt_y_correccion_usados(
                correcciones_path=correcciones_path,
                temporal_dir=temporal_dir,
                modo="publicada" if publicar else "asistida",
            )
        if not publicar:
            logger.info("Modo previsualizaciÃ³n: no se ha pulsado guardar en CARM.")
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
        if not getattr(args, "conservar_pendientes", False):
            manifiesto_path = temporal_dir / "prompts_codex" / "manifiesto_entregas.json"
            archivados = archivar_pendientes_con_prompt(manifiesto_path, pendientes_dir)
            if archivados:
                logger.info("Entregas pendientes archivadas tras generar prompt: %s", archivados)
        if getattr(args, "corregir_con_codex", False):
            try:
                rutas_correcciones, revision_path = salida.corregir_prompts_con_codex(
                    rutas_prompts,
                    output_dir=Path(args.codex_output_dir) if getattr(args, "codex_output_dir", "") else None,
                    importar=getattr(args, "importar_tras_codex", False),
                    timeout_segundos=getattr(args, "codex_timeout", 0),
                )
            except Exception as e:
                logger.error(f"No se pudo corregir con Codex CLI: {e}")
                return
            logger.info("Correcciones generadas por Codex CLI:")
            for ruta in rutas_correcciones:
                logger.info(f"- {ruta}")
            if revision_path:
                logger.info(f"Correcciones importadas. Hoja de revision: {revision_path}")
        return

    corrector = CorrectorIA(usar_ia=not args.sin_ia, prompts_path=args.prompts)

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
                entregas_automaticas.append((envio, lectura.texto))

        if entregas_automaticas:
            correcciones = corrector.corregir_lote(
                entregas_automaticas,
                contexto_unidad,
                actividad_codigo,
            )
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
        help="Atajo recomendado: prepara CARM, genera prompts, corrige con Codex CLI e importa salidas sin publicar en CARM.",
    )
    parser.add_argument(
        "--corregir-con-codex",
        action="store_true",
        help="Tras generar prompts, los envia a Codex CLI con codex exec y guarda las correcciones JSON.",
    )
    parser.add_argument(
        "--importar-tras-codex",
        action="store_true",
        help="Con --corregir-con-codex, importa automaticamente el JSON combinado a temporal.",
    )
    parser.add_argument(
        "--codex-output-dir",
        default="",
        help="Carpeta donde guardar las respuestas JSON de Codex CLI. Por defecto temporal/prompts_codex.",
    )
    parser.add_argument(
        "--codex-timeout",
        type=int,
        default=0,
        help="Tiempo maximo por prompt al llamar a Codex CLI, en segundos. 0 sin limite.",
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
        "--publicar-carm",
        action="store_true",
        help="Con --subir-correcciones-carm, pulsa guardar y publica la calificaciÃ³n en CARM.",
    )
    parser.add_argument(
        "--subida-asistida-carm",
        action="store_true",
        help="Con --subir-correcciones-carm, rellena cada calificacion y espera a que el usuario pulse guardar.",
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
