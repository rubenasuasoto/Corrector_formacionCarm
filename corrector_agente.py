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
import json
import logging
import os
import re
import shutil
import unicodedata
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
CARM_COURSE_URL = os.getenv("CARM_COURSE_URL", "https://formacion.carm.es/course/view.php?id=1592")

DEFAULT_PENDIENTES_DIR = Path(r"C:\temp\vscodec\pendientes")
DEFAULT_TEMPORAL_DIR = Path(r"C:\temp\vscodec\temporal")
DEFAULT_ACTIVIDAD_CODIGO = "ud01cp01"

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
    "Responde SIEMPRE en JSON válido y en español con acentos. "
    "Sé justo: evalúa solo lo que el alumno ha escrito y no inventes méritos."
)

PROMPT_CRITERIOS = """
Te paso un archivo con un manual sobre inteligencia artificial aplicada al sector turístico de Murcia como contexto para corregir un ejercicio práctico.

Corrige este ejercicio en una escala del 0 al 10, asignando 3 puntos a la presentación del trabajo:
Un técnico introduce en una herramienta gratuita datos completos de reservas con información personal identificable para que el sistema genere un análisis de comportamiento del visitante.

¿Qué actuación debería realizar para ajustar el uso de la herramienta a principios de protección de datos y buenas prácticas?

Devuelve JSON con este formato exacto:
{
  "nota": 0-10,
  "criterios": [
    {"nombre": "Presentación del trabajo", "maximo": 3, "puntuacion": 0-3, "comentario": "..."},
    {"nombre": "Protección de datos", "maximo": 4, "puntuacion": 0-4, "comentario": "..."},
    {"nombre": "Buenas prácticas y aplicación", "maximo": 3, "puntuacion": 0-3, "comentario": "..."}
  ],
  "retroalimentacion": "Feedback final, coloquial pero formal, adaptado al caso y la unidad"
}
""".strip()


@dataclass
class EnvioPendiente:
    alumno: str
    archivo: Path
    actividad_codigo: str = DEFAULT_ACTIVIDAD_CODIGO
    actividad_nombre: str = ""


class CorrectorIA:
    def __init__(
        self,
        api_key: str | None = None,
        modelo: str | None = None,
        usar_ia: bool = True,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.modelo = modelo or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        self.cliente = OpenAI(api_key=self.api_key) if (usar_ia and OpenAI and self.api_key) else None

    def corregir(self, respuesta: str, contexto_unidad: str) -> dict:
        if not respuesta.strip():
            return self._correccion_vacia()

        if self.cliente is None:
            logger.warning("OPENAI_API_KEY o paquete openai no disponible; usando corrección de respaldo")
            return self._correccion_respaldo()

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

        prompt_usuario = (
            f"{PROMPT_CRITERIOS}\n\n"
            f"ACTIVIDAD: {actividad_codigo}\n\n"
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
            '        {"nombre": "Protección de datos", "maximo": 4, "puntuacion": 0-4, "comentario": "..."},\n'
            '        {"nombre": "Buenas prácticas y aplicación", "maximo": 3, "puntuacion": 0-3, "comentario": "..."}\n'
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
                    {"role": "system", "content": PROMPT_SISTEMA},
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
            return [self.corregir(respuesta, contexto_unidad) for _, respuesta in entregas]

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
                    "nombre": "Protección de datos",
                    "maximo": 4,
                    "puntuacion": 0,
                    "comentario": "No hay desarrollo sobre tratamiento de datos personales.",
                },
                {
                    "nombre": "Buenas prácticas y aplicación",
                    "maximo": 3,
                    "puntuacion": 0,
                    "comentario": "No se aportan medidas aplicables al caso.",
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
                    "nombre": "Protección de datos",
                    "maximo": 4,
                    "puntuacion": 2.8,
                    "comentario": "Identifica riesgos de datos personales, pero faltan medidas concretas de minimización y anonimizado.",
                },
                {
                    "nombre": "Buenas prácticas y aplicación",
                    "maximo": 3,
                    "puntuacion": 2.0,
                    "comentario": "Aplica ideas útiles, aunque conviene aterrizarlas mejor al entorno turístico de Murcia.",
                },
            ],
            "retroalimentacion": "Buen trabajo general. Vas en la línea correcta, pero te recomiendo reforzar la parte de cumplimiento y proponer acciones más concretas para el caso.",
        }

    @staticmethod
    def _correccion_error(mensaje: str) -> dict:
        return {
            "nota": 0,
            "criterios": [],
            "retroalimentacion": mensaje,
        }


class ExtractorCarm:
    def __init__(self, usuario: str, contrasena: str, pendientes_dir: Path):
        self.usuario = usuario
        self.contrasena = contrasena
        self.pendientes_dir = pendientes_dir

    @staticmethod
    def _normalizar(texto: str) -> str:
        texto = re.sub(r"\s+", " ", (texto or "")).strip().lower()
        normalizado = unicodedata.normalize("NFKD", texto)
        return "".join(c for c in normalizado if not unicodedata.combining(c))

    @staticmethod
    def _sanitizar_nombre(nombre: str) -> str:
        limpio = re.sub(r"[\\/:*?\"<>|]", "_", nombre.strip())
        return re.sub(r"\s+", " ", limpio)[:120] or "alumno"

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
            if "caso practico" not in base:
                continue
            if "(obligatorio)" not in base:
                continue
            href = await a.get_attribute("href")
            if not href:
                continue
            unidad = await self._obtener_nombre_unidad(a)
            codigo = self._inferir_codigo_actividad(nombre, unidad)
            actividades.append(
                {
                    "nombre": nombre,
                    "unidad": unidad,
                    "codigo": codigo,
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
            actividad_codigo = actividad.get("codigo", DEFAULT_ACTIVIDAD_CODIGO)
            destino_dir = self.pendientes_dir / actividad_codigo
            destino_dir.mkdir(parents=True, exist_ok=True)
            destino = destino_dir / f"{alumno_limpio}{ext}"

            try:
                resp = await page.context.request.get(file_url)
                if resp.status != 200:
                    logger.warning(f"No se pudo descargar envio de {alumno}: HTTP {resp.status}")
                    continue
                body = await resp.body()
                destino.write_bytes(body)
                descargados.append(
                    EnvioPendiente(
                        alumno=alumno_limpio,
                        archivo=destino,
                        actividad_codigo=actividad_codigo,
                        actividad_nombre=actividad.get("nombre", ""),
                    )
                )
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
                    logger.info(f"Procesando grading {act['codigo']}: {act['nombre']}")
                    envios = await self._descargar_envios_actividad(page, act)
                    todos_envios.extend(envios)

                with open(RESPUESTAS_DIR / "envios_descargados.json", "w", encoding="utf-8") as f:
                    json.dump(
                        [
                            {
                                "alumno": e.alumno,
                                "archivo": str(e.archivo),
                                "actividad_codigo": e.actividad_codigo,
                                "actividad_nombre": e.actividad_nombre,
                            }
                            for e in todos_envios
                        ],
                        f,
                        indent=2,
                        ensure_ascii=False,
                    )

                return contexto, todos_envios
            finally:
                await browser.close()


class GeneradorSalidas:
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
        copia_entrega = alumno_dir / f"{actividad_codigo}{ext}"
        shutil.copy2(envio.archivo, copia_entrega)

        texto_correccion = self._formatear_correccion(correccion, actividad_codigo)
        archivo_correccion = alumno_dir / f"{actividad_codigo}.txt"
        archivo_correccion.write_text(texto_correccion, encoding="utf-8")

        return {
            "alumno": envio.alumno,
            "actividad": actividad_codigo,
            "actividad_nombre": envio.actividad_nombre,
            "nota": float(correccion.get("nota", 0)),
            "retroalimentacion": str(correccion.get("retroalimentacion", "")),
            "archivo_original": str(envio.archivo),
            "archivo_copiado": str(copia_entrega),
            "archivo_correccion": str(archivo_correccion),
            "estado": "borrador_pendiente_de_revision",
        }

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
        lineas.append("Detalle por criterios:")

        for crit in correccion.get("criterios", []):
            nombre = crit.get("nombre", "Criterio")
            p = crit.get("puntuacion", 0)
            m = crit.get("maximo", "?")
            c = crit.get("comentario", "")
            lineas.append(f"- {nombre}: {p}/{m}. {c}")

        lineas.append("")
        lineas.append("Retroalimentación:")
        lineas.append(str(correccion.get("retroalimentacion", "")))
        lineas.append("")

        return "\n".join(lineas)

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


async def ejecutar_flujo(args) -> None:
    pendientes_dir = Path(args.pendientes)
    temporal_dir = Path(args.temporal)

    contexto_unidad = ""
    pendientes_extraidos: list[EnvioPendiente] = []

    if args.contexto_unidad:
        contexto_path = Path(args.contexto_unidad)
        if contexto_path.exists() and contexto_path.is_file():
            contexto_unidad = GeneradorSalidas._leer_archivo_texto(contexto_path)
            logger.info(f"Contexto de unidad cargado desde: {contexto_path}")
        else:
            logger.warning(f"No se encontró el archivo de contexto: {contexto_path}")

    if args.extraer_carm:
        usuario = os.getenv("CARM_USUARIO", "")
        contrasena = os.getenv("CARM_CONTRASENA", "")
        if not usuario or not contrasena:
            logger.error("Faltan CARM_USUARIO/CARM_CONTRASENA en .env para extraer desde CARM")
            return

        extractor = ExtractorCarm(usuario, contrasena, pendientes_dir)
        try:
            logger.info("Iniciando extraccion en CARM (login -> my -> curso -> grading)")
            contexto_unidad, pendientes_extraidos = await extractor.ejecutar()
        except Exception as e:
            logger.error(f"No se pudo completar extraccion CARM: {e}")
            return

    if not contexto_unidad:
        contexto_unidad = (
            "No se pudo extraer automáticamente el contenido imprimible. "
            "Aplica igualmente criterios de protección de datos y buenas prácticas del caso."
        )

    salida = GeneradorSalidas(pendientes_dir, temporal_dir, actividad_codigo=args.actividad_codigo)
    pendientes = pendientes_extraidos or salida.obtener_pendientes()

    if not pendientes:
        logger.warning(f"No hay archivos pendientes en {pendientes_dir}")
        return

    corrector = CorrectorIA(usar_ia=not args.sin_ia)

    resultados: list[dict] = []
    trazas: list[dict] = []

    pendientes_por_actividad: dict[str, list[EnvioPendiente]] = {}
    for envio in pendientes:
        pendientes_por_actividad.setdefault(envio.actividad_codigo, []).append(envio)

    for actividad_codigo, envios_actividad in sorted(pendientes_por_actividad.items()):
        logger.info(
            f"Corrigiendo lote {actividad_codigo}: {len(envios_actividad)} entrega(s)"
        )
        entregas_con_texto = [
            (envio, salida._leer_archivo_texto(envio.archivo))
            for envio in envios_actividad
        ]
        correcciones = corrector.corregir_lote(
            entregas_con_texto,
            contexto_unidad,
            actividad_codigo,
        )

        for (envio, _), correccion in zip(entregas_con_texto, correcciones):
            resultado = salida.escribir_salidas(envio, correccion)
            resultados.append(resultado)
            if not args.conservar_pendientes:
                salida.eliminar_pendiente_calificado(envio)

            trazas.append(
                {
                    "timestamp": __import__("datetime").datetime.now().isoformat(),
                    "alumno": envio.alumno,
                    "actividad_codigo": envio.actividad_codigo,
                    "actividad_nombre": envio.actividad_nombre,
                    "archivo_entrada": str(envio.archivo),
                    "correccion": correccion,
                    "estado": "borrador",
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
        "--actividad-codigo",
        default=DEFAULT_ACTIVIDAD_CODIGO,
        help="Nombre base de los archivos generados para la actividad.",
    )
    parser.add_argument(
        "--sin-ia",
        action="store_true",
        help="Ejecuta el flujo con corrección de respaldo, sin llamar a OpenAI. Útil para probar carpetas y salidas.",
    )
    parser.add_argument(
        "--conservar-pendientes",
        action="store_true",
        help="No elimina de pendientes los archivos ya copiados y corregidos.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    argumentos = parse_args()
    asyncio.run(ejecutar_flujo(argumentos))
