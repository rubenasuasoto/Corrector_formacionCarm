# Arquitectura y orden del proyecto

Estado: 2026-05-12.

Este documento define la organizacion objetivo del Corrector CARM y separa codigo activo, documentacion, configuracion y artefactos locales. La idea es ordenar el proyecto sin romper rutas internas de golpe.

## Estructura actual aceptada

Archivos activos:

- `corrector_agente.py`: motor principal. Gestiona CARM, prompts, API, importacion, CSV y subida asistida.
- `interfaz_app.py`: interfaz web local, bandeja de Windows, configuracion y orquestacion de comandos permitidos.
- `prompts_correccion.json`: rubricas y prompts editables por actividad.
- `prueba_correcciones.py`: prueba offline con entregas ficticias.

Instalacion y soporte Windows:

- `instalar_windows.cmd`
- `instalar_windows.ps1`
- `iniciar_app_windows.cmd`
- `reparar_dependencias_windows.cmd`
- `requirements.txt`
- `requirements-extraccion.txt`

Documentacion viva:

- `README.md`: entrada general.
- `QUICKSTART.md`: uso rapido.
- `ESTADO_PROYECTO.md`: memoria de decisiones y estado operativo.
- `CUMPLIMIENTO_NORMATIVO.md`: marco RGPD/LOPDGDD/ENS/IA/ASVS/CVSS.
- `SEGURIDAD_ASVS.md`: checklist tecnico de seguridad.
- `SEGURIDAD_CVSS.md`: criterio de priorizacion.
- `INSTRUCCIONES_CODEX_PERSONALIZADAS.md`: flujo sin API para Codex.
- `ROADMAP_DESCARGA_SEGURA.md`: roadmap historico de descarga segura.

Legado o referencia:

- `sincronizador_moodle.py`: referencia antigua. No es ruta principal. Mantener solo mientras aporte contexto; candidato a mover a `legacy/` o eliminar tras una ultima revision.

## Artefactos locales no versionables

No deben entrar en git:

- `.env`
- `.corrector_app.json`
- `logs_correcciones/`
- `respuestas_extraidas/`
- `correcciones_validadas/`
- `cache_carm/`
- `tmp_prueba/`
- `.venv/`
- `venv/`
- `__pycache__/`

Motivo: contienen credenciales, estado local, datos de alumnos, notas, logs, cache o salidas generadas.

## Flujo funcional actual

1. Inicio en bandeja:
   - Windows lanza `interfaz_app.py --tray --no-browser --auto-correct`.
   - `--auto-correct` significa autoprompteo, no gasto automatico de API ni publicacion.

2. Preparacion:
   - La app revisa CARM.
   - Fuerza filtro `Requiere calificacion`.
   - Descarga entregas pendientes.
   - Genera prompts en `C:\temp\vscodec\pendientes\prompts_codex`.
   - Archiva entregas ya convertidas en prompt.
   - Si se activa "Separar carpetas por curso", usa `C:\temp\vscodec\cursos\<course_id>\pendientes` y `C:\temp\vscodec\cursos\<course_id>\temporal` para no mezclar cursos.

3. Correccion:
   - Con API: el usuario pulsa `Corregir prompts con API`.
   - Sin API: Codex/IA externa crea `*_correccion.json`.
   - Los prompts ya resueltos se archivan para evitar gasto duplicado.

4. Revision y subida:
   - La fuente fiable es `C:\temp\vscodec\temporal\revision_pendiente.csv`.
   - La interfaz muestra un unico boton de subida asistida con pendientes por actividad.
   - La app rellena CARM, pero el docente pulsa `Guardar cambios`.
   - La app no avanza hasta detectar guardado real y confirmacion humana.
   - Las filas subidas o ya gestionadas se eliminan del CSV.
   - Prompts, correcciones y resumenes usados se archivan.

## Organizacion profesional objetivo

Fase 1, sin romper imports:

- Mantener los dos ejecutables principales en raiz.
- Sacar del indice de git todos los artefactos locales.
- Mantener documentacion actualizada y coherente.
- Marcar `sincronizador_moodle.py` como legado.

Estado 2026-05-12: fase en cierre. La documentacion ya existe, la app funciona con rutas multi-curso y `.env`, logs, caches, salidas y correcciones generadas ya no aparecen en `git ls-files`.

Fase 2, refactor gradual:

```text
corrector_carm/
  __init__.py
  agent/
    carm.py
    prompts.py
    corrections.py
    upload.py
    security.py
  ui/
    server.py
    tray.py
  config.py
  paths.py
tests/
  test_correcciones.py
scripts/
  instalar_windows.ps1
  instalar_windows.cmd
  iniciar_app_windows.cmd
docs/
  seguridad/
  operacion/
legacy/
  sincronizador_moodle.py
```

Fase 3:

- Tests unitarios para importacion JSON/CSV, limpieza de prompts y borrado parcial de `revision_pendiente.csv`.
- Tests de endpoints locales con token anti-CSRF.
- Separar UI HTML/CSS/JS de `interfaz_app.py`.
- Crear checklist de release antes de distribuir.

## Multi-curso

Estado actual:

- La app puede detectar cursos visibles desde CARM y guardarlos en `respuestas_extraidas\cursos_detectados.json`.
- La interfaz tiene selector de curso activo en la cabecera.
- La separacion de carpetas por curso es opcional y se controla desde configuracion.
- La interfaz permite marcar varios cursos para autoprompteo.
- El autoprompteo secuencial de varios cursos tiene una primera version: solo se usa cuando hay varios cursos seleccionados y la separacion por curso esta activa.
- Cada subproceso recibe `CARM_COURSE_URL`, `--pendientes` y `--temporal` especificos para el curso.
- Si no hay curso activo, el arranque y el boton de escaneo detectan cursos desde el area personal en vez de cachear un curso inexistente.
- La interfaz expone un resumen por curso seleccionado: cache, fecha de cache, prompts, JSON de correccion, filas CSV, actividades e incidencias bloqueantes.
- La deteccion de cursos filtra enlaces auxiliares conocidos para no ofrecer `FAQS` o `CARM - Curso CARM` como cursos corregibles.
- Los controles de cursos en configuracion preservan cambios sin guardar durante el refresco automatico del panel.
- Al guardar curso o cambiar la opcion de carpetas por curso, la interfaz recalcula rutas inmediatamente para evitar usar rutas del curso anterior.

Regla: antes de activar varios cursos a la vez, cada curso debe tener rutas, CSV, prompts y logs suficientemente visibles para que el docente sepa que esta subiendo al curso correcto.

## Criterios de limpieza futura

Un archivo se considera obsoleto si:

- no lo referencia ningun flujo activo;
- duplica informacion ya mantenida en otro documento;
- contiene rutas antiguas como `temporal\prompts_codex` para prompts pendientes;
- recomienda publicacion automatica como flujo normal;
- contiene datos generados o personales.

Antes de borrar, mover o renombrar archivos usados por scripts de Windows, actualizar README, QUICKSTART y este documento.
