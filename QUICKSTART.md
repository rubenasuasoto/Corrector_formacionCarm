# Guía rápida

Antes de tocar nada, revisa `ESTADO_PROYECTO.md`: ahí queda la memoria del trabajo realizado, decisiones tomadas y próximos pasos.

## Ruta recomendada actual

Para uso real, el camino normal es este:

1. Iniciar la app con `.\iniciar_app_windows.cmd`.
2. Detectar o elegir curso desde la interfaz.
3. Preparar prompts desde la interfaz o con `--preparar-carm-codex`.
4. Corregir con API o resolver los prompts fuera de la app y luego pulsar `Importar JSON a revision`.
5. Revisar `revision_pendiente.csv` desde la interfaz.
6. Usar subida asistida: la app rellena nota y feedback, pero el docente guarda en CARM.

No uses comandos directos de publicacion: esa ruta esta desactivada. La subida asistida es el flujo que mantiene revision humana y limpia el CSV al confirmar cada caso.

Si una correccion genera dudas, usa la seccion `Revision manual` del panel: puedes apartar el caso, escribir una nota para Codex y crear un prompt de recorreccion. Las filas marcadas como `revision_manual_necesaria` bloquean la subida asistida hasta resolverlas.

## Continuar en otro ordenador

Para retomar el proyecto en otro Windows, usa el paquete ZIP guiado o esta carpeta de proyecto sin copiar datos sensibles. No copies `.env`, `cache_carm`, `logs_correcciones`, `respuestas_extraidas`, `correcciones_validadas`, `.venv` ni carpetas de alumnos.

Pasos recomendados:

1. Ejecuta `.\INSTALAR_CORRECTOR_CARM.cmd`.
2. Elige carpeta de instalacion y carpeta de datos.
3. Abre el panel con `.\ABRIR_CORRECTOR_CARM.cmd`.
4. Configura credenciales CARM desde la interfaz.
5. Detecta cursos y selecciona el curso activo.
6. Ejecuta `.\verificar_app_windows.cmd --instalacion`.
7. Si vas a usar Codex sin API, deja marcada la opcion de Codex en el instalador. Si prefieres hacerlo manualmente, instala Node.js LTS y el CLI oficial:

```powershell
winget install --id OpenJS.NodeJS.LTS --source winget
npm i -g @openai/codex
codex login
```

La app debe detectar `C:\Users\<usuario>\AppData\Roaming\npm\codex.cmd`. No uses el `codex.exe` de la extension de VS Code para este flujo.

Si el ordenador no permite `winget`, instala Node.js LTS desde la pagina oficial, abre una terminal nueva y repite `npm i -g @openai/codex`.

La app queda registrada en **Aplicaciones instaladas** de Windows como `Corrector CARM`. Para quitarla desde consola:

```powershell
.\desinstalar_windows.cmd
```

Por defecto conserva datos locales. En la desinstalacion grafica puedes elegir si borrar pendientes/prompts, CSV temporales o cursos/cache/proyectos Codex. Desde consola puedes usar `-EliminarDatos` para borrar todo o `-EliminarPendientes`, `-EliminarTemporal` y `-EliminarCursos` para borrar solo una parte.

Para OCR de PDF escaneados o imagenes, usa el instalador guiado o ejecuta:

```powershell
.\instalar_ocr_windows.cmd
```

## Documentacion de apoyo

- `ESTADO_PROYECTO.md`: estado real y decisiones recientes.
- `ARQUITECTURA_PROYECTO.md`: archivos activos, obsoletos y artefactos locales.
- `CUMPLIMIENTO_NORMATIVO.md`: RGPD, LOPDGDD, ENS, IA y revision humana.
- `SEGURIDAD_ASVS.md` y `SEGURIDAD_CVSS.md`: controles y priorizacion de riesgos.
- `SOLUCION_PROBLEMAS_WINDOWS.md`: Playwright, dependencias, bandeja, puerto local y reparacion.
- `RELEASE_CHECKLIST.md`: comprobaciones antes de una sesion real.
- `CIERRE_APP_LOCAL.md`: puntos pendientes antes de abrir Fase 5.

## 1. Instalar

En Windows, la entrada recomendada para una instalacion guiada es:

```powershell
.\INSTALAR_CORRECTOR_CARM.cmd
```

Esto detecta Python 3.12+ y, si falta, intenta instalarlo con `winget`; despues crea `.venv`, instala dependencias base y de extraccion, instala Chromium de Playwright si falta, crea `.env` si no existe y deja accesos directos para abrir el panel. La ventana del instalador muestra una comprobacion previa de Python, carpetas, OCR opcional, Node.js/npm/Codex y avisa si falta iniciar sesion en Codex. La primera configuracion de credenciales se hace desde la interfaz si faltan.

La instalacion queda visible en **Configuracion de Windows > Aplicaciones instaladas**. La desinstalacion normal conserva los datos locales; si quieres borrar todo, usa `desinstalar_windows.ps1 -EliminarDatos`; si quieres borrar solo una parte, usa `-EliminarPendientes`, `-EliminarTemporal` o `-EliminarCursos`.

El asistente permite elegir carpeta de instalacion y carpeta de datos. En esa carpeta de datos se crean `pendientes`, `temporal` y `cursos`; con separacion por curso activada, cada curso guarda ahi sus prompts, CSV y resumenes. El inicio con Windows aparece activado por defecto y se puede desmarcar. La fase tecnica se ejecuta oculta y se ve como progreso dentro de la ventana del instalador, sin terminales visibles para el usuario final. Tambien puedes dejar activada la opcion de Codex: el instalador detecta Node.js/npm, instala Node.js LTS con `winget` si falta e instala/actualiza el CLI oficial `@openai/codex`. Si `winget` no esta disponible, Python/Node deberan instalarse manualmente. Para corregir sin API tendras que iniciar sesion una vez con `codex login`. No se usa el Codex de VS Code para este flujo.

El progreso del instalador se muestra como una lista de pasos integrada: Python, entorno virtual, dependencias, OCR, Codex, Chromium, configuracion local, lanzador, verificacion, arranque, accesos y desinstalador. Si OCR falla, la instalacion puede continuar y los documentos escaneados quedan para revision manual.

En la interfaz, abre `Configuracion` con el icono de engranaje. La configuracion esta separada en `Pantalla`, `Carpetas`, `Curso y automatizacion`, `Windows`, `Estado`, `OpenAI` y `Avanzado`. En `Pantalla` puedes guardar tema automatico de Windows, claro u oscuro, tamaño de letra, altura del registro y alto contraste.

Si reinstalas sobre carpetas existentes, el instalador actualiza archivos de la app, conserva `.env` y reutiliza datos/configuracion compatibles. Las bases de trabajo deben quedar como `...\pendientes`, `...\temporal` y `...\cursos`; cada curso se guarda dentro de `cursos\<course_id>`.

Para automatizar correcciones con Codex sin API hace falta el Codex CLI oficial. Si la instalacion automatica falla o el equipo no permite `winget`, instala Node.js LTS manualmente y abre una terminal nueva. En Windows, la app llama a `codex.cmd` para evitar que PowerShell bloquee `codex.ps1` por politica de ejecucion:

```powershell
winget install --id OpenJS.NodeJS.LTS --source winget
npm i -g @openai/codex
codex login
```

Para abrir el panel despues:

```powershell
.\ABRIR_CORRECTOR_CARM.cmd
```

Los scripts tecnicos siguen disponibles para mantenimiento:

```powershell
.\instalar_windows.cmd
.\iniciar_app_windows.cmd
```

Para dejar tambien el arranque automatico en bandeja:

```powershell
.\instalar_windows.cmd -InstalarArranque
```

Ese arranque abre la app y hace el escaneo inicial normal. Si quieres que ademas prepare prompts automaticamente al iniciar Windows, usa:

```powershell
.\instalar_windows.cmd -InstalarArranque -AutoPrepararAlInicio
```

Desde la interfaz, en `Configuracion > Windows`, tambien puedes preparar un proyecto local por curso para Codex App en `C:\temp\vscodec\cursos\<course_id>\codex_project` con contexto didactico y enunciados, sin entregas ni datos personales de alumnos. El proyecto de Codex incluye `contexto_didactico.md` como indice, `actividades.json` con enunciados y `unidades/*.md` con el contenido imprimible completo de cada unidad. Asi Codex puede usar mas contexto que la API sin aumentar el coste de tokens de cada peticion. Si Codex Desktop llega a exponer un CLI oficial en Windows, la app podra abrirlo junto al Corrector al iniciar Windows.

Esa carpeta es solo para Codex App. No se versiona, no se empaqueta en el ZIP de instalacion y no se usa para subir nada a CARM.

El proyecto Codex se prepara automaticamente cuando seleccionas un curso que ya tiene cache didactica. Si aun no hay cache, se prepara al terminar el escaneo del curso.

La apertura automatica requiere un CLI ejecutable de Codex Desktop. La app no usa el `codex.exe` de la extension de VS Code para este flujo.

Si Codex Desktop tiene abierto el proyecto, puede bloquear temporalmente algun archivo de `codex_project`. En ese caso la interfaz abre el proyecto existente sin refrescarlo y muestra un aviso; al cerrar Codex o cambiar de curso podra actualizarlo de nuevo.

Para crear tambien un acceso directo en el escritorio:

```powershell
.\instalar_windows.cmd -CrearAccesoDirecto
```

Para generar un paquete ZIP guiado para otro Windows:

```powershell
.\crear_paquete_windows.cmd
```

El paquete se crea en el Escritorio y no incluye `.env`, `.venv`, logs, cache ni entregas/correcciones generadas.

Para generar un instalador descargable de un solo archivo, sin pedir al usuario que descomprima nada:

```powershell
.\crear_instalador_setup_windows.cmd
```

Esto crea `Corrector_CARM_<version>_Setup_<fecha>.exe` en el Escritorio. Al abrirlo, extrae temporalmente el paquete limpio y lanza el instalador guiado actual. Como no esta firmado digitalmente, Windows puede mostrar aviso de editor desconocido.

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

Para leer formatos ampliados como PDF, PDF escaneados, PPTX/PPTM, XLSX/XLSM, ODT/ODS/ODP, EPUB, ZIP o imágenes con OCR:

```powershell
pip install -r requirements-extraccion.txt
```

Los PDF que son una imagen escaneada se leen en dos pasos: la app renderiza el PDF con `pypdfium2` y después aplica OCR con Tesseract. Para OCR de imágenes o PDF escaneados hace falta tener instalado Tesseract OCR en Windows y que esté disponible en el `PATH`; si falta, la entrega pasará a revisión manual en vez de recibir un 0 automático.

El instalador guiado incluye una casilla para instalar OCR automáticamente. Si Windows no permite instalarlo, la app queda instalada igualmente y esos archivos pasan a revisión manual.

Para intentar instalar el motor OCR desde Windows:

```powershell
.\instalar_ocr_windows.cmd
```

## 2. Configurar

Copia `.env.example` a `.env` y rellena las credenciales.

Importante: `.env` contiene usuario y contraseña de CARM. `OPENAI_API_KEY` solo hace falta si quieres usar la API de OpenAI; el modo solo prompts no la necesita. No subas `.env` al repositorio y rota cualquier clave que se haya compartido por error.

Los prompts de corrección están en `prompts_correccion.json`. Puedes editar `default` para el criterio general o crear entradas por actividad, por ejemplo `ud02cp03`, para otros módulos o casos prácticos.

No metas claves ni credenciales en archivos sueltos. Las credenciales locales van solo en `.env`, que no debe subirse al repositorio.

### OpenAI API

Para el flujo recomendado por API de OpenAI necesitas una clave real en `.env`:

```env
OPENAI_API_KEY=<sk-proj-...>
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

En configuracion puedes activar `Preparar prompts automaticamente` con un intervalo propio o una hora exacta diaria. El autoescaneo y el autoprompt son independientes: el primero actualiza/detecta estado; el segundo prepara prompts pendientes. Si pasan varios dias sin corregir, los prompts ya existentes no se pisan: las nuevas tandas usan un nombre nuevo con fecha/hora y se importan por separado cuando vuelvas a la revision.

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

Si ya existe un prompt pendiente para esa actividad, la app no lo sobrescribe. Genera otro nombre compatible, por ejemplo `prompt_ud01cp01_20260514_090000.md`, y su correccion esperada sera `prompt_ud01cp01_20260514_090000_correccion.json`.

Si `Separar carpetas por curso` esta desactivado, se usan las rutas globales antiguas `C:\temp\vscodec\pendientes` y `C:\temp\vscodec\temporal`.

El archivo `.md` se copia entero en Codex/ChatGPT. Codex debe devolver un JSON con las correcciones.

### Resolver prompts sin API

El flujo sin API puede hacerse de dos formas:

- Manual: abre Codex/ChatGPT aparte, ejecuta `$C` o pega el prompt, guarda los `*_correccion.json` en la carpeta de prompts y vuelve a la interfaz para pulsar `Importar JSON a revision`.
- Codex App: si Codex Desktop esta instalado, iniciado con ChatGPT y expone un CLI ejecutable, pulsa `Corregir con Codex App`. La app usa `codex exec --cd <codex_project>`, crea los JSON individuales e importa las correcciones a `revision_pendiente.csv` sin usar `OPENAI_API_KEY`. La extension de VS Code no se usa para esta ruta.

Si una respuesta extraida parece incompleta, recortada o con caracteres raros, el prompt incluye un bloque interno `calidad_extraccion`. Codex debe intentar revisar el archivo original indicado en `archivo` antes de penalizar y no debe mencionar problemas de extraccion/OCR/codificacion al alumno salvo que tambien aparezcan en la entrega real.

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

El código `ud01cp01` cambia según la actividad. Si se extrae desde CARM, el agente intenta detectarlo desde el nombre de la unidad y del caso práctico. Si corriges archivos descargados a mano, puedes indicarlo con `--actividad-codigo ud02cp03` o meter los archivos en una subcarpeta con ese nombre.

Si la respuesta del alumno ya es `.txt`, se copia como `ud01cp01_respuesta.txt` para no pisar la corrección `ud01cp01.txt`.

## 5. Diagnosticar navegación real en CARM

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

Desde la interfaz tambien puedes elegir `Todo el curso` en el filtro de preparacion. Ese modo recorre las actividades detectadas del curso y genera prompts para las que tengan entregas pendientes.

## 6. Cachear recursos estables del curso

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

## 7. Extraer desde CARM

```powershell
python corrector_agente.py --extraer-carm
```

En este modo descarga los archivos entregados desde CARM a la carpeta activa de pendientes. Con carpetas por curso activadas sera `C:\temp\vscodec\cursos\<course_id>\pendientes\<actividad>\`.

Para extraer desde CARM y generar solo prompts para Codex, sin API:

```powershell
python corrector_agente.py --preparar-carm-codex
```

Primera unidad, optimizando tamaño de prompts sin recortar respuestas:

```powershell
python corrector_agente.py --preparar-carm-codex --unidad ud01 --max-entregas-por-prompt 6
```

Esto abre Playwright una sola vez, entra en CARM, actualiza la cache del curso, registra las filas que requieren calificación, descarga los archivos, extrae el contenido imprimible de `ud01` y divide las entregas en lotes de hasta 6 por prompt. No usa API.

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

La app rellena nota y feedback; el docente pulsa `Guardar cambios` en CARM. Solo se eliminan del CSV las filas cuyo formulario se ha abierto/rellenado y cuyo guardado ha sido confirmado por el docente.
En configuracion puedes activar el autoprompteo periodico por intervalo o a una hora exacta diaria. Ese modo solo prepara prompts; no llama a la API y no guarda calificaciones en CARM.
También puedes abrir la interfaz local:

```powershell
python interfaz_app.py
```

La aplicación queda en `http://127.0.0.1:8765` y permite preparar, previsualizar y lanzar la subida asistida desde una pantalla única.

En la interfaz, el flujo con API está separado en dos pasos: primero `Preparar prompts`, que no gasta API, y después `Corregir prompts con API`, que envía los prompts acumulados y deja generado `revision_pendiente.csv` para la subida asistida.

Antes de llamar a la API, el agente estima el tamaño de cada prompt. Si supera el aviso configurado registra un warning; si supera el límite de seguridad bloquea el envío y pide volver a preparar con menos entregas por prompt. Los umbrales se pueden ajustar con `--openai-warn-tokens-prompt` y `--openai-max-tokens-prompt`.

La cache del curso guarda el contenido imprimible completo, pero los prompts usan un resumen didactico local por unidad para reducir tokens sin perder el contexto principal. El limite por unidad se puede ajustar con:

```env
MAX_RESUMEN_DIDACTICO_CHARS=5000
```

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

## 9. Previsualizar o subir a CARM

Primero prueba en modo previsualización. Este modo abre CARM, busca el alumno y la actividad, rellena nota y retroalimentación, pero no pulsa guardar:

```powershell
python corrector_agente.py --subir-correcciones-carm correcciones_ud01cp01.json
```

También puedes previsualizar directamente el CSV revisable generado por la API:

```powershell
python corrector_agente.py --subir-correcciones-carm C:\temp\vscodec\cursos\<course_id>\temporal\revision_pendiente.csv
```

El navegador queda abierto para revisar el formulario. Para terminar la previsualización, cierra la pestaña de Chromium o detén la tarea desde la interfaz.

La publicacion directa desde CLI esta desactivada. Usa `--subida-asistida-carm` desde la interfaz: la app rellena el formulario y el docente pulsa `Guardar cambios` en CARM.

Para diagnosticar un fallo concreto de subida asistida, activa `Guardar trace de diagnostico de subida` en la interfaz. El trace se guarda en `respuestas_extraidas\traces\` y puede contener datos personales, asi que revisalo antes de compartirlo.

Cada intento deja registro en `respuestas_extraidas\subida_carm_previsualizacion.json` o `respuestas_extraidas\subida_carm_asistida.json`.

Tras importar un JSON de Codex al CSV, el prompt exacto y su `*_correccion.json` se mueven a `pendientes\prompts_codex\archivados\...` para que no vuelvan a aparecer como pendientes. Tras una subida asistida completada, tambien se archivan los resumenes usados. Una previsualizacion no archiva nada.

Tras generar prompts, las entregas usadas se mueven a `pendientes\archivados_prompt\...`. Si necesitas repetir exactamente el mismo lote para una prueba, usa `--conservar-pendientes`.

La extracción real deja auditoría en:

- `respuestas_extraidas\envios_descargados.json`: archivos descargados y dueño de cada archivo.
- `respuestas_extraidas\envios_carm_registros.json`: registro mínimo por fila de alumno, incluyendo actividad, estado, si tenía archivo, si no entregó o si hubo error de descarga.

Cuando una entrega ya ha sido copiada a `temporal` y tiene su corrección generada, se elimina automáticamente de `pendientes`. Para pruebas en las que quieras conservar los originales, usa `--conservar-pendientes`.

Los `.txt`, `.md`, `.csv`, `.html`, `.json`, `.xml`, `.docx`, `.docm`, `.odt`, `.ods`, `.odp`, `.rtf`, `.pdf`, `.pptx`, `.pptm`, `.xlsx`, `.xlsm`, `.epub`, `.zip`, `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tif`, `.tiff` y `.webp` se intentan leer automáticamente. Los multimedia, `.doc`/`.ppt` antiguos, comprimidos no soportados o formatos no extraíbles quedan marcados en `revision_pendiente.csv` como `revision_manual_necesaria` y no se eliminan de `pendientes`.

El flujo normal deja todo revisable antes de publicar. La opcion preferente es la subida asistida, donde el docente pulsa guardar en CARM y la app confirma el avance.
