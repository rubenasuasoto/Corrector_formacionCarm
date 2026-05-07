# Estado del proyecto: agente corrector CARM

Ultima actualizacion: 2026-05-07

## Resumen

El backend queda completado de forma parcial y usable para una primera operativa real:

- Extrae entregas desde CARM/Moodle con Playwright.
- Filtra por unidad o actividad.
- Trabaja con el filtro de CARM `Requiere calificacion`.
- Descarga solo los archivos necesarios y registra incidencias de alumnos sin archivo.
- Genera prompts optimizados para Codex.
- Puede llamar a Codex CLI para corregir sin usar la API de OpenAI.
- Importa las correcciones JSON a archivos `.txt` por alumno.
- Previsualiza o publica notas y feedback en CARM.
- Tiene una primera interfaz web local en `interfaz_app.py`.

La subida a CARM existe, pero debe seguir usandose con revision humana. El flujo recomendado es preparar todo primero, revisar, y publicar despues.

## Objetivo

Automatizar la correccion de casos practicos de CARM Formacion reduciendo trabajo repetitivo, sin perder control humano sobre notas y retroalimentacion.

El flujo objetivo actual es:

1. Entrar en CARM.
2. Detectar casos practicos obligatorios que requieren calificacion.
3. Descargar entregas.
4. Recoger enunciado y contexto de unidad.
5. Generar prompts por actividad.
6. Corregir con Codex CLI.
7. Crear salidas locales revisables.
8. Publicar en CARM solo tras revision.

## Documentos

- `README.md`: entrada breve del proyecto.
- `QUICKSTART.md`: comandos rapidos de uso.
- `ESTADO_PROYECTO.md`: memoria viva y fuente de verdad del estado.
- `SEGURIDAD_ASVS.md`: checklist de seguridad basado en OWASP ASVS 5.0.0 adaptado a esta app.
- `SEGURIDAD_CVSS.md`: guia de priorizacion de riesgos basada en CVSS v4.0.
- `prompts_correccion.json`: prompts editables.

Si `README.md` y este archivo chocan, manda este archivo.

## Archivos principales

- `corrector_agente.py`: nucleo del agente.
- `interfaz_app.py`: interfaz web local.
- `prueba_correcciones.py`: prueba offline.
- `sincronizador_moodle.py`: borrador antiguo de subida por API Moodle; no es el camino principal actual.
- `prompts_correccion.json`: configuracion de prompts.
- `.env.example`: plantilla de configuracion.
- `.env`: configuracion local real, no debe compartirse.

## Carpetas y salidas

- `C:\temp\vscodec\pendientes`: entregas descargadas desde CARM.
- `C:\temp\vscodec\temporal`: salidas revisables.
- `C:\temp\vscodec\temporal\prompts_codex`: prompts, manifiesto y correcciones JSON de Codex.
- `cache_carm\curso_1592.sqlite`: cache local de recursos estables del curso.
- `respuestas_extraidas`: auditorias minimas de extraccion/subida.
- `logs_correcciones`: logs y diagnosticos.

Archivos importantes generados:

- `prompts_codex\prompt_udXXcpYY.md`
- `prompts_codex\manifiesto_entregas.json`
- `prompts_codex\prompt_udXXcpYY_correccion.json`
- `prompts_codex\correcciones_codex_combinadas.json`
- `temporal\<alumno>\<actividad>.txt`
- `temporal\revision_pendiente.csv`
- `respuestas_extraidas\subida_carm_previsualizacion.json`
- `respuestas_extraidas\subida_carm_publicada.json`

## Dos comandos principales

Preparar correcciones sin publicar en CARM:

```powershell
.\.venv\Scripts\python.exe corrector_agente.py --flujo-correccion-carm --unidad ud01 --max-entregas-por-prompt 6
```

Esto entra en CARM, descarga entregas, genera prompts, corrige con Codex CLI e importa las salidas locales. No publica en CARM.

El JSON combinado queda en:

```text
C:\temp\vscodec\temporal\prompts_codex\correcciones_codex_combinadas.json
```

Publicar en CARM tras revisar:

```powershell
.\.venv\Scripts\python.exe corrector_agente.py --subir-correcciones-carm C:\temp\vscodec\temporal\prompts_codex\correcciones_codex_combinadas.json --publicar-carm
```

Para probar sin guardar, omitir `--publicar-carm`.

## Interfaz local

Existe una primera interfaz web local:

```powershell
.\.venv\Scripts\python.exe interfaz_app.py
```

URL:

```text
http://127.0.0.1:8765
```

Permite:

- Lanzar el flujo de preparacion.
- Ver estado y logs.
- Ver prompts y correcciones generadas.
- Previsualizar subida a CARM.
- Publicar en CARM con confirmacion.
- Detener un proceso en marcha.

Esta interfaz no anade dependencias externas; usa solo la libreria estandar de Python.

## Funcionalidad implementada

### Extraccion CARM

Implementado:

- Login con Playwright.
- Entrada al curso configurado en `CARM_COURSE_URL`.
- Deteccion de tareas obligatorias tipo caso practico.
- Dedupe de actividades repetidas.
- Uso preferente del enlace con `filter=require_grading`.
- Mapeo de tabla de grading por cabeceras.
- Lectura minima por fila: alumno, estado y archivos.
- Registro de filas sin archivo como `sin_entrega`, `sin_archivo_detectado` o `error_descarga`.
- Descarga de archivos a `pendientes\<actividad>`.
- Extraccion de enunciado desde la vista de actividad.
- Limpieza de cookies/localStorage/sessionStorage al cerrar.

### Cache

Implementado:

- Cache SQLite local en `cache_carm`.
- Guarda recursos estables: contenido imprimible, actividades, URLs de grading y enunciados.
- No guarda entregas, archivos de alumnos, emails, cookies ni capturas.
- Se usa por defecto si existe.
- Se puede ignorar con `--sin-cache`.
- Se puede refrescar con `--refrescar-cache`.
- Se puede borrar con `--borrar-cache-curso`.
- Si `.env` define `CARM_COURSE_END_DATE=YYYY-MM-DD` y ya paso, se purga al iniciar.

### Correccion sin API

Implementado:

- `--preparar-prompts-codex`
- `--preparar-carm-codex`
- `--corregir-con-codex`
- `--importar-tras-codex`
- `--flujo-correccion-carm`

El modo recomendado es `--flujo-correccion-carm`.

Codex CLI se invoca con `codex exec`, usando sandbox `read-only` y guardando el ultimo mensaje en JSON. Este flujo usa la sesion local de Codex, no `OPENAI_API_KEY`.

### Importacion JSON

Implementado:

- Importa listas JSON directas.
- Importa objetos con clave `correcciones`, `resultados` o `entregas`.
- Si el objeto tiene `actividad` global, se hereda en cada correccion.
- Acepta `retroalimentacion`, `comentario`, `feedback` u `observaciones`.
- Genera `.txt` por alumno, resumenes y `revision_pendiente.csv`.
- Copia la entrega original desde el manifiesto si existe.

### Subida a CARM

Implementado:

- `--subir-correcciones-carm RUTA_JSON`
- Modo previsualizacion sin guardar.
- Modo publicacion con `--publicar-carm`.
- Rellena nota.
- Rellena solo la seccion de retroalimentacion final, no el detalle completo de criterios.
- Soporta editor Atto/Moodle escribiendo en el campo oculto y en el editor visible.
- Con varias correcciones de la misma actividad, intenta usar `Guardar cambios y mostrar siguiente`.
- En la ultima correccion del lote usa `Guardar cambios`.
- Deja auditoria en `respuestas_extraidas`.

## Pruebas reales realizadas

UD01 se probo con CARM real.

Entregas detectadas:

- `ud01cp01`: Elisabet Lopez Ros.
- `ud01cp01`: Sergio Grazini Sanchez aparecia como enviado para calificar, pero sin archivo descargable.
- `ud01cp02`: Elisabet Lopez Ros.
- `ud01cp02`: Carolina Villa Marin.

Incidencia:

- Sergio queda como revision manual porque CARM indica entrega para calificar, pero no hay archivo descargable.

Correcciones de prueba:

- `ud01cp01` de Elisabet se corrigio e importo.
- `ud01cp02` se corrigio con Codex CLI para Elisabet y Carolina.
- La subida a CARM se probo en previsualizacion: nota y comentario ya se rellenan.
- Se ajusto para subir solo la retroalimentacion final, no todo el bloque de criterios.

## Seguridad

Implementado:

- `.gitignore` incluye `.env`, caches, logs sensibles y archivos tipo `*api*.txt`, `*key*.txt`, `*token*.txt`.
- Diagnostico no guarda HTML/capturas por defecto.
- Evidencias solo con `--guardar-evidencias`.
- Redaccion basica de emails, `sesskey` y secretos en HTML diagnostico.
- Contexto temporal de Playwright y limpieza al cerrar.
- La cache no almacena entregas ni credenciales.
- Existe `SEGURIDAD_ASVS.md` como checklist vivo para aplicar OWASP ASVS de forma gradual y solo en controles relevantes.
- Existe `SEGURIDAD_CVSS.md` para clasificar y priorizar hallazgos de seguridad.

Notas:

- Se detecto en fases previas una API key en un archivo suelto y se elimino. Esa clave debe considerarse comprometida y rotarse si no se hizo ya.
- `.env` no debe compartirse ni commitearse.

## Prompts

`prompts_correccion.json` es la fuente normal.

Los prompts internos en `corrector_agente.py` quedan como fallback.

El prompt `default` es general. El enunciado real viene de CARM y se inyecta aparte.

Las claves de ejemplo deben llevar prefijo `_ejemplo_` para no aplicarse por error.

## Verificacion

Comandos usados durante el desarrollo:

```powershell
.\.venv\Scripts\python.exe -m py_compile corrector_agente.py interfaz_app.py prueba_correcciones.py sincronizador_moodle.py
.\.venv\Scripts\python.exe corrector_agente.py --help
.\.venv\Scripts\python.exe interfaz_app.py --help
```

Tambien se probo:

- Extraccion CARM real.
- Generacion de prompts.
- Codex CLI con `prompt_ud01cp02.md`.
- Importacion de JSON de Codex.
- Previsualizacion de subida a CARM.
- Servidor local de interfaz en `/api/status`.

## Pendiente / proximos pasos

Prioridad alta:

- Probar una publicacion real con `--publicar-carm` en un lote controlado.
- Validar que `Guardar cambios y mostrar siguiente` funciona en un lote completo de la misma actividad.
- Mejorar la interfaz local: vista de revision por alumno antes de publicar.
- Evitar que la interfaz lance publicacion si no existe JSON combinado o si hay errores en el CSV.

Prioridad media:

- Mejorar limpieza del contenido imprimible de Moodle para reducir ruido en prompts.
- Revisar notas generadas por Codex para calibrar severidad.
- Consolidar logs de subida con alumno, actividad, nota, boton usado y resultado.
- Anadir pantalla de incidencias: alumnos sin archivo, formatos no legibles, errores de descarga.

Prioridad baja:

- Evaluar OCR con Tesseract.
- Evaluar soporte `.doc` antiguo con LibreOffice o Word.
- Decidir si `sincronizador_moodle.py` se elimina o se mantiene como referencia historica.

## Nota de continuidad

Para retomar el proyecto:

1. Leer `ESTADO_PROYECTO.md`.
2. Leer `QUICKSTART.md`.
3. Ejecutar:

```powershell
.\.venv\Scripts\python.exe -m py_compile corrector_agente.py interfaz_app.py prueba_correcciones.py sincronizador_moodle.py
```

4. Abrir la interfaz:

```powershell
.\.venv\Scripts\python.exe interfaz_app.py
```

