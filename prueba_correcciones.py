"""
Prueba offline del agente.

Genera varios envíos ficticios en una carpeta local, ejecuta el flujo sin llamar a
OpenAI y comprueba que se crean las salidas que revisará el equipo antes de subir
nada a CARM.
"""

from __future__ import annotations

import asyncio
import shutil
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


def main() -> None:
    preparar_carpetas()

    args = Namespace(
        extraer_carm=False,
        pendientes=str(PENDIENTES),
        temporal=str(TEMPORAL),
        contexto_unidad=str(CONTEXTO),
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
