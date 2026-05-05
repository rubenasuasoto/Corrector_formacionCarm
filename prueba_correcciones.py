"""
Script de prueba: demuestra el flujo sin acceder a CARM real
Útil para validar prompts, estructura y lógica antes de conectar con Moodle
"""

import json
from pathlib import Path
from corrector_agente import CorrectorIA, ValidadorTrazabilidad

# Datos de prueba
CASOS_PRUEBA = [
    {
        "nombre": "IA en recomendaciones turísticas",
        "tipo": "ejercicio_practico",
        "enunciado": "Describe una aplicación de Inteligencia Artificial en el sector turístico de Murcia.",
        "respuesta": """
        La IA puede mejorar la experiencia turística en Murcia aplicándose a:
        
        1. Personalización de recomendaciones: Los sistemas de IA analizan preferencias del visitante
           y sugieren rutas, restaurantes y museos adecuados.
        
        2. Chatbots de atención: Responden consultas en tiempo real sobre horarios, precios y eventos.
        
        3. Análisis de patrones de flujo: Predicen congestión en atracciones turísticas para optimizar
           recursos y experiencia.
        
        En Murcia específicamente, esto es útil para la Catedral, museos y playas, donde el flujo
        varía según temporada.
        """,
    },
    {
        "nombre": "Reflexión sobre aprendizaje",
        "tipo": "autoevaluacion",
        "enunciado": "¿Qué has aprendido sobre IA en turismo? ¿Dónde te viste más fuerte y dónde necesitas mejorar?",
        "respuesta": """
        He aprendido que la IA no es solo reconocimiento de voz, sino un conjunto de técnicas
        que se pueden aplicar de forma muy práctica. Mis fortalezas fueron entender cómo
        personalizar recomendaciones y ver aplicaciones reales. Necesito mejorar en machine
        learning y en cómo entrenar modelos con datos locales.
        """,
    },
    {
        "nombre": "Pregunta en foro de debate",
        "tipo": "discusion",
        "enunciado": "¿Cuáles son los mayores retos éticos de usar IA para perfilar turistas?",
        "respuesta": """
        Excelente pregunta. Creo que los retos principales son:
        1. Privacidad: Recopilar datos de comportamiento levanta preocupaciones legales
        2. Sesgos: Un algoritmo mal diseñado podría discriminar a ciertos grupos de turistas
        3. Transparencia: Los usuarios no siempre saben que están siendo "perfilados"
        
        En Murcia, con RGPD europeo, es aún más crítico. ¿Alguien ha visto cómo otras
        regiones turísticas lo manejan?
        """,
    },
]


def probar_correcciones():
    """Ejecuta correcciones de prueba y muestra salidas"""
    print("=" * 80)
    print("PRUEBA: Agente de Corrección - Modo Offline")
    print("=" * 80)

    corrector = CorrectorIA()
    validador = ValidadorTrazabilidad()

    for idx, caso in enumerate(CASOS_PRUEBA, 1):
        print(f"\n{'─' * 80}")
        print(f"CASO {idx}: {caso['nombre']}")
        print(f"Tipo: {caso['tipo']}")
        print(f"{'─' * 80}")

        print("\n📝 ENUNCIADO:")
        print(caso["enunciado"][:200] + "..." if len(caso["enunciado"]) > 200 else caso["enunciado"])

        print("\n📋 RESPUESTA:")
        print(caso["respuesta"][:300] + "..." if len(caso["respuesta"]) > 300 else caso["respuesta"])

        # Corregir
        print("\n⏳ Corrigiendo con IA...")
        correccion = corrector.corregir(caso, tipo=caso["tipo"])

        # Validar
        es_valida = validador.validar_correccion(correccion)
        print(f"\n✓ Validación: {'PASADA' if es_valida else 'FALLIDA'}")

        # Mostrar resultado
        print("\n🎓 CORRECCIÓN GENERADA:")
        print(json.dumps(correccion, indent=2, ensure_ascii=False))

        # Guardar trazabilidad
        ruta = validador.guardar_trazabilidad(
            caso, correccion, alumno=f"alumno_prueba_{idx}"
        )
        print(f"\n💾 Guardado en: {ruta}")

    print("\n" + "=" * 80)
    print("✅ Prueba completada. Revisa carpeta 'correcciones_validadas/'")
    print("=" * 80)


if __name__ == "__main__":
    probar_correcciones()
