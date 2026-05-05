# Estado del proyecto: agente corrector CARM

Última actualización: 2026-05-05

## Objetivo

Automatizar la corrección de casos prácticos de CARM Formación, manteniendo una revisión manual antes de subir notas o retroalimentación a la plataforma.

El flujo manual original era:

1. Pasar el manual de la unidad como contexto.
2. Pasar el enunciado del caso práctico.
3. Pedir una rúbrica.
4. Descargar entregas de alumnos en `C:\temp\vscodec\pendientes`.
5. Corregirlas con Codex/OpenAI.
6. Crear en `C:\temp\vscodec\temporal` una carpeta por alumno con la respuesta y la corrección.
7. Subir manualmente la nota y la retroalimentación tras revisión.

## Flujo actual implementado

El script principal es `corrector_agente.py`.

Puede trabajar de dos formas:

- Con archivos ya descargados en `C:\temp\vscodec\pendientes`.
- Con extracción desde CARM usando `--extraer-carm`.

Cuando corrige:

1. Agrupa las entregas por actividad, por ejemplo `ud01cp01` o `ud02cp03`.
2. Hace corrección por lote: una petición de IA por actividad, no una por alumno.
3. Crea una carpeta por alumno dentro de `temporal`.
4. Copia la respuesta original del alumno.
5. Genera el archivo de corrección con nota y retroalimentación.
6. Genera resumen global y resúmenes por actividad.
7. Genera `revision_pendiente.csv` para revisión manual.
8. Elimina de `pendientes` los archivos ya calificados, salvo que se use `--conservar-pendientes`.

Los archivos que no puedan leerse de forma fiable no se envían a la IA. Se copian a `temporal`, se marca la corrección como `revision_manual_necesaria` y se mantienen en `pendientes` para revisarlos.

Se ha preparado extracción ampliada opcional:

- PDF con `pypdf`.
- PPTX con `python-pptx`.
- XLSX con `openpyxl`.
- ZIP leyendo internamente archivos soportados.
- JPG/PNG con OCR mediante `pillow` + `pytesseract`, pero requiere instalar Tesseract OCR en Windows.

Instalación:

```powershell
pip install -r requirements-extraccion.txt
```

El formato `.doc` antiguo queda de momento para revisión manual porque no tiene una lectura fiable sin Word, LibreOffice o herramientas externas.

## Nombres de archivos

El código de actividad se detecta como `udXXcpYY`.

Ejemplos:

- `ud01cp01`
- `ud02cp03`

Si se extrae desde CARM, el agente intenta detectarlo desde el nombre de la unidad y del caso práctico.

Si se corrigen archivos descargados a mano:

- Se puede pasar `--actividad-codigo ud02cp03`.
- O se pueden meter los archivos dentro de una subcarpeta `pendientes\ud02cp03\`.

En `temporal\<alumno>\`:

- Si la respuesta original es `.pdf`, `.docx`, etc.: se copia como `ud01cp01.pdf`, `ud01cp01.docx`, etc.
- Si la respuesta original es `.txt`: se copia como `ud01cp01_respuesta.txt` para no pisar la corrección.
- La corrección siempre se guarda como `ud01cp01.txt`.

## Archivos importantes

- `corrector_agente.py`: flujo principal del agente.
- `prueba_correcciones.py`: prueba offline sin CARM y sin IA real.
- `prompts_correccion.json`: prompts modulares por actividad o por defecto.
- `QUICKSTART.md`: guía rápida de uso.
- `.env.example`: plantilla de configuración.
- `.env`: configuración real local, no pensada para compartirse.
- `sincronizador_moodle.py`: borrador futuro para subida a Moodle, todavía no es el foco.

## Prompts modulares

Los prompts se han sacado a `prompts_correccion.json`.

Estructura:

```json
{
  "prompts": {
    "default": {
      "sistema": "...",
      "criterios": "..."
    },
    "ud02cp03": {
      "sistema": "...",
      "criterios": "..."
    }
  }
}
```

Si existe una clave concreta para la actividad, se usa esa.
Si no existe, se usa `default`.

También se puede usar otro archivo:

```powershell
python corrector_agente.py --prompts C:\ruta\prompts_modulo_02.json
```

## Comandos de prueba

Compilar:

```powershell
python -m py_compile corrector_agente.py prueba_correcciones.py
```

Prueba offline:

```powershell
python prueba_correcciones.py
```

La prueba crea datos temporales en:

```text
tmp_prueba\pendientes
tmp_prueba\temporal
```

Resultados esperados:

- `tmp_prueba\temporal\resumen.txt`
- `tmp_prueba\temporal\resumen_ud01cp01.txt`
- `tmp_prueba\temporal\resumen_ud02cp03.txt`
- `tmp_prueba\temporal\revision_pendiente.csv`
- Carpetas por alumno con respuesta y corrección.
- `tmp_prueba\pendientes` queda vacío tras corregir.

## Uso previsto en real

Con archivos ya descargados:

```powershell
python corrector_agente.py --contexto-unidad C:\ruta\manual_ud01.txt
```

Forzando actividad:

```powershell
python corrector_agente.py --contexto-unidad C:\ruta\manual_ud01.txt --actividad-codigo ud02cp03
```

Extrayendo desde CARM:

```powershell
python corrector_agente.py --extraer-carm
```

Conservando pendientes durante pruebas:

```powershell
python corrector_agente.py --contexto-unidad C:\ruta\manual_ud01.txt --conservar-pendientes
```

## Decisiones tomadas

- La revisión final sigue siendo manual.
- No se suben notas automáticamente todavía.
- Las correcciones quedan como `borrador_pendiente_de_revision`.
- Se elimina de `pendientes` solo después de copiar la entrega y escribir la corrección.
- Se agrupa por actividad para reducir peticiones a la IA.
- Se mantiene `resumen.txt` global y además `resumen_udXXcpYY.txt` por actividad.
- Los prompts viven fuera del código para adaptar el agente a otros módulos.

## Pendiente / próximos pasos

- Probar `--extraer-carm` en la plataforma real y ajustar selectores si Moodle muestra la tabla de entregas de otra forma.
- Probar en entorno real la extracción de PDF/PPTX/XLSX/ZIP tras instalar `requirements-extraccion.txt`.
- Decidir si merece la pena instalar Tesseract OCR para imágenes.
- Decidir si se añade conversión de `.doc` antiguo con LibreOffice o Word instalado.
- Preparar una pantalla o archivo de validación más cómodo que `revision_pendiente.csv`.
- Diseñar la subida a CARM/Moodle solo después de validar bien el flujo manual.
- Más adelante, añadir medidas de seguridad para credenciales y logs.

## Nota de continuidad

Si este proyecto se retoma desde otro ordenador o cuenta de Codex, empezar leyendo:

1. `ESTADO_PROYECTO.md`
2. `QUICKSTART.md`
3. `corrector_agente.py`
4. `prompts_correccion.json`

Después ejecutar:

```powershell
python prueba_correcciones.py
```

Si esa prueba pasa, el entorno básico está funcionando.
