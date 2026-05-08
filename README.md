# Agente corrector CARM

Agente local para corregir casos prácticos descargados desde CARM Formación/Moodle, usando Codex CLI o la API de OpenAI, y dejando siempre una revisión manual antes de publicar notas o retroalimentación.

## Estado corto

El flujo principal ya está implementado en `corrector_agente.py`:

- Corrige entregas locales colocadas en `C:\temp\vscodec\pendientes`.
- Agrupa las entregas por actividad, por ejemplo `ud01cp01` o `ud02cp03`.
- Hace corrección por lote para reducir llamadas a la IA.
- Crea una carpeta por alumno en `C:\temp\vscodec\temporal`.
- Copia la entrega original, genera la corrección y escribe resúmenes.
- Genera `revision_pendiente.csv` para revisar notas y feedback antes de subir nada.
- Marca como `revision_manual_necesaria` los archivos que no pueda leer con fiabilidad.

La extracción directa desde CARM ya se ha probado con UD01. También existe previsualización y publicación de notas/retroalimentación, pero la publicación real debe hacerse solo tras revisar el JSON combinado y las salidas locales.

## Documentos importantes

Lee estos archivos en este orden:

1. `ESTADO_PROYECTO.md`: memoria viva del proyecto, decisiones tomadas y próximos pasos.
2. `QUICKSTART.md`: comandos rápidos de instalación, prueba y uso.
3. `SEGURIDAD_ASVS.md`: controles OWASP ASVS aplicables a esta app.
4. `SEGURIDAD_CVSS.md`: criterio de priorización de riesgos basado en CVSS v4.0.
5. `prompts_correccion.json`: prompts editables por actividad.
6. `corrector_agente.py`: flujo principal.

El README es solo la entrada general. Si hay duda entre este archivo y `ESTADO_PROYECTO.md`, manda `ESTADO_PROYECTO.md`.

## Instalación

```powershell
.\instalar_windows.cmd
.\iniciar_app_windows.cmd
```

El instalador crea `.venv`, instala dependencias, instala Chromium de Playwright y deja `.env` preparado si no existe.

Dependencias opcionales para leer PDF, PPTX, XLSX, ZIP e imágenes con OCR:

```powershell
pip install -r requirements-extraccion.txt
```

Para OCR de JPG/PNG también hace falta Tesseract OCR instalado en Windows y disponible en el `PATH`.

## Configuración

Copia `.env.example` a `.env` y rellena credenciales:

```env
CARM_USUARIO=tu_usuario_carm
CARM_CONTRASENA=tu_contrasena_carm
OPENAI_API_KEY=tu_api_key_aqui
OPENAI_MODEL=gpt-4.1-mini
CARM_COURSE_URL=https://formacion.carm.es/course/view.php?id=1592
```

No subas `.env` al repositorio.

`OPENAI_API_KEY` es opcional si corriges con Codex CLI. No guardes API keys, tokens o contraseñas en archivos `.txt`. Las claves locales deben vivir solo en `.env`.

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

El agente lee las entregas, las agrupa por actividad y genera archivos en `C:\temp\vscodec\temporal\prompts_codex`. Copia el `.md` de la actividad en Codex/ChatGPT y pide que devuelva el JSON de correcciones.

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

## Extracción desde CARM

Primero conviene diagnosticar la navegación real:

```powershell
python corrector_agente.py --diagnosticar-carm
```

El diagnóstico guarda un `diagnostico.json` limpio en `logs_correcciones\diagnostico_carm`, sin descargar ni corregir entregas. Por defecto no guarda HTML ni capturas.

Para depurar selectores con evidencias redactadas:

```powershell
python corrector_agente.py --diagnosticar-carm --guardar-evidencias
```

Para listar entregas que requieren calificación sin descargar archivos:

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
Se usa automáticamente cuando existe. Si `CARM_COURSE_END_DATE` ya pasó, se borra al iniciar.

```powershell
python corrector_agente.py --extraer-carm
```

Este modo descarga entregas desde CARM a `C:\temp\vscodec\pendientes\<actividad>\` y después corrige por lotes. Para uso real, conviene limitar por `--unidad` o `--actividad` y revisar las salidas antes de publicar.

Para descargar desde CARM y generar solo prompts para Codex, sin API:

```powershell
python corrector_agente.py --preparar-carm-codex
```

Primera ejecución recomendada, limitada a unidad 1 y con prompts por lotes, usando una sola sesión de Playwright:

```powershell
python corrector_agente.py --preparar-carm-codex --unidad ud01 --max-entregas-por-prompt 6
```

Este comando actualiza cache, registra filas de CARM, descarga entregas y genera prompts sin cerrar y abrir Chromium entre pasos.

## Dos comandos principales

1. Preparar correcciones sin publicar en CARM:

```powershell
python corrector_agente.py --flujo-correccion-carm --unidad ud01 --max-entregas-por-prompt 6
```

Este comando entra en CARM, descarga entregas, genera prompts, corrige con Codex CLI e importa las salidas locales. No publica en CARM. El JSON combinado queda en `C:\temp\vscodec\temporal\prompts_codex\correcciones_codex_combinadas.json`.

2. Publicar en CARM cuando ya hayas revisado:

```powershell
python corrector_agente.py --subir-correcciones-carm C:\temp\vscodec\temporal\prompts_codex\correcciones_codex_combinadas.json --publicar-carm
```

Las respuestas de Codex se guardan en `C:\temp\vscodec\temporal\prompts_codex\`. Este flujo usa la sesión de Codex CLI, no la API de OpenAI.

## Interfaz local

Para usar la aplicación desde navegador:

```powershell
python interfaz_app.py
```

Abre `http://127.0.0.1:8765`. La interfaz ejecuta solo los flujos permitidos: preparar correcciones, previsualizar subida y publicar en CARM.

Después de pegar el prompt en Codex/ChatGPT, guarda el JSON de respuesta e impórtalo:

```powershell
python corrector_agente.py --importar-correcciones-codex C:\ruta\correcciones_ud01.json
```

Esto genera los `.txt` por alumno, los resúmenes y `revision_pendiente.csv` sin llamar a la API.

Para probar la subida a CARM sin publicar:

```powershell
python corrector_agente.py --subir-correcciones-carm correcciones_ud01cp01.json
```

Este modo rellena el formulario y deja el navegador abierto, pero no guarda. Para publicar de verdad hay que añadir el seguro explícito:

```powershell
python corrector_agente.py --subir-correcciones-carm correcciones_ud01cp01.json --publicar-carm
```

Si el JSON contiene varias correcciones de la misma actividad, el publicador intenta usar `Guardar cambios y mostrar siguiente` entre alumnos, y usa `Guardar cambios` en la última corrección del lote.

## Salidas

En `C:\temp\vscodec\temporal`:

- `<alumno>\<actividad>.ext`: copia de la entrega.
- `<alumno>\<actividad>.txt`: corrección generada.
- `resumen.txt`: resumen global.
- `resumen_<actividad>.txt`: resumen por actividad.
- `revision_pendiente.csv`: hoja para revisar antes de publicar.

Todo queda en estado `borrador_pendiente_de_revision` salvo los casos que necesitan revisión manual.

## Próximos pasos

- Validar una publicación real completa con `--publicar-carm` en un lote controlado.
- Confirmar que `Guardar cambios y mostrar siguiente` funciona en un lote completo de la misma actividad.
- Mejorar la interfaz local con una vista de revisión por alumno antes de publicar.
- Instalar y probar dependencias opcionales de extracción.
- Decidir si merece la pena añadir OCR con Tesseract.
