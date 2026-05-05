"""
Agente de correcci\u00f3n autom\u00e1tica para CARM Formaci\u00f3n
Extrae actividades del curso Moodle, las corrige con prompts programados
y guarda trazabilidad completa.
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
import os

from dotenv import load_dotenv
from playwright.async_api import async_playwright, Page
from openai import OpenAI


load_dotenv()

# Configuraci\u00f3n
CARM_URL = "https://formacion.carm.es/course/view.php?id=1592"
LOG_DIR = Path("logs_correcciones")
RESPUESTAS_DIR = Path("respuestas_extraidas")
CORRECCIONES_DIR = Path("correcciones_validadas")

# Crear directorios
LOG_DIR.mkdir(exist_ok=True)
RESPUESTAS_DIR.mkdir(exist_ok=True)
CORRECCIONES_DIR.mkdir(exist_ok=True)

# Logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / f"agente_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


# ============================================================================
# PROMPTS PROGRAMADOS POR TIPO DE ACTIVIDAD
# ============================================================================

PROMPTS = {
    "ejercicio_practico": """
Eres un corrector experto en Inteligencia Artificial aplicada al turismo.
Debes evaluar la respuesta del alumno seg\u00fan esta r\u00fabrica:

**R\u00fabrica:**
1. Precisi\u00f3n t\u00e9cnica (40%): \u00bfUtiliza conceptos correctos de IA?
2. Aplicaci\u00f3n al turismo (30%): \u00bfRealiza conexiones concretas al sector?
3. Profundidad (20%): \u00bfVa m\u00e1s all\u00e1 de lo superficial?
4. Claridad (10%): \u00bfEst\u00e1 bien estructurado?

**Respuesta del alumno:**
{respuesta}

**Enunciado:**
{enunciado}

Genera una evaluaci\u00f3n en JSON con este formato:
{{
    "nota": (0-10),
    "justificacion": "Explicaci\u00f3n breve de la calificaci\u00f3n",
    "fortalezas": ["Lista de puntos fuertes"],
    "mejoras": ["Sugerencias de mejora"],
    "feedback": "Comentario constructivo para el alumno"
}}
""",
    "autoevaluacion": """
Analiza esta autoevaluaci\u00f3n del alumno considerando coherencia y realismo.

**Autoevaluaci\u00f3n del alumno:**
{respuesta}

**Criterios de validez:**
- \u00bfEs honesta y realista?
- \u00bfDemuestra autoconocimiento?
- \u00bfEst\u00e1 alineada con los objetivos del curso?

Responde en JSON:
{{
    "es_valida": true/false,
    "razon": "Explicaci\u00f3n",
    "sugerencia": "Qu\u00e9 mejorar\u00eda la reflexi\u00f3n"
}}
""",
    "discusion": """
Valida la participaci\u00f3n del alumno en el foro considerando:
- Relevancia al tema
- Fundamento con ejemplos
- Respeto y constructividad

**Contribuci\u00f3n:**
{respuesta}

**Tema del debate:**
{enunciado}

Responde en JSON:
{{
    "puntuacion": (0-10),
    "comentario": "Feedback sobre la participaci\u00f3n",
    "incentivar": "Sugiere c\u00f3mo mejorar para pr\u00f3ximos aportes"
}}
""",
}


# ============================================================================
# EXTRACTOR DE ACTIVIDADES
# ============================================================================

class ExtractorCarm:
    def __init__(self, usuario: str, contrasena: str):
        self.usuario = usuario
        self.contrasena = contrasena
        self.page: Optional[Page] = None

    async def iniciar_sesion(self, page: Page):
        """Inicia sesi\u00f3n en CARM Formaci\u00f3n"""
        logger.info("Iniciando sesi\u00f3n en CARM...")
        await page.goto(CARM_URL, wait_until="networkidle")
        
        # Rellena credenciales (ajusta selectores seg\u00fan HTML real)
        try:
            await page.fill("input[name='username']", self.usuario)
            await page.fill("input[name='password']", self.contrasena)
            await page.click("button[type='submit']")
            await page.wait_for_load_state("networkidle")
            logger.info("\u2713 Sesi\u00f3n iniciada correctamente")
        except Exception as e:
            logger.error(f"Error en login: {e}")
            try:
                respuesta = self.cliente.chat.completions.create(
                    model=self.modelo,
                    messages=[
                        {
                            "role": "system",
                            "content": "Devuelve siempre una respuesta estrictamente en JSON válido.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    max_completion_tokens=1024,
                )

                contenido = respuesta.choices[0].message.content or "{}"
                correccion = json.loads(contenido)
                
                if tipo and nombre and enlace:
                    actividad = {
                        "tipo": await tipo.text_content(),
                        "nombre": await nombre.text_content(),
                        "url": await enlace.get_attribute("href"),
                        "extraido_en": datetime.now().isoformat(),
                    }
                    actividades.append(actividad)
                    logger.debug(f"Actividad encontrada: {actividad['nombre']}")
            except Exception as e:
                logger.warning(f"Error extrayendo actividad: {e}")
                continue

        logger.info(f"\u2713 {len(actividades)} actividades extra\u00eddas")
        return actividades

    async def extraer_respuestas_alumno(self, page: Page, actividad_url: str) -> dict:
        """Accede a una actividad y extrae respuesta del alumno"""
        await page.goto(actividad_url, wait_until="networkidle")
        
        # Intenta extraer el contenido de respuesta (selectores aproximados)
        respuesta_elem = await page.query_selector(".student-response, .user-answer, textarea")
        enunciado_elem = await page.query_selector(".activity-description, .mod-description")
        
        respuesta = await respuesta_elem.text_content() if respuesta_elem else ""
        enunciado = await enunciado_elem.text_content() if enunciado_elem else ""
        
        return {
            "respuesta": respuesta.strip(),
            "enunciado": enunciado.strip(),
        }

    async def ejecutar(self) -> list[dict]:
        """Orquesta el flujo completo de extracci\u00f3n"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            page = await browser.new_page()
            
            try:
                await self.iniciar_sesion(page)
                actividades = await self.extraer_actividades(page)
                
                # Guarda actividades en JSON para inspecci\u00f3n
                with open(RESPUESTAS_DIR / "actividades_extraidas.json", "w") as f:
                    json.dump(actividades, f, indent=2, ensure_ascii=False)
                
                logger.info(f"Actividades guardadas en {RESPUESTAS_DIR}")
                return actividades
                
            finally:
                await browser.close()


# ============================================================================
# CORRECTOR CON PROMPTS PERSONALIZADOS
# ============================================================================

class CorrectorIA:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.modelo = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        self.cliente = OpenAI(api_key=self.api_key)

    def corregir(self, actividad: dict, tipo: str = "ejercicio_practico") -> dict:
        """Corrige una actividad usando prompt personalizado"""
        logger.info(f"Corrigiendo: {actividad.get('nombre', 'S/N')}")
        
        prompt_template = PROMPTS.get(tipo, PROMPTS["ejercicio_practico"])
        prompt = prompt_template.format(
            respuesta=actividad.get("respuesta", ""),
            enunciado=actividad.get("enunciado", ""),
        )

        try:
            respuesta = self.cliente.chat.completions.create(
                model=self.modelo,
                messages=[
                    {
                        "role": "system",
                        "content": "Devuelve siempre una respuesta estrictamente en JSON válido.",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                max_completion_tokens=1024,
            )

            contenido = respuesta.choices[0].message.content or "{}"
            correccion = json.loads(contenido)
            
            logger.debug(f"Correccion: {correccion}")
            return correccion
            
        except Exception as e:
            logger.error(f"Error en correcci\u00f3n IA: {e}")
            return {"error": str(e), "actividad": actividad.get("nombre")}


# ============================================================================
# VALIDADOR Y GUARDADO CON TRAZABILIDAD
# ============================================================================

class ValidadorTrazabilidad:
    @staticmethod
    def validar_correccion(correccion: dict) -> bool:
        """Valida que la correcci\u00f3n tenga estructura esperada"""
        campos_esperados = ["nota", "justificacion"] if "nota" in correccion else ["error"]
        return all(campo in correccion or "error" in correccion for campo in ["nota", "justificacion"])

    @staticmethod
    def guardar_trazabilidad(actividad: dict, correccion: dict, alumno: str = "anonimo"):
        """Guarda registro completo de correcci\u00f3n para auditor\u00eda"""
        registro = {
            "timestamp": datetime.now().isoformat(),
            "alumno": alumno,
            "actividad": actividad.get("nombre", "S/N"),
            "respuesta_original": actividad.get("respuesta", ""),
            "correccion_generada": correccion,
            "prompt_tipo": "ejercicio_practico",  # Configurable
            "estado": "borrador",  # Se puede cambiar a "validado" o "publicado"
        }
        
        # Genera nombre \u00fanico basado en timestamp y nombre
        nombre_archivo = (
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{alumno}_{actividad.get('nombre', 'unknown')}.json"
        )
        
        ruta = CORRECCIONES_DIR / nombre_archivo
        with open(ruta, "w") as f:
            json.dump(registro, f, indent=2, ensure_ascii=False)
        
        logger.info(f"\u2713 Trazabilidad guardada: {ruta}")
        return ruta


# ============================================================================
# ORQUESTADOR PRINCIPAL
# ============================================================================

async def main():
    """Flujo principal de correcci\u00f3n autom\u00e1tica"""
    logger.info("=" * 70)
    logger.info("INICIANDO AGENTE DE CORRECCI\u00d3N - CARM FORMACI\u00d3N")
    logger.info("=" * 70)
    
    # Credenciales (usa variables de entorno en producci\u00f3n)
    usuario = os.getenv("CARM_USUARIO", "tu_usuario")
    contrasena = os.getenv("CARM_CONTRASENA", "tu_contrasena")
    
    # Paso 1: Extraer actividades
    extractor = ExtractorCarm(usuario, contrasena)
    try:
        # Nota: descomenta la l\u00ednea siguiente si quieres extraer del sitio real
        # actividades = await extractor.ejecutar()
        
        # Por ahora, usa datos de prueba
        actividades = [
            {
                "nombre": "Ejercicio IA en turismo",
                "tipo": "assignment",
                "respuesta": "La IA puede usarse para personalizar recomendaciones de viajes...",
                "enunciado": "Describe una aplicaci\u00f3n de IA en el sector tur\u00edstico de Murcia",
            }
        ]
        logger.info("Usando datos de prueba para demostraci\u00f3n")
    except Exception as e:
        logger.error(f"Error en extracci\u00f3n: {e}")
        try:
            respuesta = self.cliente.chat.completions.create(
                model=self.modelo,
                messages=[
                    {
                        "role": "system",
                        "content": "Devuelve siempre una respuesta estrictamente en JSON válido.",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                max_completion_tokens=1024,
            )

            contenido = respuesta.choices[0].message.content or "{}"
            correccion = json.loads(contenido)
            correccion = json.loads(contenido)
            correccion = json.loads(contenido)
        ruta = validador.guardar_trazabilidad(actividad, correccion, alumno="alumno_001")
        correcciones_generadas.append({"actividad": actividad, "correccion": correccion, "archivo": str(ruta)})
    
    # Resumen final
    logger.info("=" * 70)
    logger.info(f"RESUMEN: {len(correcciones_generadas)} actividades procesadas")
    logger.info(f"Correcciones guardadas en: {CORRECCIONES_DIR}")
    logger.info("ESTADO: En borrador - Requiere revisi\u00f3n manual antes de publicar")
    logger.info("=" * 70)
    
    return correcciones_generadas


if __name__ == "__main__":
    asyncio.run(main())
