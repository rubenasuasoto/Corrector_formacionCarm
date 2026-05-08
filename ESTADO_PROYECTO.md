# Estado del proyecto: agente corrector CARM

Última actualización: 7 de mayo de 2026

## Resumen ejecutivo

**Estado general**: Operacional. Backend implementado y probado con éxito.

El sistema funciona en ciclos completos desde descarga hasta publicación:

✅ **Funcionalidades implementadas y probadas**:
- Extrae entregas desde CARM/Moodle con Playwright
- Filtra por unidad, actividad o "Requiere calificación"
- Descarga solo archivos necesarios, registra incidencias
- Genera prompts optimizados para Codex
- Corrige mediante Codex CLI (sin usar API de OpenAI)
- Importa correcciones JSON a archivos `.txt` por alumno
- Genera CSV de revisión (`revision_pendiente.csv`)
- Previsualiza en local antes de publicar
- Publica notas y feedback en CARM
- Interfaz web local en `interfaz_app.py`

⚠️ **Requisitos previos**: La subida a CARM requiere verificación humana. Flujo: preparar → revisar local → publicar tras validación.

## Objetivo

Automatizar la corrección de casos prácticos de CARM Formación reduciendo trabajo repetitivo, sin perder control humano sobre notas y retroalimentación.

El flujo objetivo actual es:

1. Entrar en CARM.
2. Detectar casos prácticos obligatorios que requieren calificación.
3. Descargar entregas.
4. Recoger enunciado y contexto de unidad.
5. Generar prompts por actividad.
6. Corregir con Codex CLI.
7. Crear salidas locales revisables.
8. Publicar en CARM solo tras revisión manual.

## Estado de datos y pruebas (2026-05-05)

**Correcciones validadas**: 13 JSON generados en la última tanda de pruebas.
- Timestamps: 13:48:10, 13:49:51, 13:50:22, 13:50:35
- Actividades probadas: 3 actividades de prueba diferentes
- Alumnos de prueba: alumno_prueba_1, 2, 3
- Archivos procesados por lote

**Logs disponibles**: 6 registros de ejecución
- `agente_20260505_134810.log` (primer lote)
- `agente_20260505_134951.log` (segundo lote)
- `agente_20260505_135022.log` (tercer lote)
- `agente_20260505_135035.log` (cuarto lote)
- `agente_20260505_135924.log` (lote final)

**Estado de CARM**:
- `envios_descargados.json`: registro de descargas completadas
- `envios_carm_registros.json`: auditoría de operaciones

## Documentos de referencia

Lectura recomendada en este orden:

1. **`ESTADO_PROYECTO.md`** (este archivo): memoria viva, decisiones, próximos pasos.
2. **`README.md`**: entrada breve del proyecto.
3. **`QUICKSTART.md`**: comandos rápidos para instalar y usar.
4. **`SEGURIDAD_ASVS.md`**: checklist OWASP ASVS 5.0.0 adaptado.
5. **`SEGURIDAD_CVSS.md`**: priorización de riesgos con CVSS v4.0.
6. **`ROADMAP_DESCARGA_SEGURA.md`**: fases para interfaz de descarga, seguridad local y despliegue gradual.
7. **`CUMPLIMIENTO_NORMATIVO.md`**: RGPD/LOPDGDD/ENS/IA aplicados de forma practica al proyecto.
8. **`prompts_correccion.json`**: rúbricas y prompts editables por actividad.

📌 **Si hay conflicto entre documentos, manda este archivo (`ESTADO_PROYECTO.md`).**

## Estructura de código

### Archivos ejecutables

- **`corrector_agente.py`**: núcleo principal con toda la lógica
  - Extracción desde CARM
  - Corrección con Codex CLI
  - Importación de salidas
  - Publicación en CARM
  - Soporta flags: `--flujo-correccion-carm`, `--subir-correcciones-carm`, `--publicar-carm`

- **`interfaz_app.py`**: interfaz web local
  - Servidor HTTP local en puerto 8765
  - Gestión de sesión con token
  - Navega correcciones y publica desde navegador
  - Controles CSRF activados

- **`prueba_correcciones.py`**: pruebas offline sin CARM
  - Carga entregas de `tmp_prueba/`
  - Útil para testing sin conectarse a producción

- **`sincronizador_moodle.py`**: borrador antiguo (no es la ruta principal)
  - Considerar como referencia, no es prioritario

### Archivos de configuración

- **`.env.example`**: plantilla de variables (copia a `.env` y rellena)
- **`.env`** (local, no compartir): credenciales CARM, API keys
- **`prompts_correccion.json`**: rúbricas JSON por actividad
  - Usa `"default"` como base
  - Añade claves tipo `"ud02cp03"` para rúbricas específicas

### Dependencias

- **`requirements.txt`**: dependencias base (Playwright, OpenAI, dotenv, pystray, Pillow)
- **`requirements-extraccion.txt`**: opcional para leer PDF, PPTX, XLSX, OCR

## Directorios y estructura de salidas

### Carpetas principales de datos

| Carpeta | Descripción |
|---------|-------------|
| `cache_carm/` | Cache SQLite del curso (`curso_1592.sqlite`) |
| `correcciones_validadas/` | ✅ Historial de correcciones JSON validadas |
| `logs_correcciones/` | 📝 Logs de ejecución del agente |
| `respuestas_extraidas/` | 📊 Auditoría de descargas y subidas |
| `tmp_prueba/` | 🧪 Datos de prueba local offline |

### Carpetas de trabajo (externas, en `C:\temp\vscodec\`)

| Ruta | Descripción |
|------|------------|
| `pendientes/` | 📥 Entregas descargadas desde CARM |
| `temporal/` | 📤 Salidas generadas (alumno, actividad, resúmenes) |
| `temporal/prompts_codex/` | 🤖 Prompts, JSON de correcciones y manifiesto |

### Archivos clave generados en salida

```
C:\temp\vscodec\temporal\
├── prompts_codex/
│   ├── prompt_udXXcpYY.md                      # Prompt limpio
│   ├── prompt_udXXcpYY_correccion.json         # Respuesta de Codex
│   ├── correcciones_codex_combinadas.json      # JSON COMBINADO final
│   └── manifiesto_entregas.json                # Inventario de entregas
├── revision_pendiente.csv                      # Resumen + scores para revisar
├── <nombre_alumno>/
│   ├── ud01cp01.txt                            # Entrega original
│   ├── ud01cp01_resumen.txt                    # Corrección JSON legible
│   └── resumen_global_<alumno>.txt             # Notas de todas sus actividades
└── ...
```

**Workflow de revisión**:
1. Revisar `revision_pendiente.csv` (notas rápidas)
2. Explorar `temporal/<alumno>/` (correcciones por actividad)
3. Validar `correcciones_codex_combinadas.json`
4. Si todo OK → `--publicar-carm`

## Comandos operacionales

### Comando principal: Preparar correcciones

```powershell
.\.venv\Scripts\python.exe corrector_agente.py --flujo-correccion-carm --unidad ud01 --max-entregas-por-prompt 6
```

**Qué hace**:
1. Entra en CARM (requiere credenciales en `.env`)
2. Descarga entregas de la unidad `ud01`
3. Agrupa por actividad (ud01cp01, ud01cp02, etc.)
4. Genera prompts optimizados para Codex
5. Llama a Codex CLI para corregir
6. Importa salidas JSON a carpeta temporal
7. **NO publica** en CARM (genera solo revisor local)

**Salida final**:
```
C:\temp\vscodec\temporal\prompts_codex\correcciones_codex_combinadas.json
C:\temp\vscodec\temporal\revision_pendiente.csv
```

**Flags opcionales**:
- `--unidad ud01`: filtra por unidad (ud01, ud02, ..., ud15)
- `--max-entregas-por-prompt 6`: agrupa entregas en lotes (reduce llamadas a Codex)
- Omitir `--unidad` para procesar todo sin filtrar

### Comando secundario: Publicar tras revisar

```powershell
.\.venv\Scripts\python.exe corrector_agente.py --subir-correcciones-carm C:\temp\vscodec\temporal\prompts_codex\correcciones_codex_combinadas.json --publicar-carm
```

**Qué hace**:
1. Lee el JSON combinado de correcciones
2. Publica notas y feedback en CARM

**Seguridad**:
- Requiere `--publicar-carm` para confirmar (sin flag, solo previsualiza)
- Almacena evidencia en `respuestas_extraidas\subida_carm_publicada.json`
- **Revisar siempre antes de publicar**

### Comando de prueba local (sin CARM)

```powershell
.\.venv\Scripts\python.exe prueba_correcciones.py
```

**Úsalo para**:
- Testing sin conectarse a CARM
- Entregas en `tmp_prueba/`
- Validación de prompts sin gasto de tokens

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

## Seguridad: Estado actual (2026-05-07)

## Cumplimiento normativo: avance 2026-05-08

Se añade `CUMPLIMIENTO_NORMATIVO.md` como marco práctico para RGPD, LOPDGDD, ENS, Reglamento europeo de IA, guías AEPD, ASVS y CVSS.

Controles incorporados:

- Auditoría local en `respuestas_extraidas/auditoria.jsonl` para acciones sensibles.
- Redacción básica de emails, tokens, cookies, claves y contraseñas en logs/eventos.
- Sanitizado de feedback antes de insertarlo en editores Moodle/CARM.
- Retención local configurable de logs y auditoría (`LOG_RETENTION_DAYS`, `AUDIT_RETENTION_DAYS`).
- Purga manual protegida de datos personales locales con `--purgar-datos-personales-locales --confirmar-purga-datos`.
- Se mantiene revisión humana obligatoria antes de publicar notas y feedback.
- Aviso al iniciar si hay correcciones preparadas pendientes de subir.
- Modo `--subida-asistida-carm`: rellena nota/feedback en CARM, muestra guia de revision humana y espera a que el usuario pulse guardar.
- Si faltan credenciales CARM, la interfaz bloquea el panel y solicita verificacion. En consola interactiva, los flujos CARM preguntan usuario/contrasena y esperan en vez de fallar directamente.
- `Borrar credenciales CARM` vacia `CARM_USUARIO`/`CARM_CONTRASENA` en `.env`, no elimina las claves.
- Tras publicacion real o subida asistida completada, los prompts/JSON usados se archivan en `temporal/prompts_codex/archivados/` para evitar reutilizar archivos antiguos por error. La previsualizacion no archiva.
- Tras generar prompts, las entregas usadas se mueven de `pendientes` a `pendientes/archivados_prompt/` para que no vuelvan a entrar en otro prompt accidentalmente. Se puede evitar con `--conservar-pendientes`.
- Instalacion Windows automatizada con `instalar_windows.cmd` / `instalar_windows.ps1`: crea `.venv`, instala dependencias base, instala Chromium de Playwright y prepara `.env`. Inicio recomendado con `iniciar_app_windows.cmd`.

Decisión: no activar purgas automáticas agresivas de entregas/notas mientras el flujo de descarga y revisión sigue en desarrollo. La purga de datos personales queda como acción manual confirmada; la cache didáctica sí puede purgarse automáticamente por `CARM_COURSE_END_DATE`.

Decision de subida humana asistida: se prioriza el modo asistido frente a la publicacion totalmente automatica. La app puede detectar la ultima calificacion de un caso y recomendar `Guardar cambios` en vez de `Guardar cambios y mostrar siguiente`, pero la accion final de guardado sigue siendo humana.

### Implementado (Prioridad Alta completada)

✅ **1. Token local anti-CSRF en interfaz**
- Todos los `POST` requieren `X-Corrector-Token`
- Token se genera en sesión al cargar la página
- Enviado automáticamente desde el cliente
- Probado: `POST` sin token a `/api/stop` devuelve `403`
- Archivo: `interfaz_app.py`

✅ **2. Bloqueo de publicación si hay revisión manual o errores**
- `revision_pendiente.csv` es auditoría previa obligatoria
- Publica bloqueado si el CSV:
  - No existe o está vacío
  - Contiene estados: `revision_manual_necesaria`, `error`, `error_descarga`, `sin_archivo_detectado`, `sin_entrega`
- Validación en: `corrector_agente.py` función de publicación
- Probado con `tmp_prueba`: bloqueó correctamente 3 filas

✅ **3. Endurecimiento de lectura de archivos de alumnos**
- Límite general de tamaño por archivo
- Lista cerrada de extensiones permitidas
- ZIP endurecido contra:
  - Exceso de archivos internos
  - Tamaño total excesivo
  - Archivo individual demasiado grande
  - Rutas inseguras (`../`, absolutas)
- Contenido dudoso → revisión manual
- Archivo: `corrector_agente.py` clase `LecturaEntrega`

✅ **4. Documentación de seguridad**
- `SEGURIDAD_ASVS.md`: checklist OWASP ASVS 5.0.0 adaptado a esta app
- `SEGURIDAD_CVSS.md`: guía práctica de priorización con CVSS v4.0
- Ejemplos específicos: credenciales CARM, endpoints, ZIP, logs
- Enlazados desde: `README.md`, `ESTADO_PROYECTO.md`, `SEGURIDAD_ASVS.md`

### Implementación previa

- `.gitignore` incluye `.env`, caches, logs sensibles
- Diagnóstico no guarda HTML por defecto
- Redacción básica de emails y secretos en HTML
- Contexto Playwright temporal y limpieza
- Cache sin entregas ni credenciales

### Próximas medidas recomendadas (Prioridad Alta)

⏳ **2. Guardar credenciales CARM con Windows DPAPI**
- Descifra credenciales desde `.env` con `dpapi` de Windows
- Evita guardarlas en texto plano
- Requiere: investigar integración con `ctypes` de Python
- Impacto: credenciales cifradas con usuario Windows

⏳ **5. Redacción/limpieza de logs sensibles**
- Logs actualmente contienen: nombres de alumnos, actividades, estado de subida
- Propuesta: ofuscar nombres, emails, URLs sensibles
- Mantener solo: timestamps, códigos de error, estadísticas
- Archivos: `logs_correcciones/*.log`

### Próximas medidas recomendadas (Prioridad Media)

⏳ **6. Auditoría local de acciones sensibles**
- Registro de: quién (sesión), cuándo, qué acción (descarga, corrección, publicación)
- Almacenar en: `respuestas_extraidas/auditoria.json`
- Información: timestamps, flags utilizados, resultado

⏳ **7. Separación de datos didácticos vs personales**
- Cache didáctica (contenido/enunciados): en `cache_carm/`
- Entregas/notas/alumnos: en carpetas temporales con purga clara
- Flag: `--purgar-datos-temporales-al-finalizar-curso`

⏳ **8. Confirmación fuerte para publicar**
- Botón bloqueado hasta completar revisión limpia
- Confirmación explícita tipo "PUBLICAR SÍ, ENTIENDO RIESGOS"
- Interfaz: `interfaz_app.py`

### Validación en ejecución

Probado el 2026-05-07:

- `py_compile`: OK
- `prueba_correcciones.py`: OK (datos sintéticos)
- `pip check`: OK
- Interfaz web: responde en `http://127.0.0.1:8765`
- `/api/auth`: `configured: true`
- Anti-CSRF: funcional

## Limite de uso: Estado del servicio Codex CLI

**Situación**: Se alcanzó el límite mensual de Codex CLI al 2026-05-05.

- Últimas correcciones validadas: 4 lotes (timestamps 13:48-13:50)
- Correcciones generadas: 13 JSON en `correcciones_validadas/`
- Siguiente disponibilidad: próximo período de facturación

**Alternativas activas**:
1. Completar revisión y publicación de los 13 JSON existentes
2. Usar el flujo por API de OpenAI configurando `OPENAI_API_KEY` y ejecutando el corrector sin el flujo Codex CLI
3. Validación manual sin IA (usando `prueba_correcciones.py`)
4. Esperar reanudación de Codex CLI

## Prompts

`prompts_correccion.json` es la fuente normal.

Los prompts internos en `corrector_agente.py` quedan como fallback.

El prompt `default` es general. El enunciado real viene de CARM y se inyecta aparte.

Las claves de ejemplo deben llevar prefijo `_ejemplo_` para no aplicarse por error.

## Próximos pasos recomendados

### Corto plazo (esta semana)

1. **Revisar y publicar las correcciones existentes**
   - Ubicación: `correcciones_validadas/`
   - Validar con `revision_pendiente.csv`
   - Publicar lotes con `--publicar-carm` tras revisión
   - Impacto: Cierra primer ciclo de pruebas

2. **Implementar redacción de logs sensibles**
   - Ofuscar nombres de alumnos, emails, URLs CARM
   - Mantener timestamps, errores, estadísticas
   - Archivo: `logs_correcciones/`
   - Esfuerzo: bajo (regex de redacción)

3. **Decidir sobre DPAPI para credenciales**
   - ¿Guardar CARM con cifrado Windows?
   - ¿Mantener `.env` en texto plano?
   - Recomendación: DPAPI si /.env se comparte o se guarda en USB

### Mediano plazo (próximas 2-3 semanas)

4. **Implementar auditoría local de acciones**
   - Registro en `respuestas_extraidas/auditoria.json`
   - Qué: descarga, corrección, publicación
   - Cuándo: timestamps ISO
   - Quién: sesión/token local

5. **Refinar confirmación fuerte para publicar**
   - Botón bloqueado hasta revisión limpia
   - Confirmación modal explícita
   - Interfaz: `interfaz_app.py`

6. **Preparar para escalar a más unidades**
   - UD02, UD03, etc.
   - Validar cache con `--refrescar-cache`
   - Probar filtros por actividad específica

### Largo plazo (mes siguiente)

7. **Documentación de operador**
   - Guía paso a paso: extracción → corrección → publicación
   - Troubleshooting de errores comunes
   - Video tutorial si es viable

8. **Considerar migración a OpenAI API o modelo local**
   - Si Codex no se reanuda
   - Evaluar costo-beneficio
   - Adaptar prompts si cambia el modelo

## Resumen de estado para alguien nuevo

Este proyecto automatiza corrección de casos prácticos en CARM Formación:

- **¿Qué?**: Descarga entregas de CARM, las corrige con IA (Codex CLI), genera revisiones locales, publica notas y feedback
- **¿Dónde?**: `corrector_agente.py` es el motor principal; `interfaz_app.py` es la UI web
- **¿Cuándo?**: Operacional, últimas pruebas el 2026-05-05; límite Codex alcanzado 2026-05-07
- **¿Seguridad?**: Token anti-CSRF, bloqueo de publicación sin revisión, endurecimiento de ZIP, documentación ASVS/CVSS
- **¿Próximos?**: Publicar correcciones existentes → redacción de logs → auditoría local

Para empezar:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

Lee `QUICKSTART.md` para comandos. Lee `SEGURIDAD_ASVS.md` y `SEGURIDAD_CVSS.md` antes de tocar datos sensibles.

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

- Validar una publicacion real completa con `--publicar-carm` en un lote controlado.
- Confirmar que `Guardar cambios y mostrar siguiente` funciona en un lote completo de la misma actividad.
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

