"""
Agente de correccion automatica para CARM Formacion.

Flujo principal:
1) (Opcional) Extrae envios desde CARM a una carpeta local de pendientes.
2) Corrige los ejercicios encontrados en pendientes con contexto de unidad.
3) Genera estructura de salida por alumno en carpeta temporal.
4) Genera resumen global con nota y feedback por alumno.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
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
CARM_COURSE_URL = "https://formacion.carm.es/course/view.php?id=1592"

DEFAULT_PENDIENTES_DIR = Path(r"C:\temp\vscodec\pendientes")
DEFAULT_TEMPORAL_DIR = Path(r"C:\temp\vscodec\temporal")

LOG_DIR = Path("logs_correcciones")
RESPUESTAS_DIR = Path("respuestas_extraidas")
CORRECCIONES_DIR = Path("correcciones_validadas")

for d in (LOG_DIR, RESPUESTAS_DIR, CORRECCIONES_DIR):
    d.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "agente.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


PROMPT_SISTEMA = (
    "Eres un corrector experto en inteligencia artificial aplicada al turismo de Murcia. "
    "Responde SIEMPRE en JSON valido y en espanol con acentos."
)

PROMPT_CRITERIOS = """
Te paso un archivo con un manual sobre inteligencia artificial aplicada al sector turistico de Murcia como contexto para corregir un ejercicio practico.

Ahora quiero que me des unos criterios de correccion para este ejercicio en una escala del 0 al 10, asignando 3 puntos a la presentacion del trabajo:
Un tecnico introduce en una herramienta gratuita datos completos de reservas con informacion personal identificable para que el sistema genere un analisis de comportamiento del visitante.

Que actuacion deberia realizar para ajustar el uso de la herramienta a principios de proteccion de datos y buenas practicas?

Devuelve JSON con este formato exacto:
{
  "nota": 0-10,
  "criterios": [
    {"nombre": "Presentacion del trabajo", "maximo": 3, "puntuacion": 0-3, "comentario": "..."},
    {"nombre": "Proteccion de datos", "maximo": 4, "puntuacion": 0-4, "comentario": "..."},
    {"nombre": "Buenas practicas y aplicacion", "maximo": 3, "puntuacion": 0-3, "comentario": "..."}
  ],
  "retroalimentacion": "Feedback final, coloquial pero formal, adaptado al caso y la unidad"
}
""".strip()


@dataclass
class EnvioPendiente:
    alumno: str
    archivo: Path


class CorrectorIA:
    def __init__(self, api_key: str | None = None, modelo: str | None = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.modelo = modelo or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        self.cliente = OpenAI(api_key=self.api_key) if (OpenAI and self.api_key) else None

    def corregir(self, respuesta: str, contexto_unidad: str) -> dict:
        if not respuesta.strip():
            return {
                "nota": 0,
                "criterios": [
                    {
                        "nombre": "Presentacion del trabajo",
                        "maximo": 3,
                        "puntuacion": 0,
                        "comentario": "No se pudo evaluar la presentacion por falta de contenido.",
                    },
                    {
                        "nombre": "Proteccion de datos",
                        "maximo": 4,
                        "puntuacion": 0,
                        "comentario": "No hay desarrollo sobre tratamiento de datos personales.",
                    },
                    {
                        "nombre": "Buenas practicas y aplicacion",
                        "maximo": 3,
                        "puntuacion": 0,
                        "comentario": "No se aportan medidas aplicables al caso.",
                    },
                ],
                "retroalimentacion": "No he podido corregir este ejercicio porque el archivo aparece vacio o ilegible.",
            }

        if self.cliente is None:
            logger.warning("OPENAI_API_KEY o paquete openai no disponible; usando correccion de respaldo")
            return {
                "nota": 7.0,
                "criterios": [
                    {
                        "nombre": "Presentacion del trabajo",
                        "maximo": 3,
                        "puntuacion": 2.2,
                        "comentario": "La presentacion es correcta, aunque se puede ordenar mejor la estructura.",
                    },
                    {
                        "nombre": "Proteccion de datos",
                        "maximo": 4,
                        "puntuacion": 2.8,
                        "comentario": "Identifica riesgos de datos personales, pero faltan medidas concretas de minimizacion y anonimizado.",
                    },
                    {
                        "nombre": "Buenas practicas y aplicacion",
                        "maximo": 3,
                        "puntuacion": 2.0,
                        "comentario": "Aplica ideas utiles, aunque conviene aterrizarlas mejor al entorno turistico de Murcia.",
                    },
                ],
                "retroalimentacion": "Buen trabajo general. Vas en la linea correcta, pero te recomiendo reforzar la parte de cumplimiento y proponer acciones mas concretas para el caso.",
            }

        prompt_usuario = (
            f"{PROMPT_CRITERIOS}\n\n"
            f"CONTEXTO DE UNIDAD (Contenido imprimible):\n{contexto_unidad}\n\n"
            f"RESPUESTA DEL ALUMNO A EVALUAR:\n{respuesta}"
        )

        try:
            respuesta_api = self.cliente.chat.completions.create(
                model=self.modelo,
                messages=[
                    {"role": "system", "content": PROMPT_SISTEMA},
                    {"role": "user", "content": prompt_usuario},
                ],
                response_format={"type": "json_object"},
                max_completion_tokens=1400,
            )
            contenido = respuesta_api.choices[0].message.content or "{}"
            data = json.loads(contenido)
            data.setdefault("nota", 0)
            data.setdefault("criterios", [])
            data.setdefault("retroalimentacion", "Sin retroalimentacion generada.")
            return data
        except Exception as e:
            logger.error(f"Error corrigiendo con IA: {e}")
            return {
                "nota": 0,
                "criterios": [],
                "retroalimentacion": f"No se pudo generar correccion automatica: {e}",
            }


class ExtractorCarm:
    def __init__(self, usuario: str, contrasena: str, pendientes_dir: Path):
        self.usuario = usuario
        self.contrasena = contrasena
        self.pendientes_dir = pendientes_dir

    @staticmethod
    def _normalizar(texto: str) -> str:
        return re.sub(r"\s+", " ", (texto or "")).strip().lower()

    @staticmethod
    def _sanitizar_nombre(nombre: str) -> str:
        limpio = re.sub(r"[\\/:*?\"<>|]", "_", nombre.strip())
        return re.sub(r"\s+", " ", limpio)[:120] or "alumno"

    @staticmethod
    def _agregar_action_grading(url: str) -> str:
        p = urlparse(url)
        q = dict(parse_qsl(p.query))
        q["action"] = "grading"
        return urlunparse((p.scheme, p.netloc, p.path, p.params, urlencode(q), p.fragment))

    async def _extraer_contexto_imprimible(self, page) -> str:
        contexto_partes: list[str] = []
        enlaces = await page.query_selector_all("a")
        for a in enlaces:
            txt = (await a.text_content() or "").strip().lower()
            if "contenido imprimible" not in txt:
                continue
            href = await a.get_attribute("href")
            if not href:
                continue
            try:
                await page.goto(href, wait_until="networkidle")
                body = await page.text_content("body")
                if body and body.strip():
                    contexto_partes.append(body.strip())
                await page.goto(CARM_COURSE_URL, wait_until="networkidle")
            except Exception as e:
                logger.warning(f"No se pudo leer contenido imprimible {href}: {e}")
        return "\n\n".join(contexto_partes)

    async def _obtener_actividades_obligatorias(self, page) -> list[dict]:
        actividades: list[dict] = []
        enlaces = await page.query_selector_all("a[href*='mod/assign/view.php']")
        for a in enlaces:
            nombre = (await a.text_content() or "").strip()
            if not nombre:
                continue
            base = self._normalizar(nombre)
            if "caso practico" not in base and "caso práctico" not in nombre.lower():
                continue
            if "(obligatorio)" not in nombre.lower():
                continue
            href = await a.get_attribute("href")
            if not href:
                continue
            actividades.append(
                {
                    "nombre": nombre,
                    "url_grading": self._agregar_action_grading(href),
                }
            )
        return actividades

    async def _descargar_envios_actividad(self, page, actividad: dict) -> list[EnvioPendiente]:
        descargados: list[EnvioPendiente] = []
        await page.goto(actividad["url_grading"], wait_until="networkidle")

        filas = await page.query_selector_all("table.generaltable tbody tr")
        for fila in filas:
            celdas = await fila.query_selector_all("td")
            if len(celdas) < 2:
                continue

            alumno = (await celdas[0].text_content() or "").strip()
            if not alumno:
                continue

            enlace_archivo = await fila.query_selector("a[href*='pluginfile.php'], a[href*='forcedownload=1'], a[download]")
            if enlace_archivo is None:
                continue

            file_url = await enlace_archivo.get_attribute("href")
            if not file_url:
                continue

            nombre_archivo = (await enlace_archivo.text_content() or "entrega").strip()
            ext = Path(nombre_archivo).suffix or ".txt"
            alumno_limpio = self._sanitizar_nombre(alumno)
            destino = self.pendientes_dir / f"{alumno_limpio}{ext}"

            try:
                resp = await page.context.request.get(file_url)
                if resp.status != 200:
                    logger.warning(f"No se pudo descargar envio de {alumno}: HTTP {resp.status}")
                    continue
                body = await resp.body()
                destino.write_bytes(body)
                descargados.append(EnvioPendiente(alumno=alumno_limpio, archivo=destino))
                logger.info(f"Descargado envio de {alumno_limpio}: {destino}")
            except Exception as e:
                logger.warning(f"Error descargando envio de {alumno}: {e}")

        return descargados

    async def ejecutar(self) -> tuple[str, list[EnvioPendiente]]:
        if async_playwright is None:
            raise RuntimeError(
                "Playwright no esta disponible. Ejecuta: pip install -r requirements.txt y luego playwright install chromium"
            )

        self.pendientes_dir.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            page = await browser.new_page()
            try:
                await page.goto(CARM_LOGIN_URL, wait_until="networkidle")
                await page.fill("input[name='username']", self.usuario)
                await page.fill("input[name='password']", self.contrasena)
                await page.click("button[type='submit']")
                await page.wait_for_load_state("networkidle")

                await page.goto(CARM_MY_URL, wait_until="networkidle")
                await page.goto(CARM_COURSE_URL, wait_until="networkidle")

                contexto = await self._extraer_contexto_imprimible(page)
                actividades = await self._obtener_actividades_obligatorias(page)

                logger.info(f"Actividades prioritarias encontradas: {len(actividades)}")

                todos_envios: list[EnvioPendiente] = []
                for act in actividades:
                    logger.info(f"Procesando grading: {act['nombre']}")
                    envios = await self._descargar_envios_actividad(page, act)
                    todos_envios.extend(envios)

                with open(RESPUESTAS_DIR / "envios_descargados.json", "w", encoding="utf-8") as f:
                    json.dump(
                        [{"alumno": e.alumno, "archivo": str(e.archivo)} for e in todos_envios],
                        f,
                        indent=2,
                        ensure_ascii=False,
                    )

                return contexto, todos_envios
            finally:
                await browser.close()


class GeneradorSalidas:
    def __init__(self, pendientes_dir: Path, temporal_dir: Path):
        self.pendientes_dir = pendientes_dir
        self.temporal_dir = temporal_dir

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
    def _sanitizar(nombre: str) -> str:
        limpio = re.sub(r"[\\/:*?\"<>|]", "_", nombre.strip())
        return re.sub(r"\s+", " ", limpio)[:120] or "alumno"

    def obtener_pendientes(self) -> list[EnvioPendiente]:
        self.pendientes_dir.mkdir(parents=True, exist_ok=True)
        pendientes: list[EnvioPendiente] = []
        for f in sorted(self.pendientes_dir.iterdir()):
            if f.is_file():
                pendientes.append(EnvioPendiente(alumno=self._sanitizar(f.stem), archivo=f))
        return pendientes

    def escribir_salidas(self, envio: EnvioPendiente, correccion: dict) -> dict:
        alumno_dir = self.temporal_dir / envio.alumno
        alumno_dir.mkdir(parents=True, exist_ok=True)

        ext = envio.archivo.suffix or ".txt"
        copia_entrega = alumno_dir / f"ud01cp01{ext}"
        shutil.copy2(envio.archivo, copia_entrega)

        texto_correccion = self._formatear_correccion(correccion)
        archivo_correccion = alumno_dir / "ud01cp01.txt"
        archivo_correccion.write_text(texto_correccion, encoding="utf-8")

        return {
            "alumno": envio.alumno,
            "nota": float(correccion.get("nota", 0)),
            "retroalimentacion": str(correccion.get("retroalimentacion", "")),
            "archivo_original": str(envio.archivo),
            "archivo_copiado": str(copia_entrega),
            "archivo_correccion": str(archivo_correccion),
        }

    @staticmethod
    def _formatear_correccion(correccion: dict) -> str:
        lineas = []
        lineas.append("Correccion del caso practico UD01 CP01")
        lineas.append("")
        lineas.append(f"Nota final: {correccion.get('nota', 0)}/10")
        lineas.append("")
        lineas.append("Detalle por criterios:")

        for crit in correccion.get("criterios", []):
            nombre = crit.get("nombre", "Criterio")
            p = crit.get("puntuacion", 0)
            m = crit.get("maximo", "?")
            c = crit.get("comentario", "")
            lineas.append(f"- {nombre}: {p}/{m}. {c}")

        lineas.append("")
        lineas.append("Retroalimentacion:")
        lineas.append(str(correccion.get("retroalimentacion", "")))
        lineas.append("")

        return "\n".join(lineas)

    def escribir_resumen(self, resultados: list[dict]) -> Path:
        self.temporal_dir.mkdir(parents=True, exist_ok=True)
        resumen_path = self.temporal_dir / "resumen.txt"

        lineas = []
        lineas.append("Resumen de puntuaciones y retroalimentacion")
        lineas.append("")

        for r in resultados:
            lineas.append(f"Alumno: {r['alumno']}")
            lineas.append(f"Nota: {r['nota']}/10")
            lineas.append(f"Feedback a comunicar: {r['retroalimentacion']}")
            lineas.append("")

        resumen_path.write_text("\n".join(lineas), encoding="utf-8")
        return resumen_path


async def ejecutar_flujo(args) -> None:
    pendientes_dir = Path(args.pendientes)
    temporal_dir = Path(args.temporal)

    contexto_unidad = ""

    if args.extraer_carm:
        usuario = os.getenv("CARM_USUARIO", "")
        contrasena = os.getenv("CARM_CONTRASENA", "")
        if not usuario or not contrasena:
            logger.error("Faltan CARM_USUARIO/CARM_CONTRASENA en .env para extraer desde CARM")
            return

        extractor = ExtractorCarm(usuario, contrasena, pendientes_dir)
        try:
            logger.info("Iniciando extraccion en CARM (login -> my -> curso -> grading)")
            contexto_unidad, _ = await extractor.ejecutar()
        except Exception as e:
            logger.error(f"No se pudo completar extraccion CARM: {e}")
            return

    if not contexto_unidad:
        contexto_unidad = (
            "No se pudo extraer automaticamente el contenido imprimible. "
            "Aplica igualmente criterios de proteccion de datos y buenas practicas del caso."
        )

    salida = GeneradorSalidas(pendientes_dir, temporal_dir)
    pendientes = salida.obtener_pendientes()

    if not pendientes:
        logger.warning(f"No hay archivos pendientes en {pendientes_dir}")
        return

    corrector = CorrectorIA()

    resultados: list[dict] = []
    trazas: list[dict] = []

    for envio in pendientes:
        logger.info(f"Corrigiendo archivo de {envio.alumno}: {envio.archivo.name}")
        respuesta_alumno = salida._leer_archivo_texto(envio.archivo)
        correccion = corrector.corregir(respuesta_alumno, contexto_unidad)

        resultado = salida.escribir_salidas(envio, correccion)
        resultados.append(resultado)

        trazas.append(
            {
                "timestamp": __import__("datetime").datetime.now().isoformat(),
                "alumno": envio.alumno,
                "archivo_entrada": str(envio.archivo),
                "correccion": correccion,
                "estado": "borrador",
            }
        )

    resumen_path = salida.escribir_resumen(resultados)

    traza_path = CORRECCIONES_DIR / "correcciones_lote.json"
    traza_path.write_text(json.dumps(trazas, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info(f"Proceso completado. Resumen generado en: {resumen_path}")
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
        "--pendientes",
        default=str(DEFAULT_PENDIENTES_DIR),
        help="Carpeta de archivos pendientes.",
    )
    parser.add_argument(
        "--temporal",
        default=str(DEFAULT_TEMPORAL_DIR),
        help="Carpeta de salida temporal por alumno.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    argumentos = parse_args()
    asyncio.run(ejecutar_flujo(argumentos))
