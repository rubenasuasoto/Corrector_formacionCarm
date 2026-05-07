# Estado del proyecto: agente corrector CARM

Última actualización: 2026-05-07

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

## Relación entre documentos

Se ha decidido separar responsabilidades para evitar duplicación:

- `README.md`: entrada breve y estable para entender qué es el proyecto y cómo arrancar.
- `QUICKSTART.md`: comandos de uso rápido.
- `ESTADO_PROYECTO.md`: memoria viva, decisiones tomadas y próximos pasos.

Si algún detalle operativo cambia, actualizar primero este archivo y después reflejar solo lo imprescindible en `README.md` o `QUICKSTART.md`.

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

También existe un modo sin API:

```powershell
python corrector_agente.py --preparar-prompts-codex
```

Este modo lee o extrae las entregas, las agrupa por actividad y genera prompts en `temporal\prompts_codex` para pegarlos manualmente en Codex/ChatGPT. No llama a OpenAI API y no genera notas finales todavía.

## Extracción ampliada opcional

Con `requirements-extraccion.txt` se añaden lectores para:

- PDF con `pypdf`.
- PPTX con `python-pptx`.
- XLSX con `openpyxl`.
- ZIP leyendo internamente archivos soportados.
- JPG/PNG con OCR mediante `pillow` y `pytesseract`.

Instalación:

```powershell
pip install -r requirements-extraccion.txt
```

El OCR de imágenes requiere instalar Tesseract OCR en Windows y tenerlo disponible en el `PATH`.

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

Los prompts viven en `prompts_correccion.json`.

El código mantiene `PROMPT_SISTEMA` y `PROMPT_CRITERIOS` solo como fallback genérico si falta o falla el JSON. La fuente normal de prompts es `prompts_correccion.json`.

El prompt `default` debe ser general, porque el enunciado real se extrae de CARM y se añade aparte al prompt de corrección. No conviene meter en `default` el enunciado de un caso concreto.

Estructura:

```json
{
  "prompts": {
    "default": {
      "sistema": "...",
      "criterios": "..."
    },
    "_ejemplo_ud02cp03": {
      "sistema": "...",
      "criterios": "..."
    }
  }
}
```

Si existe una clave concreta para la actividad, se usa esa. Si no existe, se usa `default`. Las claves de ejemplo deben llevar prefijo `_ejemplo_` para que no se apliquen accidentalmente a una actividad real.

También se puede usar otro archivo:

```powershell
python corrector_agente.py --prompts C:\ruta\prompts_modulo_02.json
```

## Comandos de prueba

Compilar:

```powershell
python -m py_compile corrector_agente.py prueba_correcciones.py sincronizador_moodle.py
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
- `tmp_prueba\pendientes` queda vacío tras corregir, salvo los casos marcados para revisión manual.

## Uso previsto en real

Diagnóstico de navegación CARM:

```powershell
python corrector_agente.py --diagnosticar-carm
```

Este modo inicia sesión, entra al área personal y al curso, guarda un `diagnostico.json` limpio en `logs_correcciones\diagnostico_carm` y no descarga ni corrige nada. Por defecto no guarda HTML, capturas ni URLs.

Para depurar selectores visualmente se puede usar:

```powershell
python corrector_agente.py --diagnosticar-carm --guardar-evidencias
```

Las evidencias se redactan de forma básica, pero pueden contener datos de alumnos y no deben compartirse.

Listado seguro sin descarga:

```powershell
python corrector_agente.py --solo-listar-carm
```

Este modo entra en CARM y genera `respuestas_extraidas\envios_carm_registros.json` con el mínimo necesario por fila, sin descargar archivos ni corregir.

Para preparar una ejecución real limitada a la unidad 1:

```powershell
python corrector_agente.py --preparar-carm-codex --unidad ud01 --max-entregas-por-prompt 6
```

Este comando hace en una sola sesión de Playwright lo que antes requería cachear, listar y extraer por separado: actualiza cache, registra filas CARM, descarga archivos y genera prompts. El filtro `--unidad ud01` limita actividades y contexto imprimible a la unidad 1. `--max-entregas-por-prompt` divide los prompts en lotes para no consumir el límite de uso de Codex en una sola petición demasiado grande. Por defecto no se recortan respuestas.

Para cerrar el ciclo sin API, el JSON devuelto por Codex/ChatGPT se importa con:

```powershell
python corrector_agente.py --importar-correcciones-codex C:\ruta\correcciones_ud01.json
```

El importador genera `C:\temp\vscodec\temporal\<alumno>\<actividad>.txt`, los resúmenes y `revision_pendiente.csv`. Si existe `prompts_codex\manifiesto_entregas.json`, copia también la entrega original al directorio del alumno.

Para probar la subida a CARM sin guardar:

```powershell
python corrector_agente.py --subir-correcciones-carm correcciones_ud01cp01.json
```

Para publicar de verdad:

```powershell
python corrector_agente.py --subir-correcciones-carm correcciones_ud01cp01.json --publicar-carm
```

La cache local vive en `cache_carm\curso_1592.sqlite`. Guarda solo recursos estables del curso: contenido imprimible, actividades, URLs de grading y enunciados. No guarda entregas, archivos de alumnos, emails, cookies ni capturas.

La cache se usa automáticamente cuando existe. Se puede desactivar en una ejecución con `--sin-cache` o refrescar con `--refrescar-cache`.

Si `.env` define `CARM_COURSE_END_DATE=YYYY-MM-DD` y la fecha ya pasó, la cache se borra automáticamente al iniciar. También puede borrarse manualmente con:

```powershell
python corrector_agente.py --borrar-cache-curso
```

Tras la primera prueba real de CARM se ajustó la lógica para:

- Deduplicar actividades, porque el curso muestra enlaces repetidos desde el bloque de estado/finalización.
- Respetar el enlace de CARM con `filter=require_grading` cuando existe, para trabajar solo con entregas que requieren calificación.
- Mapear la tabla de grading por cabeceras, no por posición fija.
- Leer alumno desde la columna `Nombre / Apellido(s)`.
- Leer solo las columnas necesarias: alumno, estado y archivos enviados.
- Registrar filas sin archivo diferenciando `sin_entrega`, `sin_archivo_detectado` y `error_descarga`.
- Extraer el enunciado de cada caso práctico desde la vista de la actividad antes de entrar al grading.
- Guardar `respuestas_extraidas\envios_carm_registros.json` como auditoría mínima por alumno/fila.
- Usar contexto temporal de Playwright y limpiar cookies/localStorage/sessionStorage al cerrar.
- No guardar HTML/capturas por defecto en diagnóstico; solo con `--guardar-evidencias`.
- Añadir redacción básica de emails, `sesskey` y secretos en HTML diagnóstico cuando se guardan evidencias.

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
- Se añade un modo `--preparar-prompts-codex` para trabajar sin API, usando Codex/ChatGPT manualmente.
- Se añade un modo `--diagnosticar-carm` para probar navegación real sin tocar entregas.
- Se añaden filtros `--unidad` y `--actividad` para limitar ejecuciones reales y reducir tokens.
- Se añade `--max-entregas-por-prompt` para dividir prompts grandes sin recortar respuestas.
- Se añade cache SQLite local para recursos estables del curso, borrable con `--borrar-cache-curso`.
- La cache se usa por defecto y se purga automáticamente si `CARM_COURSE_END_DATE` ya pasó.
- Se mantiene `resumen.txt` global y además `resumen_udXXcpYY.txt` por actividad.
- Los prompts viven fuera del código para adaptar el agente a otros módulos.
- `README.md` se mantiene como resumen de entrada y este archivo como fuente de verdad del estado.
- `prompts_correccion.json` es la fuente de verdad de prompts; los prompts internos del código son solo respaldo.

## Verificación hecha

El 2026-05-07 se comprobó:

```powershell
python -m py_compile corrector_agente.py prueba_correcciones.py sincronizador_moodle.py
python prueba_correcciones.py
```

Resultado:

- Compilación correcta.
- Prueba offline correcta.
- Sin `OPENAI_API_KEY`, el sistema usa corrección de respaldo.
- Sin dependencias opcionales, PPTX/XLSX quedan correctamente marcados como revisión manual.

## Pendiente / próximos pasos

- Probar `--extraer-carm` en la plataforma real y ajustar selectores si Moodle muestra la tabla de entregas de otra forma.
- Añadir importación del JSON devuelto por Codex para convertir el modo sin API en flujo completo.
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
