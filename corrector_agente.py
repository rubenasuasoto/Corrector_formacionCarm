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
import zipfile
from dataclasses import dataclass
from html import unescape
from pathlib import Path
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
    actividad_enunciado: str = ""
    estado_entrega: str = ""
    archivo_original_nombre: str = ""


@dataclass
class LecturaEntrega:
    texto: str
    requiere_revision_manual: bool = False
    motivo: str = ""


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

    def corregir(self, respuesta: str, contexto_unidad: str) -> dict:
        if not respuesta.strip():
            return self._correccion_vacia()

        if self.cliente is None:
            logger.warning("OPENAI_API_KEY o paquete openai no disponible; usando corrección de respaldo")
            return self._correccion_respaldo()

        prompt_cfg = self.prompts.obtener(DEFAULT_ACTIVIDAD_CODIGO)
        prompt_usuario = (
            f"{prompt_cfg['criterios']}\n\n"
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

        prompt_cfg = self.prompts.obtener(actividad_codigo)
        prompt_usuario = (
            f"{prompt_cfg['criterios']}\n\n"
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
    ):
        self.usuario = usuario
        self.contrasena = contrasena
        self.pendientes_dir = pendientes_dir
        self.mantener_navegador = mantener_navegador
        self.guardar_evidencias = guardar_evidencias
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
    def _url_vista_actividad(url: str) -> str:
        p = urlparse(url)
        q = dict(parse_qsl(p.query))
        q.pop("action", None)
        q.pop("filter", None)
        q.pop("tsort", None)
        q.pop("tdir", None)
        return urlunparse((p.scheme, p.netloc, p.path, p.params, urlencode(q), p.fragment))

    async def _login(self, page) -> None:
        await page.goto(CARM_LOGIN_URL, wait_until="networkidle")
        await page.fill("input[name='username'], #username", self.usuario)
        await page.fill("input[name='password'], #password", self.contrasena)
        await page.click("button[type='submit'], input[type='submit']")
        await page.wait_for_load_state("networkidle")

        if await page.locator("input[name='username'], #username").count():
            raise RuntimeError("El login parece seguir mostrando el formulario. Revisa credenciales o flujo de acceso.")

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

    async def _obtener_actividades_obligatorias(self, page) -> list[dict]:
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
            if "(obligatorio)" not in base:
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
            actividades.append(
                {
                    "nombre": nombre,
                    "unidad": unidad,
                    "codigo": codigo,
                    "url": vista_url,
                    "url_grading": href_require_grading or self._agregar_action_grading(vista_url),
                    "filtro": "require_grading" if href_require_grading else "grading",
                }
            )
        return actividades

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

    async def _descargar_envios_actividad(self, page, actividad: dict, descargar: bool = True) -> list[EnvioPendiente]:
        descargados: list[EnvioPendiente] = []
        await page.goto(actividad["url_grading"], wait_until="networkidle")

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

    async def ejecutar(self, solo_listar: bool = False) -> tuple[str, list[EnvioPendiente]]:
        if async_playwright is None:
            raise RuntimeError(
                "Playwright no esta disponible. Ejecuta: pip install -r requirements.txt y luego playwright install chromium"
            )

        self.pendientes_dir.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()
            try:
                await self._login(page)

                await page.goto(CARM_MY_URL, wait_until="networkidle")
                await page.goto(CARM_COURSE_URL, wait_until="networkidle")

                contexto = await self._extraer_contexto_imprimible(page)
                actividades = await self._obtener_actividades_obligatorias(page)

                logger.info(f"Actividades prioritarias encontradas: {len(actividades)}")

                todos_envios: list[EnvioPendiente] = []
                for act in actividades:
                    logger.info(f"Procesando grading {act['codigo']}: {act['nombre']}")
                    act["enunciado"] = await self._extraer_enunciado_actividad(page, act["url"])
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
                    logger.info("Navegador abierto. Pulsa Enter en la consola para cerrarlo.")
                    await asyncio.to_thread(input)
                try:
                    await context.clear_cookies()
                    await page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
                except Exception:
                    pass
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
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()
            try:
                await self._login(page)
                if self.guardar_evidencias:
                    await self._guardar_diagnostico_pagina(page, diagnostico_dir, "01_post_login")

                await page.goto(CARM_MY_URL, wait_until="networkidle")
                if self.guardar_evidencias:
                    await self._guardar_diagnostico_pagina(page, diagnostico_dir, "02_my")

                await page.goto(CARM_COURSE_URL, wait_until="networkidle")
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
                        await page.goto(actividad["url_grading"], wait_until="networkidle")
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
                    logger.info("Navegador abierto. Pulsa Enter en la consola para cerrarlo.")
                    await asyncio.to_thread(input)
                try:
                    await context.clear_cookies()
                    await page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
                except Exception:
                    pass
                await context.close()
                await browser.close()


class GeneradorSalidas:
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
            for info in z.infolist():
                if info.is_dir() or info.file_size > 5_000_000:
                    continue
                nombre = Path(info.filename)
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
            "retroalimentacion": str(correccion.get("retroalimentacion", "")),
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

    def escribir_prompts_codex(
        self,
        pendientes_por_actividad: dict[str, list[EnvioPendiente]],
        contexto_unidad: str,
        prompts_path: str | Path | None = None,
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
                    entregas.append({**item_base, "respuesta": lectura.texto})

                manifiesto.append(
                    {
                        **item_base,
                        "requiere_revision_manual": lectura.requiere_revision_manual,
                        "motivo": lectura.motivo,
                    }
                )

            prompt_cfg = gestor_prompts.obtener(actividad_codigo)
            prompt_path = prompts_dir / f"prompt_{actividad_codigo}.md"
            lineas = [
                f"# Prompt para Codex - {actividad_codigo}",
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
                '        {"nombre": "Protección de datos", "maximo": 4, "puntuacion": 0, "comentario": "..."},',
                '        {"nombre": "Buenas prácticas y aplicación", "maximo": 3, "puntuacion": 0, "comentario": "..."}',
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
                json.dumps(entregas, ensure_ascii=False, indent=2),
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

    if args.extraer_carm or getattr(args, "diagnosticar_carm", False) or getattr(args, "solo_listar_carm", False):
        usuario = os.getenv("CARM_USUARIO", "")
        contrasena = os.getenv("CARM_CONTRASENA", "")
        if not usuario or not contrasena:
            logger.error("Faltan CARM_USUARIO/CARM_CONTRASENA en .env para extraer desde CARM")
            return

        extractor = ExtractorCarm(
            usuario,
            contrasena,
            pendientes_dir,
            mantener_navegador=getattr(args, "mantener_navegador", False),
            guardar_evidencias=getattr(args, "guardar_evidencias", False),
        )
        try:
            if getattr(args, "diagnosticar_carm", False):
                diagnostico_path = await extractor.diagnosticar(
                    incluir_enlaces=getattr(args, "incluir_enlaces_diagnostico", False),
                )
                logger.info(f"Diagnóstico CARM generado en: {diagnostico_path}")
                return

            logger.info("Iniciando extraccion en CARM (login -> my -> curso -> grading)")
            contexto_unidad, pendientes_extraidos = await extractor.ejecutar(
                solo_listar=getattr(args, "solo_listar_carm", False),
            )
            if getattr(args, "solo_listar_carm", False):
                logger.info("Listado CARM generado sin descargar archivos ni corregir.")
                return
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

    pendientes_por_actividad: dict[str, list[EnvioPendiente]] = {}
    for envio in pendientes:
        pendientes_por_actividad.setdefault(envio.actividad_codigo, []).append(envio)

    if getattr(args, "preparar_prompts_codex", False):
        rutas_prompts = salida.escribir_prompts_codex(
            pendientes_por_actividad,
            contexto_unidad,
            prompts_path=args.prompts,
        )
        logger.info("Prompts para Codex generados sin llamar a la API:")
        for ruta in rutas_prompts:
            logger.info(f"- {ruta}")
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
        "--conservar-pendientes",
        action="store_true",
        help="No elimina de pendientes los archivos ya copiados y corregidos.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    argumentos = parse_args()
    asyncio.run(ejecutar_flujo(argumentos))
