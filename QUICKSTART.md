# GuÃ­a rÃ¡pida

Antes de tocar nada, revisa `ESTADO_PROYECTO.md`: ahÃ­ queda la memoria del trabajo realizado, decisiones tomadas y prÃ³ximos pasos.

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

Ese arranque abre la app y hace el escaneo inicial normal. Si quieres que ademas prepare prompts automaticamente al iniciar Windows, usa:

```powershell
.\instalar_windows.cmd -InstalarArranque -AutoPrepararAlInicio
```

Para crear tambien un acceso directo en el escritorio:

```powershell
.\instalar_windows.cmd -CrearAccesoDirecto
```

Para instalar dependencias opcionales de lectura avanzada:

```powershell
.\instalar_windows.cmd -ConExtraccion
```

Si una instalacion queda a medias o Windows bloquea Playwright/Chromium:

```powershell
.\reparar_dependencias_windows.cmd
```

Para limpiar el lock de Playwright y reinstalar Chromium:

```powershell
.\reparar_dependencias_windows.cmd -LimpiarPlaywrightLock -ReinstalarChromium
```

Mas incidencias comunes: `SOLUCION_PROBLEMAS_WINDOWS.md`.

Despues inicia la app con:

```powershell
.\iniciar_app_windows.cmd
```

Opciones utiles de inicio:

```powershell
.\iniciar_app_windows.cmd -AbrirNavegador
.\iniciar_app_windows.cmd -AutoPreparar
.\iniciar_app_windows.cmd -SinEscaneoInicial
```

Para comprobar que el equipo esta listo:

```powershell
.\verificar_app_windows.cmd
```

Este comando tambien levanta brevemente el servidor local en un puerto temporal para comprobar token y endpoints basicos.

Justo despues de instalar, antes de configurar credenciales o curso, puedes usar:

```powershell
.\verificar_app_windows.cmd --instalacion
```

Para preparar un release local y guardar un manifiesto en `respuestas_extraidas`:

```powershell
.\preparar_release_windows.cmd
```

Instalacion manual equivalente:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

Para leer formatos ampliados como PDF, PPTX, XLSX o imÃ¡genes con OCR:

```powershell
pip install -r requirements-extraccion.txt
```

Para OCR de imÃ¡genes (`.jpg`, `.png`) tambiÃ©n hace falta tener instalado Tesseract OCR en Windows y que estÃ© disponible en el `PATH`. Esta parte no es prioritaria para la primera versiÃ³n.

## 2. Configurar

Copia `.env.example` a `.env` y rellena las credenciales.

Importante: `.env` contiene usuario y contraseÃ±a de CARM. `OPENAI_API_KEY` solo hace falta si quieres usar la API de OpenAI; el modo solo prompts no la necesita. No subas `.env` al repositorio y rota cualquier clave que se haya compartido por error.

Los prompts de correcciÃ³n estÃ¡n en `prompts_correccion.json`. Puedes editar `default` para el criterio general o crear entradas por actividad, por ejemplo `ud02cp03`, para otros mÃ³dulos o casos prÃ¡cticos.

No metas claves ni credenciales en archivos sueltos. Las credenciales locales van solo en `.env`, que no debe subirse al repositorio.

### OpenAI API

Para el flujo recomendado por API de OpenAI necesitas una clave real en `.env`:

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5-mini
CORRECTION_MODE=api
```

Comprueba la configuracion sin corregir nada:

```powershell
python corrector_agente.py --comprobar-openai-api
```

Si no tienes API key, usa el modo solo prompts:

```env
CORRECTION_MODE=prompt
```

En ese modo la app descarga entregas y genera archivos `.md` pendientes de resolver en la carpeta activa del curso. Con `Separar carpetas por curso` activado, para el curso `1592` sera `C:\temp\vscodec\cursos\1592\pendientes\prompts_codex`. Luego pegas el prompt en Codex/ChatGPT, guardas el JSON devuelto en esa misma carpeta y lo importas desde la interfaz.

## 2.1. Varios cursos CARM

Desde la interfaz:

1. Abre configuracion.
2. En el campo de curso puedes usar el area personal `https://formacion.carm.es/my/index.php` para configurar la deteccion.
3. Pulsa `Detectar cursos CARM`.
4. Elige el curso activo en el selector superior.
5. Si vas a trabajar con varios cursos, activa `Separar carpetas por curso`.
6. Marca los cursos que quieres incluir en `Cursos para autoprompteo` y pulsa `Guardar seleccion`.

Variables relacionadas:

```env
CARM_DASHBOARD_URL=https://formacion.carm.es/my/index.php
CARM_COURSE_URL=
```

`CARM_DASHBOARD_URL` sirve para listar cursos. `CARM_COURSE_URL` es el curso activo concreto y lo rellena la interfaz al elegir uno; no hay curso por defecto.

Con `Separar carpetas por curso`, cada curso usa:

```text
C:\temp\vscodec\cursos\<course_id>\pendientes
C:\temp\vscodec\cursos\<course_id>\temporal
```

Si hay varios cursos seleccionados, el autoprompteo al iniciar los procesa de uno en uno. La app no llama a la API ni sube a CARM automaticamente.

Si no hay curso activo todavia, `Escanear ahora` y el arranque de la app detectan cursos desde el area personal. Cuando elijas uno, ya podra actualizar cache, preparar prompts y mostrar el CSV de ese curso.

En configuracion, `Estado por curso` muestra de un vistazo si cada curso seleccionado tiene cache, prompts, JSON de correccion, filas en CSV e incidencias que bloquearian la subida.

La deteccion oculta enlaces auxiliares de CARM como `FAQS` o `CARM - Curso CARM`. Si esos nombres reaparecen, pulsa `Detectar cursos CARM` de nuevo y revisa el listado filtrado.

## 3. Preparar prompts para Codex sin API

Para que el agente lea las entregas, las agrupe por actividad y genere archivos listos para pegar en Codex/ChatGPT, sin llamar a la API de OpenAI:

```powershell
python corrector_agente.py --preparar-carm-codex --unidad ud01
```

Salidas:

- `C:\temp\vscodec\cursos\<course_id>\pendientes\prompts_codex\prompt_ud01cp01.md`
- `C:\temp\vscodec\cursos\<course_id>\pendientes\prompts_codex\prompt_ud02cp03.md`
- `C:\temp\vscodec\cursos\<course_id>\pendientes\prompts_codex\manifiesto_entregas.json`

Si `Separar carpetas por curso` esta desactivado, se usan las rutas globales antiguas `C:\temp\vscodec\pendientes` y `C:\temp\vscodec\temporal`.

El archivo `.md` se copia entero en Codex/ChatGPT. Codex debe devolver un JSON con las correcciones.

### Resolver prompts sin API

El flujo sin API actual no usa Codex CLI integrado. Abre Codex/ChatGPT aparte, ejecuta `$C` o pega el prompt, guarda los `*_correccion.json` en la carpeta de prompts y vuelve a la interfaz para pulsar `Importar JSON a revision`.

## 4. Corregir archivos reales ya descargados

Coloca las entregas en la carpeta `pendientes` activa. Con carpetas por curso activadas: `C:\temp\vscodec\cursos\<course_id>\pendientes`.

```powershell
python corrector_agente.py --preparar-prompts-codex
```

Para usar otro archivo de prompts:

```powershell
python corrector_agente.py --preparar-prompts-codex --prompts C:\ruta\prompts_modulo_02.json
```

Salidas:

- `C:\temp\vscodec\cursos\<course_id>\temporal\<alumno>\ud01cp01.ext`: copia de la entrega.
- `C:\temp\vscodec\cursos\<course_id>\temporal\<alumno>\ud01cp01.txt`: correccion generada.
- `C:\temp\vscodec\cursos\<course_id>\temporal\resumen.txt`: resumen global.
- `C:\temp\vscodec\cursos\<course_id>\temporal\resumen_ud01cp01.txt`: resumen especifico de esa unidad y caso practico.
- `C:\temp\vscodec\cursos\<course_id>\temporal\revision_pendiente.csv`: hoja para revisar notas y feedback antes de subir.

El cÃ³digo `ud01cp01` cambia segÃºn la actividad. Si se extrae desde CARM, el agente intenta detectarlo desde el nombre de la unidad y del caso prÃ¡ctico. Si corriges archivos descargados a mano, puedes indicarlo con `--actividad-codigo ud02cp03` o meter los archivos en una subcarpeta con ese nombre.

Si la respuesta del alumno ya es `.txt`, se copia como `ud01cp01_respuesta.txt` para no pisar la correcciÃ³n `ud01cp01.txt`.

## 5. Diagnosticar navegaciÃ³n real en CARM

Antes de descargar entregas reales, ejecuta un diagnÃ³stico:

```powershell
python corrector_agente.py --diagnosticar-carm
```

Esto abre Chromium, inicia sesiÃ³n en CARM, entra al curso configurado en `.env` y guarda un diagnÃ³stico limpio en:

- `logs_correcciones\diagnostico_carm\diagnostico.json`

Por defecto no guarda HTML, capturas ni URLs. Si hace falta depurar selectores visualmente:

```powershell
python corrector_agente.py --diagnosticar-carm --guardar-evidencias
```

Las evidencias se redactan de forma bÃ¡sica, pero pueden contener datos de alumnos. Ãšsalas solo para depurar y no las compartas.

Si quieres que el navegador se quede abierto al final para mirar la pantalla:

```powershell
python corrector_agente.py --diagnosticar-carm --mantener-navegador
```

Con este diagnÃ³stico ajustamos selectores si Moodle no muestra actividades o entregas como espera el agente.

Para listar entregas que requieren calificaciÃ³n sin descargar archivos:

```powershell
python corrector_agente.py --solo-listar-carm
```

Esto genera `respuestas_extraidas\envios_carm_registros.json` con alumno, actividad, estado y si hay archivo, pero sin descargar entregas ni corregir.

Para preparar la primera ejecuciÃ³n real solo con la unidad 1:

```powershell
python corrector_agente.py --solo-listar-carm --unidad ud01
```

## 6. Cachear recursos estables del curso

Para no releer en cada ejecuciÃ³n el contenido imprimible y los enunciados:

```powershell
python corrector_agente.py --cachear-curso --unidad ud01
```

Esto guarda solo recursos didÃ¡cticos y metadatos de actividades en:

- `cache_carm\curso_1592.sqlite`

No guarda respuestas de alumnos, archivos enviados, emails, cookies ni capturas.

La cache se usa automÃ¡ticamente en operaciones CARM cuando existe. Para preparar prompts en una sola sesiÃ³n de Playwright:

```powershell
python corrector_agente.py --preparar-carm-codex --unidad ud01 --max-entregas-por-prompt 6
```

Para forzar actualizaciÃ³n:

```powershell
python corrector_agente.py --cachear-curso --unidad ud01 --refrescar-cache
```

Para borrar la cache al terminar el curso:

```powershell
python corrector_agente.py --borrar-cache-curso
```

TambiÃ©n puedes poner en `.env`:

```env
CARM_COURSE_END_DATE=2026-06-02
```

Si esa fecha ya pasÃ³, la cache se borra automÃ¡ticamente al iniciar. Para ignorar la cache en una ejecuciÃ³n concreta:

```powershell
python corrector_agente.py --extraer-carm --preparar-prompts-codex --unidad ud01 --sin-cache
```

## 7. Extraer desde CARM

```powershell
python corrector_agente.py --extraer-carm
```

En este modo descarga los archivos entregados desde CARM a la carpeta activa de pendientes. Con carpetas por curso activadas sera `C:\temp\vscodec\cursos\<course_id>\pendientes\<actividad>\`.

Para extraer desde CARM y generar solo prompts para Codex, sin API:

```powershell
python corrector_agente.py --preparar-carm-codex
```

Primera unidad, optimizando tamaÃ±o de prompts sin recortar respuestas:

```powershell
python corrector_agente.py --preparar-carm-codex --unidad ud01 --max-entregas-por-prompt 6
```

Esto abre Playwright una sola vez, entra en CARM, actualiza la cache del curso, registra las filas que requieren calificaciÃ³n, descarga los archivos, extrae el contenido imprimible de `ud01` y divide las entregas en lotes de hasta 6 por prompt. No usa API.

## 8. Flujo principal actual

Primero prepara prompts sin publicar en CARM ni gastar API:

```powershell
python corrector_agente.py --preparar-carm-codex --unidad ud01 --max-entregas-por-prompt 0
```

Esto entra en CARM, descarga entregas, genera prompts pendientes y archiva los archivos ya convertidos en prompt. No llama a la API y no publica en CARM. Con carpetas por curso activadas, los prompts quedan en `C:\temp\vscodec\cursos\<course_id>\pendientes\prompts_codex`.

Despues resuelve los prompts con API desde la interfaz o con Codex/IA externa. Si usas `$C`, vuelve al panel principal, selecciona un `*_correccion.json` o `Todos los JSON pendientes` en "Archivo de correcciones" y pulsa `Importar JSON a revision`; la app lo pasara a `revision_pendiente.csv`.

Cuando hayas revisado, sube a CARM con subida asistida:

```powershell
python corrector_agente.py --subir-correcciones-carm C:\temp\vscodec\cursos\<course_id>\temporal\revision_pendiente.csv --subida-asistida-carm
```

La app rellena nota y feedback; el docente pulsa `Guardar cambios` en CARM. Las filas confirmadas o ya gestionadas se eliminan del CSV.
TambiÃ©n puedes abrir la interfaz local:

```powershell
python interfaz_app.py
```

La aplicaciÃ³n queda en `http://127.0.0.1:8765` y permite preparar, previsualizar y publicar desde una pantalla Ãºnica.

En la interfaz, el flujo con API estÃ¡ separado en dos pasos: primero `Preparar prompts`, que no gasta API, y despuÃ©s `Corregir prompts con API`, que envÃ­a los prompts acumulados y deja generado `revision_pendiente.csv` para la subida asistida.

Antes de llamar a la API, el agente estima el tamaÃ±o de cada prompt. Si supera el aviso configurado registra un warning; si supera el lÃ­mite de seguridad bloquea el envÃ­o y pide volver a preparar con menos entregas por prompt. Los umbrales se pueden ajustar con `--openai-warn-tokens-prompt` y `--openai-max-tokens-prompt`.

Si un lote sale demasiado grande, baja el lote a 3 o 4:

```powershell
python corrector_agente.py --preparar-carm-codex --unidad ud01 --max-entregas-por-prompt 4
```

Evita usar `--max-caracteres-entrega` salvo que sea imprescindible, porque recorta respuestas y puede empeorar la calidad.

Cuando Codex/ChatGPT devuelva las correcciones en JSON, guÃ¡rdalas en un archivo y conviÃ©rtelas en salidas revisables:

```powershell
python corrector_agente.py --importar-correcciones-codex C:\ruta\correcciones_ud01.json
```

El importador acepta una lista JSON directa o un objeto con clave `correcciones`. TambiÃ©n entiende respuestas pegadas dentro de un bloque de cÃ³digo `json`. Campos mÃ­nimos por entrega: `alumno`, `actividad`, `nota` y `retroalimentacion` o `comentario`.

## 9. Previsualizar o subir a CARM

Primero prueba en modo previsualizaciÃ³n. Este modo abre CARM, busca el alumno y la actividad, rellena nota y retroalimentaciÃ³n, pero no pulsa guardar:

```powershell
python corrector_agente.py --subir-correcciones-carm correcciones_ud01cp01.json
```

TambiÃ©n puedes previsualizar directamente el CSV revisable generado por la API:

```powershell
python corrector_agente.py --subir-correcciones-carm C:\temp\vscodec\cursos\<course_id>\temporal\revision_pendiente.csv
```

El navegador queda abierto para revisar el formulario. Para terminar la previsualizaciÃ³n, cierra la pestaÃ±a de Chromium o detÃ©n la tarea desde la interfaz.

Cuando hayas comprobado que el formulario se rellena bien, publica de verdad con:

```powershell
python corrector_agente.py --subir-correcciones-carm correcciones_ud01cp01.json --publicar-carm
```

Con varias correcciones de la misma actividad, se intenta usar `Guardar cambios y mostrar siguiente` entre alumnos. En la Ãºltima correcciÃ³n del lote usa `Guardar cambios` para no avanzar de mÃ¡s.

Cada intento deja registro en `respuestas_extraidas\subida_carm_previsualizacion.json` o `respuestas_extraidas\subida_carm_publicada.json`.

Tras importar un JSON de Codex al CSV, el prompt exacto y su `*_correccion.json` se mueven a `pendientes\prompts_codex\archivados\...` para que no vuelvan a aparecer como pendientes. Tras una publicacion real o una subida asistida completada, tambien se archivan los resumenes usados. Una previsualizacion no archiva nada.

Tras generar prompts, las entregas usadas se mueven a `pendientes\archivados_prompt\...`. Si necesitas repetir exactamente el mismo lote para una prueba, usa `--conservar-pendientes`.

La extracciÃ³n real deja auditorÃ­a en:

- `respuestas_extraidas\envios_descargados.json`: archivos descargados y dueÃ±o de cada archivo.
- `respuestas_extraidas\envios_carm_registros.json`: registro mÃ­nimo por fila de alumno, incluyendo actividad, estado, si tenÃ­a archivo, si no entregÃ³ o si hubo error de descarga.

Cuando una entrega ya ha sido copiada a `temporal` y tiene su correcciÃ³n generada, se elimina automÃ¡ticamente de `pendientes`. Para pruebas en las que quieras conservar los originales, usa `--conservar-pendientes`.

Los `.txt`, `.docx`, `.odt`, `.rtf`, `.csv`, `.html`, `.json`, `.xml` y similares se intentan leer automÃ¡ticamente. Con las dependencias opcionales tambiÃ©n se intentan leer `.pdf`, `.pptx`, `.xlsx`, `.zip`, `.jpg` y `.png`. Los multimedia, `.doc` antiguo, comprimidos no soportados o formatos no extraÃ­bles quedan marcados en `revision_pendiente.csv` como `revision_manual_necesaria` y no se eliminan de `pendientes`.

El flujo normal deja todo revisable antes de publicar. Solo se guarda en CARM cuando ejecutas explÃ­citamente `--publicar-carm`.
