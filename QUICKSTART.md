# Guía rápida

Antes de tocar nada, revisa `ESTADO_PROYECTO.md`: ahí queda la memoria del trabajo realizado, decisiones tomadas y próximos pasos.

## 1. Instalar

En Windows, usa el instalador del proyecto:

```powershell
.\instalar_windows.cmd
```

Esto crea `.venv`, instala dependencias, instala Chromium de Playwright y crea `.env` si no existe.

Para dejar tambien el arranque automatico en bandeja:

```powershell
.\instalar_windows.cmd -InstalarArranque
```

Para instalar dependencias opcionales de lectura avanzada:

```powershell
.\instalar_windows.cmd -ConExtraccion
```

Despues inicia la app con:

```powershell
.\iniciar_app_windows.cmd
```

Instalacion manual equivalente:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

Para leer formatos ampliados como PDF, PPTX, XLSX o imágenes con OCR:

```powershell
pip install -r requirements-extraccion.txt
```

Para OCR de imágenes (`.jpg`, `.png`) también hace falta tener instalado Tesseract OCR en Windows y que esté disponible en el `PATH`. Esta parte no es prioritaria para la primera versión.

## 2. Configurar

Copia `.env.example` a `.env` y rellena las credenciales.

Importante: `.env` contiene usuario y contraseña de CARM. `OPENAI_API_KEY` solo hace falta si quieres usar la API de OpenAI; el flujo recomendado con Codex CLI no la necesita. No subas `.env` al repositorio y rota cualquier clave que se haya compartido por error.

Los prompts de corrección están en `prompts_correccion.json`. Puedes editar `default` para el criterio general o crear entradas por actividad, por ejemplo `ud02cp03`, para otros módulos o casos prácticos.

No metas claves ni credenciales en archivos sueltos. Las credenciales locales van solo en `.env`, que no debe subirse al repositorio.

## 3. Probar sin CARM y sin IA

```powershell
python prueba_correcciones.py
```

Esto crea envíos ficticios en `tmp_prueba\pendientes`, genera correcciones de respaldo y deja las salidas en `tmp_prueba\temporal`.

## 4. Preparar prompts para Codex sin API

Para que el agente lea las entregas, las agrupe por actividad y genere archivos listos para pegar en Codex/ChatGPT, sin llamar a la API de OpenAI:

```powershell
python corrector_agente.py --contexto-unidad C:\ruta\manual_ud01.txt --preparar-prompts-codex
```

Salidas:

- `C:\temp\vscodec\temporal\prompts_codex\prompt_ud01cp01.md`
- `C:\temp\vscodec\temporal\prompts_codex\prompt_ud02cp03.md`
- `C:\temp\vscodec\temporal\prompts_codex\manifiesto_entregas.json`

El archivo `.md` se copia entero en Codex/ChatGPT. Codex debe devolver un JSON con las correcciones.

## 5. Corregir archivos reales ya descargados

Coloca las entregas en `C:\temp\vscodec\pendientes` con el nombre del alumno como nombre de archivo.

```powershell
python corrector_agente.py --contexto-unidad C:\ruta\manual_ud01.txt
```

Para usar otro archivo de prompts:

```powershell
python corrector_agente.py --contexto-unidad C:\ruta\manual_ud01.txt --prompts C:\ruta\prompts_modulo_02.json
```

Salidas:

- `C:\temp\vscodec\temporal\<alumno>\ud01cp01.ext`: copia de la entrega.
- `C:\temp\vscodec\temporal\<alumno>\ud01cp01.txt`: corrección generada.
- `C:\temp\vscodec\temporal\resumen.txt`: resumen global.
- `C:\temp\vscodec\temporal\resumen_ud01cp01.txt`: resumen específico de esa unidad y caso práctico.
- `C:\temp\vscodec\temporal\revision_pendiente.csv`: hoja para revisar notas y feedback antes de subir.

El código `ud01cp01` cambia según la actividad. Si se extrae desde CARM, el agente intenta detectarlo desde el nombre de la unidad y del caso práctico. Si corriges archivos descargados a mano, puedes indicarlo con `--actividad-codigo ud02cp03` o meter los archivos en una subcarpeta con ese nombre.

Si la respuesta del alumno ya es `.txt`, se copia como `ud01cp01_respuesta.txt` para no pisar la corrección `ud01cp01.txt`.

## 6. Diagnosticar navegación real en CARM

Antes de descargar entregas reales, ejecuta un diagnóstico:

```powershell
python corrector_agente.py --diagnosticar-carm
```

Esto abre Chromium, inicia sesión en CARM, entra al curso configurado en `.env` y guarda un diagnóstico limpio en:

- `logs_correcciones\diagnostico_carm\diagnostico.json`

Por defecto no guarda HTML, capturas ni URLs. Si hace falta depurar selectores visualmente:

```powershell
python corrector_agente.py --diagnosticar-carm --guardar-evidencias
```

Las evidencias se redactan de forma básica, pero pueden contener datos de alumnos. Úsalas solo para depurar y no las compartas.

Si quieres que el navegador se quede abierto al final para mirar la pantalla:

```powershell
python corrector_agente.py --diagnosticar-carm --mantener-navegador
```

Con este diagnóstico ajustamos selectores si Moodle no muestra actividades o entregas como espera el agente.

Para listar entregas que requieren calificación sin descargar archivos:

```powershell
python corrector_agente.py --solo-listar-carm
```

Esto genera `respuestas_extraidas\envios_carm_registros.json` con alumno, actividad, estado y si hay archivo, pero sin descargar entregas ni corregir.

Para preparar la primera ejecución real solo con la unidad 1:

```powershell
python corrector_agente.py --solo-listar-carm --unidad ud01
```

## 7. Cachear recursos estables del curso

Para no releer en cada ejecución el contenido imprimible y los enunciados:

```powershell
python corrector_agente.py --cachear-curso --unidad ud01
```

Esto guarda solo recursos didácticos y metadatos de actividades en:

- `cache_carm\curso_1592.sqlite`

No guarda respuestas de alumnos, archivos enviados, emails, cookies ni capturas.

La cache se usa automáticamente en operaciones CARM cuando existe. Para preparar prompts en una sola sesión de Playwright:

```powershell
python corrector_agente.py --preparar-carm-codex --unidad ud01 --max-entregas-por-prompt 6
```

Para forzar actualización:

```powershell
python corrector_agente.py --cachear-curso --unidad ud01 --refrescar-cache
```

Para borrar la cache al terminar el curso:

```powershell
python corrector_agente.py --borrar-cache-curso
```

También puedes poner en `.env`:

```env
CARM_COURSE_END_DATE=2026-06-02
```

Si esa fecha ya pasó, la cache se borra automáticamente al iniciar. Para ignorar la cache en una ejecución concreta:

```powershell
python corrector_agente.py --extraer-carm --preparar-prompts-codex --unidad ud01 --sin-cache
```

## 8. Extraer desde CARM

```powershell
python corrector_agente.py --extraer-carm
```

En este modo descarga los archivos entregados desde CARM a `C:\temp\vscodec\pendientes\<actividad>\` con el nombre del alumno, y corrige cada actividad en lote para hacer una petición de IA por unidad/caso práctico.

Para extraer desde CARM y generar solo prompts para Codex, sin API:

```powershell
python corrector_agente.py --preparar-carm-codex
```

Primera unidad, optimizando tamaño de prompts sin recortar respuestas:

```powershell
python corrector_agente.py --preparar-carm-codex --unidad ud01 --max-entregas-por-prompt 6
```

Esto abre Playwright una sola vez, entra en CARM, actualiza la cache del curso, registra las filas que requieren calificación, descarga los archivos, extrae el contenido imprimible de `ud01` y divide las entregas en lotes de hasta 6 por prompt. No usa API.

## 9. Dos comandos principales

Primero prepara las correcciones sin publicar en CARM:

```powershell
python corrector_agente.py --flujo-correccion-carm --unidad ud01 --max-entregas-por-prompt 6
```

Esto entra en CARM, descarga entregas, genera prompts, corrige con Codex CLI e importa las salidas locales. No publica en CARM. El JSON combinado queda en `C:\temp\vscodec\temporal\prompts_codex\correcciones_codex_combinadas.json`.

Después, cuando hayas revisado, publica en CARM:

```powershell
python corrector_agente.py --subir-correcciones-carm C:\temp\vscodec\temporal\prompts_codex\correcciones_codex_combinadas.json --publicar-carm
```

Las respuestas de Codex quedan en `C:\temp\vscodec\temporal\prompts_codex\`. Este flujo usa tu sesión de Codex CLI, no `OPENAI_API_KEY`.

También puedes abrir la interfaz local:

```powershell
python interfaz_app.py
```

La aplicación queda en `http://127.0.0.1:8765` y permite preparar, previsualizar y publicar desde una pantalla única.

Si un lote sale demasiado grande, baja el lote a 3 o 4:

```powershell
python corrector_agente.py --preparar-carm-codex --unidad ud01 --max-entregas-por-prompt 4
```

Evita usar `--max-caracteres-entrega` salvo que sea imprescindible, porque recorta respuestas y puede empeorar la calidad.

Cuando Codex/ChatGPT devuelva las correcciones en JSON, guárdalas en un archivo y conviértelas en salidas revisables:

```powershell
python corrector_agente.py --importar-correcciones-codex C:\ruta\correcciones_ud01.json
```

El importador acepta una lista JSON directa o un objeto con clave `correcciones`. También entiende respuestas pegadas dentro de un bloque de código `json`. Campos mínimos por entrega: `alumno`, `actividad`, `nota` y `retroalimentacion` o `comentario`.

## 10. Previsualizar o subir a CARM

Primero prueba en modo previsualización. Este modo abre CARM, busca el alumno y la actividad, rellena nota y retroalimentación, pero no pulsa guardar:

```powershell
python corrector_agente.py --subir-correcciones-carm correcciones_ud01cp01.json
```

El navegador queda abierto para revisar el formulario. Para terminar la previsualización, cierra la pestaña de Chromium o detén la tarea desde la interfaz.

Cuando hayas comprobado que el formulario se rellena bien, publica de verdad con:

```powershell
python corrector_agente.py --subir-correcciones-carm correcciones_ud01cp01.json --publicar-carm
```

Con varias correcciones de la misma actividad, se intenta usar `Guardar cambios y mostrar siguiente` entre alumnos. En la última corrección del lote usa `Guardar cambios` para no avanzar de más.

Cada intento deja registro en `respuestas_extraidas\subida_carm_previsualizacion.json` o `respuestas_extraidas\subida_carm_publicada.json`.

Tras una publicacion real o una subida asistida completada, los prompts y JSON usados se mueven a `temporal\prompts_codex\archivados\...` para no reutilizarlos por error. Una previsualizacion no archiva nada.

Tras generar prompts, las entregas usadas se mueven a `pendientes\archivados_prompt\...`. Si necesitas repetir exactamente el mismo lote para una prueba, usa `--conservar-pendientes`.

La extracción real deja auditoría en:

- `respuestas_extraidas\envios_descargados.json`: archivos descargados y dueño de cada archivo.
- `respuestas_extraidas\envios_carm_registros.json`: registro mínimo por fila de alumno, incluyendo actividad, estado, si tenía archivo, si no entregó o si hubo error de descarga.

Cuando una entrega ya ha sido copiada a `temporal` y tiene su corrección generada, se elimina automáticamente de `pendientes`. Para pruebas en las que quieras conservar los originales, usa `--conservar-pendientes`.

Los `.txt`, `.docx`, `.odt`, `.rtf`, `.csv`, `.html`, `.json`, `.xml` y similares se intentan leer automáticamente. Con las dependencias opcionales también se intentan leer `.pdf`, `.pptx`, `.xlsx`, `.zip`, `.jpg` y `.png`. Los multimedia, `.doc` antiguo, comprimidos no soportados o formatos no extraíbles quedan marcados en `revision_pendiente.csv` como `revision_manual_necesaria` y no se eliminan de `pendientes`.

El flujo normal deja todo revisable antes de publicar. Solo se guarda en CARM cuando ejecutas explícitamente `--publicar-carm`.
