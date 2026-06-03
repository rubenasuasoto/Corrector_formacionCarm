# Arquitectura y orden del proyecto

Estado: 2026-05-17.

Este documento define la organizacion objetivo del Corrector CARM y separa codigo activo, documentacion, configuracion y artefactos locales. La idea es ordenar el proyecto sin romper rutas internas de golpe.

## Estructura actual aceptada

Archivos activos:

- `corrector_agente.py`: motor principal. Gestiona CARM, prompts, API, importacion, CSV y subida asistida.
- `interfaz_app.py`: interfaz web local, bandeja de Windows, configuracion y orquestacion de comandos permitidos.
- `prompts_correccion.json`: rubricas y prompts editables por actividad.

Instalacion y soporte Windows:

- `instalar_windows.cmd`
- `instalar_windows.ps1`
- `instalador_guiado_windows.cmd`
- `instalador_guiado_windows.ps1`
- `iniciar_app_windows.cmd`
- `desinstalar_windows.cmd`
- `desinstalar_windows.ps1`
- `crear_launcher_windows.cmd`
- `crear_launcher_windows.ps1`
- `reparar_dependencias_windows.cmd`
- `reparar_dependencias_windows.ps1`
- `instalar_ocr_windows.cmd`
- `instalar_ocr_windows.ps1`
- `crear_paquete_windows.cmd`
- `crear_paquete_windows.ps1`
- `requirements.txt`
- `requirements-extraccion.txt`

Identidad visual local:

- `assets/corrector_carm.ico`: icono de Windows para accesos directos y notificaciones fallback.
- `assets/corrector_carm.png`: icono del panel local y bandeja.

Documentacion viva:

- `README.md`: entrada general.
- `QUICKSTART.md`: uso rapido.
- `ESTADO_PROYECTO.md`: memoria de decisiones y estado operativo.
- `CUMPLIMIENTO_NORMATIVO.md`: marco RGPD/LOPDGDD/ENS/IA/ASVS/CVSS.
- `SEGURIDAD_ASVS.md`: checklist tecnico de seguridad.
- `SEGURIDAD_CVSS.md`: criterio de priorizacion.
- `INSTRUCCIONES_CODEX_PERSONALIZADAS.md`: flujo sin API para Codex.
- `ROADMAP_DESCARGA_SEGURA.md`: roadmap historico de descarga segura.
- `RELEASE_CHECKLIST.md`: checklist antes de distribuir o usar en una sesion real.

Legado o referencia:

- Sin scripts legado activos en raiz. `prueba_correcciones.py`, `sincronizador_moodle.py` y `tmp_prueba/` fueron retirados para evitar rutas duplicadas.

## Artefactos locales no versionables

No deben entrar en git:

- `.env`
- `.corrector_app.json`
- `logs_correcciones/`
- `respuestas_extraidas/`
- `correcciones_validadas/`
- `cache_carm/`
- `.venv/`
- `venv/`
- `__pycache__/`
- `.tmp_verificacion_cache/`

Motivo: contienen credenciales, estado local, datos de alumnos, notas, logs, cache o salidas generadas.

## Flujo funcional actual

1. Inicio en bandeja:
   - Windows puede lanzar `interfaz_app.py --tray --no-browser`.
   - Si el usuario lo activa expresamente, el arranque incluye `--auto-correct`.
   - `--auto-correct` significa autoprompteo, no gasto automatico de API ni publicacion.

2. Preparacion:
   - La app revisa CARM.
   - Fuerza filtro `Requiere calificacion`.
   - Descarga entregas pendientes.
   - Genera prompts en la carpeta activa de prompts.
   - Archiva entregas ya convertidas en prompt.
   - Si se activa "Separar carpetas por curso", usa `C:\temp\vscodec\cursos\<course_id>\pendientes` y `C:\temp\vscodec\cursos\<course_id>\temporal` para no mezclar cursos.
   - Si no se activa, conserva las rutas globales antiguas `C:\temp\vscodec\pendientes` y `C:\temp\vscodec\temporal`.

3. Correccion:
   - Con API: el usuario pulsa `Corregir prompts con API`.
   - Sin API: Codex/IA externa crea `*_correccion.json`.
   - Los prompts ya resueltos se archivan para evitar gasto duplicado.

4. Revision y subida:
   - La fuente fiable es `revision_pendiente.csv` dentro de la carpeta temporal activa del curso.
   - La interfaz muestra un unico boton de subida asistida con pendientes por actividad.
   - La app rellena CARM, pero el docente pulsa `Guardar cambios`.
   - La app no avanza hasta detectar guardado real y confirmacion humana.
   - Las filas se eliminan del CSV solo si se ha abierto/rellenado el formulario y el docente confirma el guardado, o si hubo publicacion controlada en pruebas internas.
   - Prompts, correcciones y resumenes usados se archivan.

## Organizacion profesional objetivo

Fase 1, sin romper imports:

- Mantener los dos ejecutables principales en raiz.
- Mantener en raiz los lanzadores `.cmd` que usan docentes e instaladores.
- Sacar del indice de git todos los artefactos locales.
- Mantener documentacion actualizada y coherente.
- Mantener fuera del flujo activo scripts de prueba antiguos.
- Mejorar el paquete distribuible con un `LEEME_INSTALACION.txt` que distinga entradas de usuario, mantenimiento y diagnostico.

Estado 2026-05-17: fase en cierre. La documentacion ya existe, la app funciona con rutas multi-curso y `.env`, logs, caches, salidas, verificaciones temporales y correcciones generadas no deben aparecer en `git ls-files`.

Decision de orden actual: no mover todavia los scripts Windows a `scripts/`, porque el instalador, el paquete ZIP y los accesos directos esperan varios lanzadores en raiz. La limpieza profesional se hara en dos pasos: primero paquete y documentacion claros; despues refactor de carpetas con wrappers de compatibilidad.

El paquete de usuario final no replica el repositorio completo. `crear_paquete_windows.ps1` usa una lista blanca de archivos necesarios y genera dentro del ZIP `LEEME_INSTALACION.txt`, `GUIA_USUARIO.txt` y `MANIFIESTO_PAQUETE.json`. Quedan fuera documentos de desarrollo como `AGENTS.md`, `ESTADO_PROYECTO.md`, `ARQUITECTURA_PROYECTO.md`, roadmap, checklist de release y scripts de preparacion interna.

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
  test_importacion_json.py
scripts/
  instalar_windows.ps1
  instalar_windows.cmd
  iniciar_app_windows.cmd
docs/
  seguridad/
  operacion/
legacy/
  # Solo si alguna referencia historica vuelve a ser necesaria.
```

Fase 3:

- Tests unitarios para importacion JSON/CSV, limpieza de prompts y borrado parcial de `revision_pendiente.csv`.
- Tests de endpoints locales con token anti-CSRF.
- Separar UI HTML/CSS/JS de `interfaz_app.py`.
- Crear checklist de release antes de distribuir.

## Frontera CARM vs nucleo reutilizable

Revision 2026-06-03: el corrector CARM contiene varias piezas que ya no son
exclusivas de CARM. Para crear otros correctores sin copiar y pegar un bloque
gigante, la separacion objetivo debe ser:

### Adaptador especifico CARM

Pertenece a CARM porque depende de `formacion.carm.es`, selectores, filtros,
URLs, tabla de grading o decisiones de operacion propias de CARM:

- `ExtractorCarm`: login, deteccion de cursos CARM, cacheado didactico desde
  CARM, descarga de entregas, filtros `Requiere calificacion`/`Enviada`, subida
  asistida, contraste y regularizacion de suspensos.
- `CacheCursoCarm`: por ahora esta acoplada a curso CARM y a la forma en que
  se extraen unidades/casos desde CARM. Puede evolucionar a `CacheCursoMoodle`
  solo cuando el taller tenga una interfaz comun de actividades.
- Configuracion CARM: `CARM_USUARIO`, `CARM_CONTRASENA`,
  `CARM_COURSE_URL`, `CARM_DASHBOARD_URL`, sesion recordada y limpieza al
  cambiar de cuenta.
- UI CARM: textos de marca, regularizacion de suspensos CARM, diagnosticos y
  acciones avanzadas que entran en CARM.

### Nucleo comun de correctores Moodle

Estas piezas no deberian vivir conceptualmente como "CARM", aunque hoy esten
en `corrector_agente.py` o `interfaz_app.py`:

- Lectura de entregas y extraccion de texto: `LecturaEntrega` y la parte de
  `GeneradorSalidas` que lee HTML, DOCX, ODF, RTF, PDF, OCR, PPTX, XLSX, ZIP,
  PAGES, EPUB e imagenes.
- Motor de prompts: `GestorPrompts`, construccion de prompts por lotes,
  `prompt_index.json`, manifiesto de entregas, filtros de entregas legibles y
  revision manual.
- Motor IA/API/Codex: `CorrectorIA`, comprobacion OpenAI, seleccion de modelo,
  solucion de prompts con API y solucion con Codex App.
- Importacion y revision: lectura de `*_correccion.json`, normalizacion de
  notas/criterios/retroalimentacion, generacion de `revision_pendiente.csv`,
  estados bloqueantes y casos marcados como revision manual.
- Archivo y limpieza de prompts: deteccion de prompts ya resueltos, duplicados,
  JSON sin filas, resumenes usados y retencion local.
- Seguridad local generica: redaccion de logs, pseudonimos, token local del
  panel, no versionar datos sensibles, purga local y trace solo bajo peticion.
- UI comun: tema, contraste, tamanos, bandeja, instancia unica, reinicio,
  boton detener, salud local, configuracion OpenAI y carpetas por
  corrector/curso.

### Corte recomendado para el taller

No extraer todo de golpe. El primer corte seguro es crear un paquete comun
para funciones puras y poco acopladas:

```text
moodle_corrector_core/
  prompts.py        # prompt_index, filtros, nombres *_correccion.json
  corrections.py    # importar JSON, revision CSV, estados bloqueantes
  documents.py      # lectura/extraccion de archivos
  ai.py             # OpenAI/Codex App
  security.py       # redaccion, pseudonimos, retencion
  paths.py          # rutas por corrector/curso
```

El adaptador CARM llamaria a ese nucleo, y cada nuevo corrector tendria su
propio adaptador Moodle:

```text
corrector_carm/adapters/carm.py
corrector_escuela_musica/adapters/moodle_local.py
```

Regla de seguridad: mientras CARM sea el corrector operativo, no mover clases
grandes (`ExtractorCarm`, `GeneradorSalidas`) sin tests de equivalencia. Primero
extraer funciones puras y escribir pruebas que comparen comportamiento con el
flujo actual.

## DevOps local antes de Fase 5

El flujo de despliegue seguro se aplica en escala local:

- Codigo: raiz del proyecto, con `corrector_agente.py` e `interfaz_app.py` como ejecutables activos.
- Git: no versionar `.env`, caches, logs, entregas, salidas ni correcciones generadas.
- Build local: `crear_paquete_windows.cmd` y futuro `.exe` local.
- Lanzador Windows: `crear_launcher_windows.cmd` genera `Corrector CARM.exe` con icono propio; arranca directamente `pythonw.exe interfaz_app.py` sin consola visible y no contiene credenciales ni datos.
- Instalador guiado: `INSTALAR_CORRECTOR_CARM.cmd` llama a `instalador_guiado_windows.ps1`, copia la app a la carpeta elegida, prepara `.corrector_app.json` con carpeta de datos configurable y despues ejecuta el instalador tecnico.
- Test: `verificar_app.py`, endpoints locales, importacion JSON/CSV, aislamiento cuenta/curso, JS embebido e iconos.
- Instalacion limpia: probar ZIP/paquete en una carpeta temporal sin secretos.
- Produccion local: panel en `127.0.0.1`, token local y subida asistida con revision humana.
- Simulacion de fallo: permisos Playwright, credenciales ausentes, puerto ocupado, paquete sin `.env`, cache incompleta y errores de UI.

Docker, Compose, orquestacion y despliegue cloud no forman parte de la arquitectura activa. Se reservan para Fase 5 si la herramienta deja de ser una app local y pasa a servidor, multiusuario o uso institucional coordinado.

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
- Al guardar credenciales de una cuenta CARM distinta, la interfaz limpia curso activo, cursos seleccionados y sesion recordada para no reutilizar carpetas o CSV de otro docente.
- El verificador local simula cambio de cuenta y comprueba que los cursos seleccionados antiguos no se heredan.

Regla: antes de activar varios cursos a la vez, cada curso debe tener rutas, CSV, prompts y logs suficientemente visibles para que el docente sepa que esta subiendo al curso correcto.

## Criterios de limpieza futura

Un archivo se considera obsoleto si:

- no lo referencia ningun flujo activo;
- duplica informacion ya mantenida en otro documento;
- contiene rutas antiguas como `temporal\prompts_codex` para prompts pendientes;
- recomienda publicacion automatica como flujo normal;
- contiene datos generados o personales.

Antes de borrar, mover o renombrar archivos usados por scripts de Windows, actualizar README, QUICKSTART y este documento.
