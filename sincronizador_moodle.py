"""
LEGADO / REFERENCIA HISTORICA.

Este script no forma parte del flujo principal actual del Corrector CARM.
La ruta operativa es `corrector_agente.py` + `interfaz_app.py`, con subida
asistida desde `revision_pendiente.csv`.

Mantener solo como referencia hasta decidir si se mueve a `legacy/` o se elimina.
"""

import json
import logging
from pathlib import Path
from typing import Optional
import requests
from datetime import datetime

logger = logging.getLogger(__name__)

class SincronizadorMoodle:
    """Sube correcciones validadas desde JSON a la plataforma Moodle"""
    
    def __init__(self, url_moodle: str, token_api: str):
        """
        Args:
            url_moodle: URL base de Moodle (ej: https://formacion.carm.es)
            token_api: Token de acceso API de Moodle
        """
        self.url_moodle = url_moodle
        self.token_api = token_api
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token_api}"})

    def cargar_correccion(self, ruta_json: Path) -> dict:
        """Carga un archivo de correcciÃ³n validada"""
        with open(ruta_json, "r") as f:
            return json.load(f)

    def es_validada(self, correccion: dict) -> bool:
        """Verifica que la correcciÃ³n estÃ© lista para publicar"""
        estado = correccion.get("estado", "")
        return estado in ["validado", "publicado"]

    def subir_nota_moodle(self, correccion: dict) -> bool:
        """
        Sube la calificaciÃ³n a Moodle usando su API
        Requiere: courseid, assignmentid, userid, grade, feedback
        """
        try:
            if not self.es_validada(correccion):
                logger.warning(f"CorrecciÃ³n no validada: {correccion['actividad']}")
                return False

            # Estructura esperada (adapta segÃºn metadatos reales)
            payload = {
                "courseid": correccion.get("courseid", 1592),
                "assignmentid": correccion.get("assignmentid"),
                "userid": correccion.get("userid"),
                "grade": correccion.get("correccion_generada", {}).get("nota", 0),
                "feedback": correccion.get("correccion_generada", {}).get("feedback", ""),
            }

            # Llamada a API de Moodle (ajusta endpoint segÃºn versiÃ³n)
            response = self.session.post(
                f"{self.url_moodle}/webservice/rest/server.php",
                params={
                    "wstoken": self.token_api,
                    "wsfunction": "mod_assign_save_grade",
                    "moodlewsrestformat": "json",
                },
                json=payload,
            )

            if response.status_code == 200:
                logger.info(f"âœ“ Nota subida para {correccion['alumno']}")
                return True
            else:
                logger.error(f"Error en API Moodle: {response.text}")
                return False

        except Exception as e:
            logger.error(f"Error subiendo nota: {e}")
            return False

    def sincronizar_lote(self, dir_correcciones: Path):
        """Procesa todas las correcciones validadas en un directorio"""
        archivos = list(dir_correcciones.glob("*.json"))
        
        if not archivos:
            logger.info("No hay correcciones validadas para sincronizar")
            return
        
        exitosas = 0
        fallidas = 0
        
        for archivo in archivos:
            correccion = self.cargar_correccion(archivo)
            
            if self.subir_nota_moodle(correccion):
                # Marca como publicada
                correccion["estado"] = "publicado"
                correccion["publicado_en"] = datetime.now().isoformat()
                
                with open(archivo, "w") as f:
                    json.dump(correccion, f, indent=2, ensure_ascii=False)
                
                exitosas += 1
            else:
                fallidas += 1
        
        logger.info(f"SincronizaciÃ³n completada: {exitosas} OK, {fallidas} errores")


# ============================================================================
# EJEMPLO DE USO
# ============================================================================

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv()

    MOODLE_URL = "https://formacion.carm.es"
    MOODLE_TOKEN = os.getenv("MOODLE_API_TOKEN", "tu_token_api")
    CORRECCIONES_DIR = Path("correcciones_validadas")

    sincronizador = SincronizadorMoodle(MOODLE_URL, MOODLE_TOKEN)
    sincronizador.sincronizar_lote(CORRECCIONES_DIR)
