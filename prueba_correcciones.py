"""
Prueba offline del agente.

Genera varios envíos ficticios en una carpeta local, ejecuta el flujo sin llamar a
OpenAI y comprueba que se crean las salidas que revisará el equipo antes de subir
nada a CARM.
"""

from __future__ import annotations

import asyncio
import shutil
import zipfile
from argparse import Namespace
from pathlib import Path

from corrector_agente import ejecutar_flujo


BASE_PRUEBA = Path("tmp_prueba")
PENDIENTES = BASE_PRUEBA / "pendientes"
TEMPORAL = BASE_PRUEBA / "temporal"
CONTEXTO = BASE_PRUEBA / "manual_ud01.txt"

CASOS_PRUEBA = {
    "Ana Garcia.txt": (
        "Lo correcto sería no meter datos personales completos en una herramienta gratuita. "
        "Primero habría que anonimizar o seudonimizar los datos, usar solo los datos necesarios "
        "y comprobar que la herramienta cumple el RGPD. También pediría autorización o usaría "
        "una herramienta corporativa con contrato de tratamiento de datos."
    ),
    "ud02cp03/Carmen Lopez.txt": (
        "Antes de usar una herramienta externa revisaría si permite tratar datos personales. "
        "Si no hay garantías, trabajaría con datos anonimizados y una finalidad clara."
    ),
    "Luis Martinez.txt": (
        "Usaría la herramienta gratuita para analizar reservas y luego borraría el archivo. "
        "Así se obtiene información útil sobre el turista."
    ),
    "Entrega vacia.txt": "",
}

DOCX_PRUEBA = "Marta Sanchez.docx"
MULTIMEDIA_PRUEBA = "ud02cp03/Video Alumno.mp4"
ZIP_PRUEBA = "ud02cp03/Entrega Comprimida.zip"
PPTX_PRUEBA = "Presentacion Alumno.pptx"
XLSX_PRUEBA = "Tabla Alumno.xlsx"


def preparar_carpetas() -> None:
    if BASE_PRUEBA.exists():
        shutil.rmtree(BASE_PRUEBA)

    PENDIENTES.mkdir(parents=True, exist_ok=True)
    TEMPORAL.mkdir(parents=True, exist_ok=True)

    CONTEXTO.write_text(
        "Manual UD01: La IA aplicada al turismo debe respetar minimización de datos, "
        "anonimización cuando sea posible, transparencia, finalidad legítima y protección "
        "de información personal identificable según RGPD.",
        encoding="utf-8",
    )

    for nombre, contenido in CASOS_PRUEBA.items():
        destino = PENDIENTES / nombre
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(contenido, encoding="utf-8")

    crear_docx_minimo(
        PENDIENTES / DOCX_PRUEBA,
        "No subiría reservas completas a una herramienta gratuita. Usaría datos anonimizados y revisaría el cumplimiento del RGPD.",
    )

    multimedia = PENDIENTES / MULTIMEDIA_PRUEBA
    multimedia.parent.mkdir(parents=True, exist_ok=True)
    multimedia.write_bytes(b"video-falso-para-prueba")

    crear_zip_prueba(PENDIENTES / ZIP_PRUEBA)
    (PENDIENTES / PPTX_PRUEBA).write_bytes(b"pptx-falso-para-probar-dependencia-opcional")
    (PENDIENTES / XLSX_PRUEBA).write_bytes(b"xlsx-falso-para-probar-dependencia-opcional")


def crear_docx_minimo(path: Path, texto: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>"
        f"{texto}"
        "</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "")
        z.writestr("word/document.xml", document_xml)


def crear_zip_prueba(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "respuesta.txt",
            "Dentro del ZIP explico que anonimizaría los datos antes de usar cualquier herramienta externa.",
        )


def main() -> None:
    preparar_carpetas()

    args = Namespace(
        extraer_carm=False,
        pendientes=str(PENDIENTES),
        temporal=str(TEMPORAL),
        contexto_unidad=str(CONTEXTO),
        prompts="prompts_correccion.json",
        actividad_codigo="ud01cp01",
        sin_ia=True,
        conservar_pendientes=False,
    )

    asyncio.run(ejecutar_flujo(args))

    print("Prueba terminada.")
    print(f"Revisa las salidas en: {TEMPORAL.resolve()}")
    print(f"Resumen: {(TEMPORAL / 'resumen.txt').resolve()}")
    print(f"Hoja de revisión: {(TEMPORAL / 'revision_pendiente.csv').resolve()}")


if __name__ == "__main__":
    main()
