# Agente corrector CARM

Agente local para corregir casos prÃ¡cticos descargados desde CARM FormaciÃ³n/Moodle, usando Codex CLI o la API de OpenAI, y dejando siempre una revisiÃ³n manual antes de publicar notas o retroalimentaciÃ³n.

## Estado corto

El flujo principal ya estÃ¡ implementado en `corrector_agente.py`:

- Corrige entregas locales colocadas en `C:\temp\vscodec\pendientes`.
- Agrupa las entregas por actividad, por ejemplo `ud01cp01` o `ud02cp03`.
- Prepara prompts por lote para reducir llamadas a la IA.
- Crea una carpeta por alumno en `C:\temp\vscodec\temporal`.
- Copia la entrega original, genera la correcciÃ³n y escribe resÃºmenes.
- Genera `revision_pendiente.csv` para revisar notas y feedback antes de subir nada.
- Marca como `revision_manual_necesaria` los archivos que no pueda leer con fiabilidad.

La extraccion directa desde CARM ya se ha probado con UD01. El flujo recomendado es autopromptear, resolver prompts bajo confirmacion y subir con modo asistido desde `revision_pendiente.csv`; el guardado final en CARM sigue siendo humano.

## Documentos importantes

Lee estos archivos en este orden:

1. `ESTADO_PROYECTO.md`: memoria viva del proyecto, decisiones tomadas y prÃ³ximos pasos.
2. `QUICKSTART.md`: comandos rÃ¡pidos de instalaciÃ³n, prueba y uso.
3. `SEGURIDAD_ASVS.md`: controles OWASP ASVS aplicables a esta app.
4. `SEGURIDAD_CVSS.md`: criterio de priorizaciÃ³n de riesgos basado en CVSS v4.0.
5. `ARQUITECTURA_PROYECTO.md`: estructura profesional objetivo y estado de archivos.
6. `prompts_correccion.json`: prompts editables por actividad.
7. `corrector_agente.py`: flujo principal.

El README es solo la entrada general. Si hay duda entre este archivo y `ESTADO_PROYECTO.md`, manda `ESTADO_PROYECTO.md`.

## InstalaciÃ³n

```powershell
.\instalar_windows.cmd
.\iniciar_app_windows.cmd
```

El instalador crea `.venv`, instala dependencias, instala Chromium de Playwright y deja `.env` preparado si no existe.

Dependencias opcionales para leer PDF, PPTX, XLSX, ZIP e imÃ¡genes con OCR:

```powershell
pip install -r requirements-extraccion.txt
```

Para OCR de JPG/PNG tambiÃ©n hace falta Tesseract OCR instalado en Windows y disponible en el `PATH`.

## ConfiguraciÃ³n

Copia `.env.example` a `.env` y rellena credenciales:

```env
CARM_USUARIO=tu_usuario_carm
CARM_CONTRASENA=tu_contrasena_carm
OPENAI_API_KEY=tu_api_key_aqui
OPENAI_MODEL=gpt-5-mini
CARM_COURSE_URL=https://formacion.carm.es/course/view.php?id=1592
```

No subas `.env` al repositorio.

`OPENAI_API_KEY` es opcional si corriges con Codex CLI. No guardes API keys, tokens o contraseÃ±as en archivos `.txt`. Las claves locales deben vivir solo en `.env`.

## Prueba offline

Sin CARM y sin IA real:

```powershell
python prueba_correcciones.py
```

Esto crea entregas ficticias en `tmp_prueba\pendientes`, genera correcciones de respaldo y deja resultados en `tmp_prueba\temporal`.

## Uso sin API

Para aprovechar Codex/ChatGPT manualmente sin pagar llamadas de API:

```powershell
python corrector_agente.py --contexto-unidad C:\ruta\manual_ud01.txt --preparar-prompts-codex
```

El agente lee las entregas, las agrupa por actividad y genera archivos en `C:\temp\vscodec\pendientes\prompts_codex`. Copia el `.md` de la actividad en Codex/ChatGPT y pide que devuelva el JSON de correcciones junto al prompt.

Para el flujo automatico sin API hace falta Codex CLI instalado y autenticado:

```powershell
python corrector_agente.py --comprobar-codex-cli
```

Opciones soportadas:

- Iniciar sesion en la extension oficial ChatGPT/Codex de VS Code.
- Ejecutar `codex login` en PowerShell.
- Configurar `CODEX_CLI_PATH` en `.env` si la app en bandeja no hereda el `PATH`.

## Uso con entregas locales

Coloca las entregas en `C:\temp\vscodec\pendientes` y ejecuta:

```powershell
python corrector_agente.py --contexto-unidad C:\ruta\manual_ud01.txt
```

Forzando una actividad concreta:

```powershell
python corrector_agente.py --contexto-unidad C:\ruta\manual_ud01.txt --actividad-codigo ud02cp03
```

Conservando los archivos en pendientes durante pruebas:

```powershell
python corrector_agente.py --contexto-unidad C:\ruta\manual_ud01.txt --conservar-pendientes
```

## ExtracciÃ³n desde CARM

Primero conviene diagnosticar la navegaciÃ³n real:

```powershell
python corrector_agente.py --diagnosticar-carm
```

El diagnÃ³stico guarda un `diagnostico.json` limpio en `logs_correcciones\diagnostico_carm`, sin descargar ni corregir entregas. Por defecto no guarda HTML ni capturas.

Para depurar selectores con evidencias redactadas:

```powershell
python corrector_agente.py --diagnosticar-carm --guardar-evidencias
```

Para listar entregas que requieren calificaciÃ³n sin descargar archivos:

```powershell
python corrector_agente.py --solo-listar-carm
```

Para la primera unidad:

```powershell
python corrector_agente.py --solo-listar-carm --unidad ud01
```

Para cachear contenido imprimible y enunciados de una unidad:

```powershell
python corrector_agente.py --cachear-curso --unidad ud01
```

La cache local vive en `cache_carm\curso_1592.sqlite` y no guarda entregas ni datos personales de alumnos.
Se usa automÃ¡ticamente cuando existe. Si `CARM_COURSE_END_DATE` ya pasÃ³, se borra al iniciar.

```powershell
python corrector_agente.py --extraer-carm
```

Este modo descarga entregas desde CARM a `C:\temp\vscodec\pendientes\<actividad>\` y despuÃ©s corrige por lotes. Para uso real, conviene limitar por `--unidad` o `--actividad` y revisar las salidas antes de publicar.

Para descargar desde CARM y generar solo prompts para Codex, sin API:

```powershell
python corrector_agente.py --preparar-carm-codex
```

Primera ejecuciÃ³n recomendada, limitada a unidad 1 y con prompts por lotes, usando una sola sesiÃ³n de Playwright:

```powershell
python corrector_agente.py --preparar-carm-codex --unidad ud01 --max-entregas-por-prompt 6
```

Este comando actualiza cache, registra filas de CARM, descarga entregas y genera prompts sin cerrar y abrir Chromium entre pasos.

## Flujo recomendado actual

1. Preparar prompts sin gastar API ni publicar en CARM:

```powershell
python corrector_agente.py --preparar-carm-codex --unidad ud01 --max-entregas-por-prompt 0
```

Este comando entra en CARM, descarga entregas pendientes, genera prompts en `C:\temp\vscodec\pendientes\prompts_codex` y archiva las entregas ya convertidas en prompt para no duplicarlas.

2. Resolver prompts:

Con API configurada, desde la interfaz pulsa `Corregir prompts con API` o ejecuta:

```powershell
python corrector_agente.py --pendientes C:\temp\vscodec\pendientes --temporal C:\temp\vscodec\temporal --corregir-prompts-openai
```

Sin API, usa Codex u otra IA con `INSTRUCCIONES_CODEX_PERSONALIZADAS.md`. Debe crear un JSON por prompt con el patron `prompt_udXXcpYY_correccion.json` en la misma carpeta de prompts.

3. Subir a CARM con revision humana:

La app importa las correcciones a `C:\temp\vscodec\temporal\revision_pendiente.csv`. Ese CSV es la fuente fiable para rellenar CARM. Usa la subida asistida desde la interfaz o:

```powershell
python corrector_agente.py --subir-correcciones-carm C:\temp\vscodec\temporal\revision_pendiente.csv --subida-asistida-carm --mantener-navegador
```

La subida asistida rellena nota y feedback, pero el guardado en CARM lo hace el docente. Las filas confirmadas o ya gestionadas se eliminan del CSV. Los prompts, correcciones y resumenes usados se archivan para evitar gasto o subida duplicada.

## Interfaz local

Para usar la aplicaciÃ³n desde navegador:

```powershell
python interfaz_app.py
```

Abre `http://127.0.0.1:8765`. La interfaz ejecuta solo los flujos permitidos: preparar prompts, corregir prompts con API bajo confirmacion e iniciar subida asistida a CARM.

DespuÃ©s de pegar el prompt en Codex/ChatGPT, guarda el JSON de respuesta e impÃ³rtalo:

```powershell
python corrector_agente.py --importar-correcciones-codex C:\ruta\correcciones_ud01.json
```

Esto genera los `.txt` por alumno, los resÃºmenes y `revision_pendiente.csv` sin llamar a la API.

La subida recomendada es `--subida-asistida-carm`: la app rellena los campos y no avanza hasta detectar que CARM ha guardado y que el usuario lo confirma en el panel.

## Salidas

En `C:\temp\vscodec\temporal`:

- `<alumno>\<actividad>.ext`: copia de la entrega.
- `<alumno>\<actividad>.txt`: correcciÃ³n generada.
- `resumen.txt`: resumen global.
- `resumen_<actividad>.txt`: resumen por actividad.
- `revision_pendiente.csv`: hoja para revisar antes de publicar.

Todo queda en estado `borrador_pendiente_de_revision` salvo los casos que necesitan revisiÃ³n manual.

## PrÃ³ximos pasos

- Seguir validando subida asistida real por lotes y casos ya gestionados en CARM.
- Mejorar la vista local de revision por alumno antes de subir.
- Instalar y probar dependencias opcionales de extracciÃ³n.
- Decidir si merece la pena aÃ±adir OCR con Tesseract.
