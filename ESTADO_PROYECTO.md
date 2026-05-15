# Estado del proyecto: agente corrector CARM

## Actualizacion 2026-05-14

Estado actual: seguimos en la puerta pre-Fase 5. La prioridad ya no es abrir infraestructura cloud, sino cerrar la app local instalable y dejarla suficientemente estable para uso real en Windows.

- Actualizacion 2026-05-15: el docente confirma que el flujo multi-curso funciona. Se corrige un bloqueo de la interfaz provocado por operadores ternarios rotos dentro del JavaScript embebido del panel; el sintoma era que el selector de correcciones quedaba en `Cargando fuentes de correccion...` y el log aparecia vacio. La instancia local se reinicio y se valido con Playwright contra `http://127.0.0.1:8765` sin errores de pagina ni consola.
- Mejora visual 2026-05-15: se actualizan icono de bandeja, favicon, marca del panel y avisos internos por tipo. Las notificaciones de Windows pasan a clasificar `info`, `success`, `warning` y `error`, con deduplicacion temporal para evitar avisos repetidos.
- Icono Windows 2026-05-15: se anade `assets/corrector_carm.ico` y `assets/corrector_carm.png` con libreta, lapiz y marca de revision. El panel, la bandeja y los accesos directos usan el icono propio de la app.
- Icono interfaz 2026-05-15: la cabecera y el favicon del panel ya cargan directamente `/assets/corrector_carm.png` y `/assets/corrector_carm.ico`; antes la cabecera aun usaba un dibujo CSS antiguo.
- Notificaciones Windows 2026-05-15: se prioriza `pystray` para notificar desde la bandeja de la propia app y evitar que Windows muestre `Windows PowerShell` como origen. La ruta PowerShell queda solo como fallback si no existe icono de bandeja. Para eliminar por completo cualquier branding de Python/launcher en una version distribuible, el siguiente paso seria empaquetar en `.exe` con AppUserModelID propio.
- Verificacion preventiva: `verificar_app.py` incorpora una comprobacion del JavaScript embebido para detectar ternarios rotos antes de que vuelvan a congelar el panel.
- Release 2026-05-15: `preparar_release.py` pasa completo y genera `release_manifest_0.3.0-local_20260515_055225.json`. `crear_paquete_windows.cmd` genera `Corrector_CARM_0.3.0-local_guiado_20260515_075223.zip` con los iconos propios incluidos.
- Prueba instalacion limpia 2026-05-15: el ZIP guiado se extrae sin secretos ni artefactos generados, el instalador crea `.venv`, instala dependencias base, crea `.env` desde plantilla y compila la app. El verificador en modo instalacion pasa correctamente; las credenciales CARM y el curso activo quedan como configuracion posterior.
- Decision DevOps 2026-05-15: el flujo de despliegue seguro del documento se adopta como pipeline local Windows: codigo, Git, build local, verificacion, paquete/instalacion limpia, produccion local en `127.0.0.1`, simulacion de fallos locales y operacion con revision humana. Docker/Compose/cloud quedan reservados para Fase 5; antes de eso, la mejora adecuada es empaquetar en `.exe` local.
- Launcher Windows 2026-05-15: se incorpora `crear_launcher_windows.cmd` / `.ps1` para generar `Corrector CARM.exe` con icono propio. Es un lanzador local que abre el panel mediante `iniciar_app_windows.ps1`; no incluye secretos, cache ni datos de alumnos y conserva el instalador actual para dependencias/Chromium.
- Instalador guiado 2026-05-15: `INSTALAR_CORRECTOR_CARM.cmd` abre una ventana de configuracion basica. Permite elegir carpeta de instalacion, carpeta de datos/descargas, acceso directo, inicio con Windows activado por defecto y apertura al finalizar; luego copia la app, prepara `.corrector_app.json` y ejecuta el instalador tecnico.
- Correccion cache multi-curso 2026-05-15: se repara un fallo SQL en `CacheCursoCarm` donde habian desaparecido placeholders `?` de varias consultas SQLite, provocando `near ",": syntax error` al ejecutar `--cachear-curso`. `verificar_app.py` incorpora una prueba offline de operaciones basicas de cache SQLite para detectarlo antes de tocar CARM.
- Correccion subida asistida 2026-05-15: se reparan ternarios JavaScript rotos dentro de `corrector_agente.py` que provocaban `Page.evaluate: SyntaxError: Unexpected token ':'` al mostrar la guia de subida asistida o rellenar feedback. `verificar_app.py` ahora revisa tambien JavaScript embebido usado por Playwright, no solo el panel local.
- Correccion extraccion 2026-05-15: las entregas cuyo texto extraido queda vacio, con muy pocas palabras utiles o solo con vinetas/listas pasan a `revision_manual_necesaria` en vez de corregirse automaticamente con nota 0. Caso real detectado: PDF con contenido visible como imagen pero casi sin texto extraible; las filas de Ana Tellaeche en el CSV del curso 1589 se recalificaron revisando las paginas renderizadas y quedaron listas para revision/subida asistida.
- OCR PDF 2026-05-15: `requirements-extraccion.txt` incorpora `pypdfium2` y `corrector_agente.py` añade fallback OCR para PDF escaneados: primero intenta `pypdf`, y si el texto extraido es insuficiente renderiza paginas y usa Tesseract. Si falta `tesseract.exe`, la entrega queda en revision manual con motivo claro. El panel de estado local muestra `pypdfium2` y `Tesseract OCR`.
- Instalacion OCR 2026-05-15: se añaden `instalar_ocr_windows.cmd` / `.ps1` para instalar Tesseract OCR mediante `winget` cuando el equipo lo permita. El instalador guiado muestra una casilla para instalar OCR y pasa `-InstalarOCR` al instalador tecnico; si falla, la app no se aborta y esos archivos quedan como revision manual. Tras instalarlo hay que reiniciar la app para refrescar el `PATH`.
- OCR instalado en equipo de desarrollo 2026-05-15: Tesseract 5.4 queda instalado en `AppData\Local\Programs\Tesseract-OCR` con idiomas `eng`, `osd` y `spa`. La app ya lo detecta aunque la consola antigua no tenga el `PATH` refrescado, y la prueba sobre PDF escaneado real de Ana extrae texto suficiente sin revision manual.
- Formatos ampliados 2026-05-15: la lectura de entregas admite ahora `.docm`, `.pptm`, `.xlsm`, `.ods`, `.odp`, `.epub` e imagenes OCR `.bmp`, `.tif`, `.tiff`, `.webp`. Los ZIP pueden contener tambien imagenes OCR y formatos ampliados, manteniendo limites de tamaño, numero de archivos y rutas internas seguras.
- Ortografia feedback 2026-05-15: se refuerzan `prompts_correccion.json` y los prompts generados para exigir español con tildes y eñes. `sanitizar_feedback` corrige tildes frecuentes en retroalimentacion/comentarios importados o generados por API, y `verificar_app.py` incorpora una prueba de prompt ortografico para evitar volver a enviar instrucciones sin acentos.
- Codex App sin API 2026-05-15: se probo `codex exec` con el ejecutable de la extension ChatGPT/Codex de VS Code, pero se descarta como ruta operativa porque el objetivo es depender de Codex Desktop, no de VS Code. El flujo `--corregir-prompts-codex-app` y el boton `Corregir con Codex App` quedan preparados, pero solo se habilitan si Windows expone un CLI ejecutable de Codex Desktop que no proceda de la extension de VS Code.
- Proyecto Codex por curso 2026-05-15: la interfaz puede exportar un proyecto local en `C:\temp\vscodec\cursos\<course_id>\codex_project` con cache didactica y enunciados, sin entregas ni datos personales de alumnos. Se crea/actualiza automaticamente al seleccionar un curso con cache disponible y al terminar un escaneo de curso. Se añade boton `Abrir proyecto Codex` y opcion de iniciar Codex App con ese proyecto junto al Corrector al arrancar Windows. `codex_project` queda tratado como carpeta operativa solo para Codex: ignorada por Git, bloqueada en el paquete ZIP y fuera del flujo de subida a CARM. La instalacion automatica de Codex queda como logica futura de Fase 5/instalador avanzado, no se fuerza todavia.
- Codex App workspace 2026-05-15: Codex Desktop instalado como app MSIX expone protocolo `codex://`, pero en el equipo de desarrollo no declara alias de consola `codex` ni permite ejecutar directamente sus binarios internos desde `WindowsApps`. Por tanto, abrir el proyecto desde la app queda limitado a cuando exista CLI oficial disponible; mientras tanto, el proyecto `codex_project` se mantiene para uso manual con Codex Desktop y para una futura integracion oficial sin VS Code.
- Instalador y Codex 2026-05-15: el asistente guiado añade la opcion `Preparar integracion con Codex App sin API`. El instalador tecnico acepta `-PrepararCodex`, detecta la app de escritorio `OpenAI.Codex` y no usa el `codex.exe` de la extension ChatGPT/Codex de VS Code para automatizar correcciones. Si Codex Desktop no expone CLI ejecutable, la app avisa y mantiene API/modo manual.
- Codex CLI oficial 2026-05-15: se instala Node.js LTS y `@openai/codex` con npm. La app pasa a preferir `C:\Users\<usuario>\AppData\Roaming\npm\codex.cmd`, inyecta `C:\Program Files\nodejs` en el entorno de ejecucion y evita `codex.ps1` para no chocar con la politica de ejecucion de PowerShell. `verificar_app.py --instalacion --sin-endpoints` ya marca Codex Desktop/CLI como OK con sesion ChatGPT.
- Robustez Codex 2026-05-15: el flujo `--corregir-prompts-codex-app` comprueba `codex --version` y `codex login status` antes de lanzar correcciones, limpia avisos internos de temporales y reintenta una vez si detecta fallo temporal de red/servicio/rate limit. Al abrir el proyecto Codex desde la interfaz, si Codex Desktop mantiene bloqueado algun archivo del `codex_project`, la app no falla: abre el proyecto existente y avisa de que no pudo refrescarlo en ese momento.
- Traspaso a otro ordenador 2026-05-15: `QUICKSTART.md` y `README.md` documentan el arranque limpio en Windows, que no se copian `.env`, cache, logs, salidas ni `.venv`, y que para Codex sin API hay que instalar Node.js LTS, `npm i -g @openai/codex` y ejecutar `codex login`. La ruta esperada del CLI oficial es `AppData\Roaming\npm\codex.cmd`; el flujo de VS Code queda fuera.
- Instalacion guiada: existen `INSTALAR_CORRECTOR_CARM.cmd`, `ABRIR_CORRECTOR_CARM.cmd` y `crear_paquete_windows.cmd`. El paquete guiado excluye `.env`, `.venv`, logs, cache, entregas y correcciones generadas.
- Primer paquete local guiado preparado para otro Windows: `Corrector_CARM_0.3.0-local_guiado_*.zip`.
- Credenciales: `.env.example` deja `CARM_USUARIO` y `CARM_CONTRASENA` vacios para que la app no confunda valores de plantilla con credenciales reales.
- Inicio tras login: al guardar credenciales CARM correctas, la interfaz lanza autodeteccion de cursos. Al seleccionar curso, si falta cache didactica util, programa el cacheo del curso.
- Carpetas por curso: quedan activadas por defecto. El curso activo recalcula `pendientes` y `temporal` hacia `C:\temp\vscodec\cursos\<course_id>\...`.
- Cache didactica: `corrector_agente.py` descarga contenido imprimible real cuando lo encuentra, extrae texto de recursos enlazados, guarda resumen local por unidad y descarta paginas indice/mapa de Moodle como contexto didactico.
- Optimizacion de tokens: las correcciones por API y los prompts externos usan solo el contexto de la unidad de la actividad, no todo el curso. El resumen local por unidad se limita con `MAX_RESUMEN_DIDACTICO_CHARS`.
- Codificacion: `verificar_app.py` incluye comprobacion anti-mojibake para textos versionados. Los archivos principales se validan en UTF-8; si PowerShell muestra caracteres raros suele ser un problema de codepage de consola, no del archivo.
- Verificacion: `verificar_app.py --instalacion --sin-endpoints` paso en verde tras los ultimos cambios. El release completo tambien pasa y genera manifiesto `release_manifest_0.3.0-local_20260514_120121.json`.
- Decision de fase: no abrir Fase 5 todavia. El siguiente bloque es decidir si se prueba multi-curso real o se empaqueta una version compartible con el instalador guiado actual.

## Actualizacion 2026-05-12

Esta revision alinea estado, roadmap y arquitectura despues de la fase multi-curso.

- Actualizacion 2026-05-13: verificacion local correcta, Git limpio antes de release y etiqueta `v0.3.0-local` creada tras generar manifiesto de release.
- Fase actual: puerta pre-Fase 5. Fase 3 cerrada, Fase 4 implementada en primera version y creado `CIERRE_APP_LOCAL.md` para terminar la app local antes de plantear cloud/servidor/multiusuario.
- Ajuste subida asistida: la interfaz ya no mantiene Chromium abierto al terminar; al finalizar el ultimo alumno debe volver el resultado al proceso y actualizar `revision_pendiente.csv`. Si CARM guardo pero Moodle no lo expone de forma detectable, el panel permite confirmacion manual explicita en vez de obligar a `Omitir`.
- Verificacion local ampliada: `verificar_app.py` comprueba offline que varios `*_correccion.json` de distintas unidades importan a `revision_pendiente.csv` sin duplicar filas y que una reimportacion sustituye la correccion anterior.
- Ajuste interfaz multi-cuenta: al guardar credenciales de una cuenta CARM distinta se limpia el curso activo y la seleccion de cursos anterior, se borra la sesion recordada y se recalculan rutas para evitar usar carpetas de otro docente. Al cambiar solo de curso activo, una seleccion simple de autoprompteo pasa al nuevo curso y cada ID conserva sus carpetas propias con `Separar carpetas por curso`.
- Ajuste interfaz/autoprompteo: el panel permite preparar prompts de todo el curso desde el flujo principal y configurar autoprompteo periodico por intervalo o a una hora exacta diaria. Este autoprompteo solo genera prompts; no llama a API ni guarda en CARM.
- Ajuste subida CARM: la publicacion directa queda bloqueada por seguridad. La deteccion de guardado asistido tambien observa si el estado `Sin calificar` desaparece/cambia o si aparece `Calificado` tras pulsar `Guardar cambios`.
- Diagnostico subida: la interfaz permite activar un trace Playwright de subida asistida, guardado en `respuestas_extraidas\traces\`, desactivado por defecto por contener datos personales.
- Ajuste de esperas: al promptear o subir, las actividades sin filas en `Requiere calificacion` se omiten rapido para evitar que Playwright quede esperando datos donde no hay casos practicos pendientes.
- Deteccion CARM: si el enlace de accion de la actividad indica `0 Sin calificar`, la actividad se omite antes de abrir la tabla de grading; si indica pendientes, se sigue validando dentro de la tabla con el filtro `Requiere calificacion`.
- Ajuste critico subida asistida: una correccion que no llega a abrir formulario de CARM ya no se elimina del CSV aunque no aparezca en la tabla `Requiere calificacion`. Solo se retira del CSV si fue publicada o si el docente confirma el guardado tras abrir/rellenar el formulario.
- Saneado de feedback: se corrigen deformaciones puntuales de la palabra `respuesta` y se bloquea cualquier otro token con caracteres no esperados antes de escribir CSV, resumenes o rellenar CARM.
- Validacion real CARM: el docente confirma que el flujo actual prepara prompts correctamente, corrige con API, importa al CSV y sube a CARM mediante subida asistida con revision humana. La puerta pre-Fase 5 queda muy avanzada; falta completar release/higiene documental y decidir si se prueba multi-curso real.
- Release local: `verificar_app.py` completo pasa en verde y `preparar_release.py` genera manifiesto `release_manifest_0.3.0-local_20260514_084143.json`. No se crea etiqueta porque hay cambios locales pendientes de revisar/commit.
- Multi-curso: el curso activo queda guardado como `active_course_id` independiente de la lista de cursos para autoprompteo; al cambiar el selector de curso, las carpetas activas pasan a `C:\temp\vscodec\cursos\<course_id>\...`.
- Revision de rendimiento local: se redujeron esperas basadas en `networkidle` en paginas de enunciado/formulario, se cachea la revision Git del panel y se evita solapar refrescos del navegador.
- Limpieza operativa: Codex CLI integrado queda desactivado como ruta principal para evitar bloqueos/rutas obsoletas. El flujo sin API actual es `$C` externo o Codex/ChatGPT manual + `Importar JSON a revision`.
- Ajuste inicio Windows: `iniciar_app_windows.ps1` no lanza otra instancia si el panel ya responde en el puerto configurado. El acceso de inicio instalado se reescribio sin `--auto-correct` y minimizado para evitar ventanas de comando repetidas.
- Rutas activas: con `Separar carpetas por curso` activado, el curso `1592` usa `C:\temp\vscodec\cursos\1592\pendientes` y `C:\temp\vscodec\cursos\1592\temporal`. Las rutas globales antiguas quedan solo como base/compatibilidad cuando esa opcion esta desactivada.
- Estado real: backend operativo, interfaz local en maduracion, autoprompteo multi-curso en primera version y subida asistida como flujo recomendado.
- El proyecto esta en fase de endurecimiento local antes de distribuir: higiene de git, rutas multi-curso, arranque de Windows, seguridad y documentacion coherente.
- Se corrigio la configuracion de curso para recalcular rutas de trabajo despues de cambiar curso o activar/desactivar carpetas por curso.
- El arranque de Windows ya no reintroduce `--auto-correct` automaticamente si el usuario no lo pidio. Para instalar arranque con autoprompteo explicito se usa `--install-startup --install-startup-auto-correct`.
- La interfaz permite activar/desactivar el arranque de Windows y elegir si ese arranque debe preparar prompts automaticamente.
- La interfaz incorpora `Estado local`, un chequeo de dependencias, Chromium, carpetas, credenciales, curso activo y artefactos sensibles en Git.
- Se anade verificacion por consola con `verificar_app.py`, `verificar_app_windows.cmd` y `verificar_app_windows.ps1`, incluyendo endpoints locales basicos con token.
- Se crea `RELEASE_CHECKLIST.md` como checklist de release local antes de distribuir o hacer una sesion real.
- Se anade versionado local con `VERSION`; la interfaz y el verificador muestran version, commit y si hay cambios locales.
- Se anade preparacion de release local con `preparar_release.py`, `preparar_release_windows.cmd` y `preparar_release_windows.ps1`; genera manifiesto y solo etiqueta con `--crear-tag`.
- `.env.example` queda actualizado, sin secretos, y cubre variables CARM, OpenAI, retencion y limites de tokens.
- Inicio Fase 4: `instalar_windows.ps1` valida Python 3.12+, comprueba codigos de salida, evita reinstalar Chromium si ya existe, ejecuta verificacion de instalacion y permite crear acceso directo con `-CrearAccesoDirecto`.
- `reparar_dependencias_windows.cmd` deja de llamar al instalador completo y usa `reparar_dependencias_windows.ps1`, con opciones para reinstalar dependencias, reinstalar Chromium y limpiar `ms-playwright\__dirlock`.
- `iniciar_app_windows.cmd` pasa a usar `iniciar_app_windows.ps1`, con comprobacion rapida y opciones de inicio `-AbrirNavegador`, `-AutoPreparar`, `-SinEscaneoInicial`.
- El chequeo local detecta `ms-playwright\__dirlock` y se documenta `SOLUCION_PROBLEMAS_WINDOWS.md` para permisos, Chromium, bandeja y puerto local.
- La interfaz acepta tambien `correcciones_codex_combinadas.json` como fuente permitida si existe, manteniendo `revision_pendiente.csv` como fuente fiable de subida.
- Se corrigio deuda critica de repositorio: `.env`, logs y algunas correcciones generadas salieron del indice con `git rm --cached`, sin borrarse del equipo local.
- Arquitectura: Fase 1 queda centrada en cerrar artefactos no versionables y documentacion coherente. Fase 2, refactor modular, sigue pendiente.

## Actualizacion profesional 2026-05-09

Esta seccion prevalece sobre notas historicas anteriores cuando haya contradiccion.

- Flujo actual: arranque en bandeja sin autoprompteo salvo activacion explicita, resolucion de prompts bajo accion del usuario y subida asistida desde `revision_pendiente.csv`.
- No se recomienda publicacion automatica como flujo normal.
- El CSV es la fuente fiable para rellenar CARM; los resumenes son lectura humana.
- Los prompts/correcciones/resumenes usados se archivan para evitar duplicidades y gasto de API. En el flujo manual `$C`, la app no borra nada durante la correccion externa: archiva el prompt exacto y su JSON cuando el usuario importa el `*_correccion.json` a `revision_pendiente.csv`.
- El autoprompt periodico tiene intervalo propio y hora exacta diaria opcional. Si hay prompts pendientes sin corregir, una nueva tanda no los sobrescribe: se genera un nombre con fecha/hora y el manifiesto de entregas se acumula.
- `.env`, logs, cache, salidas y correcciones generadas quedan fuera de git.
- Se crea `ARQUITECTURA_PROYECTO.md` como guia de orden profesional y refactor por fases.
- Se eliminan pruebas y referencias antiguas (`prueba_correcciones.py`, `sincronizador_moodle.py`, `tmp_prueba`) para evitar rutas duplicadas u obsoletas.

### Multi-curso iniciado el 2026-05-09

Implementado:

- `corrector_agente.py --listar-cursos-carm` entra en CARM, lista cursos visibles y guarda `respuestas_extraidas/cursos_detectados.json`.
- Se separan dos URLs:
  - `CARM_DASHBOARD_URL`: area personal para detectar todos los cursos, por defecto `https://formacion.carm.es/my/index.php`.
  - `CARM_COURSE_URL`: curso activo concreto `course/view.php[x]id=...`; no tiene valor por defecto porque cada usuario puede tener cursos distintos.
- Compatibilidad: si una instalacion antigua puso la URL del area personal en `CARM_COURSE_URL`, la app la usa como dashboard. Despues hay que elegir un curso activo desde la interfaz.
- Compatibilidad adicional: la app acepta la variante antigua `https://formacion.carm.es/course/my/index.php`, pero el valor canonico documentado es `https://formacion.carm.es/my/index.php`.
- La interfaz muestra un selector de curso activo en la cabecera.
- La configuracion permite activar `Separar carpetas por curso`.
- Con carpetas por curso activadas, las rutas de trabajo pasan a:
  - `C:\temp\vscodec\cursos\<course_id>\pendientes`
  - `C:\temp\vscodec\cursos\<course_id>\temporal`
- La configuracion permite marcar varios cursos para autoprompteo.
- Si hay varios cursos seleccionados y las carpetas por curso estan activas, el autoprompteo los recorre en cola, de uno en uno, pasando cada curso al subproceso con su propia `CARM_COURSE_URL`, `--pendientes` y `--temporal`.
- Si hay varios cursos seleccionados pero no esta activa la separacion por curso, la app evita mezclar datos y usa solo el curso activo.
- Los comandos que necesitan un curso concreto se bloquean con un error claro si aun no hay curso activo seleccionado.
- Si no hay curso activo, incluso con `Separar carpetas por curso` activo, la interfaz mantiene las carpetas base y no crea una carpeta falsa `sin_curso`.
- Arranque sin curso activo: la app ya no intenta cachear un curso inexistente; lanza deteccion de cursos desde el area personal.
- `Escanear ahora` sin curso activo tambien ejecuta deteccion de cursos, no cache de curso.
- La comprobacion periodica ya contempla cursos seleccionados: si hay varios cursos seleccionados y carpetas por curso activadas, actualiza la cache del primer curso seleccionado que aun no tenga cache.
- La interfaz muestra `Estado por curso` con cache, fecha de cache, prompts, JSON de correccion, filas CSV, actividades e incidencias bloqueantes por cada curso seleccionado.
- La deteccion de cursos filtra entradas auxiliares como `FAQS` y `CARM - Curso CARM`; se mantiene compatibilidad con datos antiguos, pero la interfaz ya no los muestra como cursos seleccionables.
- La configuracion de cursos ya no pisa cada pocos segundos el desplegable ni los checkboxes de autoprompteo mientras el modal de ajustes esta abierto.
- El estado local expone si el arranque de Windows esta instalado y si ese arranque incluye `--auto-correct`.
- Se detecto un arranque antiguo con `--auto-correct`; se actualizo el `.cmd` instalado para que no autopromptee al iniciar Windows salvo que el usuario lo active expresamente.

Pendiente antes de darlo por cerrado:

- Probar en CARM real con dos cursos visibles.
- Verificar que cada curso genera prompts en su carpeta propia y que el selector de curso muestra el CSV correcto.
- Mejorar la comprobacion periodica para que, ademas de cachear cursos sin cache, pueda decidir si conviene autopromptear cursos con entregas nuevas.
- Ampliar el resumen por curso con ultima ejecucion/log especifico por curso.
- Si en el futuro CARM muestra cursos reales con nombres muy distintos a `SPF...`, revisar el filtro de cursos auxiliares para no ocultarlos por error.

Validacion ejecutada:

```powershell
python -m py_compile interfaz_app.py corrector_agente.py
python -c "import interfaz_app as app; print(app.selected_course_ids()); print(app.selected_courses_for_auto()[:1])"
python -c "import interfaz_app as app; print(app.dashboard_url()); print(app.current_course_url())"
python corrector_agente.py --cachear-curso
python -c "import interfaz_app as app; app.load_app_config=lambda:{}; app.read_env_values=lambda:{}; print(app.build_args('detect_course', {})); print(app.project_state()['selected_courses'])"
python -c "import interfaz_app as app; print(app.revision_csv_state(app.REVISION_CSV)); print(app.selected_course_summaries()[:1])"
python -c "import interfaz_app as app; print(app.detected_courses()); state=app.project_state(); print(state['startup_installed'], state['startup_auto_correct_enabled'], state['auto_correct_after_scan'])"
python -c "import interfaz_app as app; print(app.is_detected_course_allowed('FAQS'), app.is_detected_course_allowed('CARM - Curso CARM'), app.is_detected_course_allowed('SPF142026'))"
```

El ultimo comando debe mostrar error controlado si no hay `CARM_COURSE_URL` de curso activo.

## Actualización operativa 2026-05-08

- La previsualización desde la interfaz ya no intenta esperar `Enter` en un proceso sin consola. Rellena solo la primera corrección y deja Chromium abierto hasta que el usuario cierre la pestaña.
- La subida asistida ya no activa el modo de espera por consola: rellena nota y retroalimentación, muestra la guía de revisión humana y espera a que el usuario guarde en CARM.
- El relleno de CARM limpia primero la nota y la retroalimentación existentes antes de escribir los valores nuevos, contemplando reenvíos de alumnos o calificaciones previas.
- El panel local deja de forzar el scroll del log si el usuario no está situado al final, evitando saltos visuales mientras revisa la interfaz.
- El refresco automático del panel ya no reconstruye selects/listas/campos si no cambian y no pisa inputs enfocados. El botón "Pausar autoescaneo" queda disponible durante un escaneo inicial y detiene la detección en curso.
- Los modos de revisión/previsualización ya no piden pulsar Enter para cerrar. El navegador queda abierto hasta cerrar la pestaña o detener la tarea; la interfaz lanza los subprocesos sin ventana de consola adicional en Windows.
- Previsualización y subida asistida detectan si Moodle/CARM se queda en tabla o resumen y pulsan automáticamente "Calificar" para llegar al formulario antes de rellenar nota y feedback.
- Nota historica: se llego a probar Codex CLI, pero ya no es ruta operativa recomendada.
- Los prompts para Codex limpian el contexto procedente de cache antes de incluirlo. Si la cache contiene una página índice/mapa de Moodle en vez de contenido didáctico real, se descarta para ahorrar tokens y evitar ruido.

Última actualización: 8 de mayo de 2026

## Revisión completa 2026-05-08

**Estado técnico actual**: backend e interfaz siguen operativos, con cambios recientes centrados en estabilidad de UI, subida asistida y reducción de ruido en prompts.

**Validación ejecutada en esta revisión**:

```powershell
.\.venv\Scripts\python.exe -m py_compile corrector_agente.py interfaz_app.py verificar_app.py preparar_release.py
```

Resultado: OK.

**Archivos modificados actualmente en git**:

- `.env.example`: variables CARM/OpenAI/retencion sin ruta de Codex CLI.
- `corrector_agente.py`: cambios de subida/previsualización, limpieza de prompts y desactivacion del flujo CLI integrado.
- `ESTADO_PROYECTO.md`: actualización de estado.
- `logs_correcciones/agente.log`: log de ejecución local, ignorado por `.gitignore`.

**Hallazgos importantes**:

- Codex CLI queda como prueba historica; el flujo actual usa prompts externos e importacion de JSON.
- Los prompts actuales se han limpiado para no incluir navegación/JS/mapa de Moodle. Si la cache trae una página índice en vez de contenido didáctico real, el generador la descarta.
- La cache didáctica aún no descarga/lee el PDF real de "Contenido imprimible"; ahora detecta el índice como ruido. Próximo paso claro: resolver enlaces a PDF de contenido imprimible y cachear texto didáctico real.
- El flujo de previsualización/subida asistida ya no debe pedir `Enter`, debe intentar entrar automáticamente al formulario `Calificar`, y debe limpiar nota/feedback previos antes de rellenar.
- En logs se observó solapamiento de cacheos al inicio; la UI ya permite pausar/detener autoescaneo, pero conviene probarlo tras reiniciar la app para verificar que no quedan procesos antiguos.

**Riesgos abiertos**:

- Falta una prueba real final de subida asistida completa en lote con varios alumnos de la misma actividad.
- La subida asistida usa `Guardar cambios` y confirmacion humana; no depende de `Guardar cambios y mostrar siguiente`.
- La cache didáctica debe mejorar para extraer PDFs/recursos enlazados, no solo `innerText` de páginas Moodle.
- Las pruebas offline antiguas se han retirado; la verificacion actual usa compilacion, salud local y endpoints con token.

## Resumen ejecutivo

**Estado general**: Operacional. Backend implementado y probado con éxito.

El sistema funciona en ciclos completos desde descarga hasta publicación:

[x] **Funcionalidades implementadas y probadas**:
- Extrae entregas desde CARM/Moodle con Playwright
- Filtra por unidad, actividad o "Requiere calificación"
- Descarga solo archivos necesarios, registra incidencias
- Genera prompts optimizados para Codex
- Corrige mediante API de OpenAI o mediante JSON resuelto fuera con `$C`/Codex/ChatGPT
- Importa correcciones JSON a archivos `.txt` por alumno
- Genera CSV de revisión (`revision_pendiente.csv`)
- Previsualiza en local antes de publicar
- Publica notas y feedback en CARM
- Interfaz web local en `interfaz_app.py`

[!] **Requisitos previos**: La subida a CARM requiere verificación humana. Flujo: preparar → revisar local → publicar tras validación.

## Objetivo

Automatizar la corrección de casos prácticos de CARM Formación reduciendo trabajo repetitivo, sin perder control humano sobre notas y retroalimentación.

El flujo objetivo actual es:

1. Entrar en CARM.
2. Detectar casos prácticos obligatorios que requieren calificación.
3. Descargar entregas.
4. Recoger enunciado y contexto de unidad.
5. Generar prompts por actividad.
6. Corregir con API o resolver prompts fuera de la app e importar JSON.
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
  - Preparacion de prompts e importacion de JSON externos
  - Importación de salidas
  - Subida asistida a CARM
  - Soporta flags: `--preparar-carm-codex`, `--corregir-prompts-openai`, `--subir-correcciones-carm`, `--subida-asistida-carm`

- **`interfaz_app.py`**: interfaz web local
  - Servidor HTTP local en puerto 8765
  - Gestión de sesión con token
  - Navega correcciones y publica desde navegador
  - Controles CSRF activados

### Archivos de configuración

- **`.env.example`**: plantilla de variables (copia a `.env` y rellena)
- **`.env`** (local, no compartir): credenciales CARM, API keys
- **`prompts_correccion.json`**: rúbricas JSON por actividad
  - Usa `"default"` como base
  - Añade claves tipo `"ud02cp03"` para rúbricas específicas

### Dependencias

- **`requirements.txt`**: dependencias base (Playwright, OpenAI, dotenv, pystray, Pillow)
- **`requirements-extraccion.txt`**: opcional para leer PDF/PDF escaneados, PPTX/PPTM, XLSX/XLSM, ODF, EPUB, ZIP e imagenes OCR

## Directorios y estructura de salidas

### Carpetas principales de datos

| Carpeta | Descripción |
|---------|-------------|
| `cache_carm/` | Cache SQLite del curso (`curso_1592.sqlite`) |
| `correcciones_validadas/` | [x] Historial de correcciones JSON validadas |
| `logs_correcciones/` | Logs Logs de ejecución del agente |
| `respuestas_extraidas/` | 📊 Auditoría de descargas y subidas |

### Carpetas de trabajo (externas, en `C:\temp\vscodec\`)

| Ruta | Descripción |
|------|------------|
| `pendientes/` | 📥 Entregas descargadas desde CARM |
| `temporal/` | 📤 Salidas generadas (alumno, actividad, resúmenes) |
| `pendientes/prompts_codex/` | 🤖 Prompts pendientes de resolver, JSON de correcciones y manifiesto |

### Archivos clave generados en salida

```
C:\temp\vscodec\
|------ pendientes\
|   `------ prompts_codex\
|       |------ prompt_udXXcpYY.md                  # Prompt pendiente de resolver
|       |------ prompt_udXXcpYY_correccion.json     # Respuesta JSON individual
|       `------ manifiesto_entregas.json            # Inventario de entregas
|------ temporal\
|------ revision_pendiente.csv                      # Resumen + scores para revisar
|------ <nombre_alumno>/
|   |------ ud01cp01.txt                            # Entrega original
│   ├── ud01cp01_resumen.txt                    # Corrección JSON legible
|   `------ resumen_global_<alumno>.txt             # Notas de todas sus actividades
`------ ...
```

**Workflow de revisión**:
1. Revisar `revision_pendiente.csv` (notas rápidas)
2. Explorar `temporal/<alumno>/` (correcciones por actividad)
3. Validar `revision_pendiente.csv` como archivo principal de subida; en modo prompts/Codex se importan los `*_correccion.json` individuales
4. Si todo OK -> subida asistida con guardado humano.

En modo API desde la interfaz, el flujo queda en dos fases: preparar prompts acumulados sin gastar API y, cuando el usuario lo confirme, ejecutar `--corregir-prompts-openai` para generar JSON, CSV revisable y salidas listas para subir.

`--corregir-prompts-openai` estima tokens antes de enviar cada prompt. Avisa por defecto a partir de ~100k tokens y bloquea por seguridad a partir de ~180k, para evitar llamadas destinadas a fallar por límites. Se puede ajustar con `--openai-warn-tokens-prompt` y `--openai-max-tokens-prompt`.

## Comandos operacionales

### Comando principal: Preparar prompts

```powershell
.\.venv\Scripts\python.exe corrector_agente.py --preparar-carm-codex --unidad ud01 --max-entregas-por-prompt 0
```

**Qué hace**:
1. Entra en CARM (requiere credenciales en `.env`)
2. Descarga entregas de la unidad `ud01`
3. Agrupa por actividad (ud01cp01, ud01cp02, etc.)
4. Genera prompts optimizados para Codex
5. **NO publica** en CARM ni corrige con CLI integrado
6. Espera que se resuelvan los prompts fuera de la app y se importen los JSON

**Salida de preparacion**:
```
C:\temp\vscodec\cursos\<course_id>\pendientes\prompts_codex\prompt_udXXcpYY.md
```

**Flags opcionales**:
- `--unidad ud01`: filtra por unidad (ud01, ud02, ..., ud15)
- `--max-entregas-por-prompt 6`: agrupa entregas en lotes
- Omitir `--unidad` para procesar todo sin filtrar

### Comando secundario: Subida asistida tras revisar

```powershell
.\.venv\Scripts\python.exe corrector_agente.py --subir-correcciones-carm C:\temp\vscodec\cursos\<course_id>\temporal\revision_pendiente.csv --subida-asistida-carm
```

**Qué hace**:
1. Lee `revision_pendiente.csv`
2. Rellena notas y feedback en CARM
3. Espera guardado humano confirmado

**Seguridad**:
- El docente pulsa `Guardar cambios` en CARM
- La app comprueba que CARM haya guardado antes de avanzar
- Elimina del CSV solo filas cuyo formulario se ha abierto/rellenado y cuyo guardado ha sido confirmado por el docente.

### Comando de prueba local (sin CARM)

```powershell
.\.venv\Scripts\python.exe verificar_app.py --sin-endpoints
```

**Úsalo para**:
- Testing sin conectarse a CARM
- Verificacion local sin datos sinteticos antiguos
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
- Deteccion de cursos visibles desde CARM con `--listar-cursos-carm`.
- Selector de curso activo en la interfaz.
- Separacion opcional de carpetas por curso en `C:\temp\vscodec\cursos\<course_id>\`.
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
- `--corregir-prompts-openai`

El modo recomendado es preparar prompts primero y resolverlos despues con API bajo confirmacion o con Codex/IA externa.
Los flags antiguos de Codex CLI quedan desactivados para evitar bloqueos por PATH, sesion o limites externos.

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
- Modo subida asistida con `--subida-asistida-carm`.
- Publicacion directa desactivada; la ruta operativa es subida asistida.
- Rellena nota.
- Rellena solo la seccion de retroalimentacion final, no el detalle completo de criterios.
- Soporta editor Atto/Moodle escribiendo en el campo oculto y en el editor visible.
- Usa `Guardar cambios` en CARM y espera confirmacion humana con deteccion de guardado.
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
- `ud01cp02` se corrigio e importo para Elisabet y Carolina.
- La subida a CARM se probo en previsualizacion: nota y comentario ya se rellenan.
- Se ajusto para subir solo la retroalimentacion final, no todo el bloque de criterios.

## Seguridad: Estado actual (2026-05-07)

## Cumplimiento normativo: avance 2026-05-08

## Estado operativo actualizado: 2026-05-09

Flujo acordado:

- Al iniciar Windows, la app se abre en bandeja sin autoprompteo por defecto. `--auto-correct` solo se usa si el usuario activa autopreparacion al inicio.
- Con carpetas por curso activadas, los prompts pendientes viven en `C:\temp\vscodec\cursos\<course_id>\pendientes\prompts_codex`.
- El modo con API solo se ejecuta cuando el usuario pulsa `Corregir prompts con API`; antes de gastar API archiva prompts que ya tienen `*_correccion.json` para no duplicar coste.
- El modo sin API usa `INSTRUCCIONES_CODEX_PERSONALIZADAS.md` y genera JSON individuales `prompt_<actividad>_correccion.json`; la interfaz principal tiene boton `Importar JSON a revision` para pasar un JSON concreto o todos los JSON pendientes a `revision_pendiente.csv`.
- La fuente fiable para subir a CARM es `revision_pendiente.csv` dentro de la carpeta temporal activa del curso, no los resumenes.
- La interfaz de subida muestra un unico boton de subida asistida con el numero exacto de filas pendientes por actividad.
- La subida asistida rellena nota y feedback, exige que el usuario pulse `Guardar cambios` en CARM, detecta guardado real antes de avanzar y elimina del CSV solo filas confirmadas tras abrir/rellenar formulario.
- Cuando una actividad queda gestionada, se archivan prompts, correcciones y resumenes usados.

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
- Tras publicacion real o subida asistida completada, los prompts/JSON usados se archivan en `pendientes/prompts_codex/archivados/` para evitar reutilizar archivos antiguos por error. La previsualizacion no archiva.
- Tras generar prompts, las entregas usadas se mueven de `pendientes` a `pendientes/archivados_prompt/` para que no vuelvan a entrar en otro prompt accidentalmente. Se puede evitar con `--conservar-pendientes`.
- Instalacion Windows automatizada con `instalar_windows.cmd` / `instalar_windows.ps1`: crea `.venv`, instala dependencias base, instala Chromium de Playwright y prepara `.env`. Inicio recomendado con `iniciar_app_windows.cmd`.
- Arrancar en bandeja (`--tray`) no gasta API ni publica automaticamente. Con `--auto-correct` se activa el autoprompteo: revisar CARM, preparar prompts y dejar la correccion para confirmacion posterior.
- Configuracion permite pausar autoescaneo (`0` minutos), reactivarlo a 60 minutos y lanzar escaneo manual. La tarea en curso se puede cancelar con `Detener`.

Decisión: no activar purgas automáticas agresivas de entregas/notas mientras el flujo de descarga y revisión sigue en desarrollo. La purga de datos personales queda como acción manual confirmada; la cache didáctica sí puede purgarse automáticamente por `CARM_COURSE_END_DATE`.

Decision de subida humana asistida: se prioriza el modo asistido frente a la publicacion totalmente automatica. La app recomienda `Guardar cambios`, comprueba que CARM haya guardado antes de avanzar y la accion final de guardado sigue siendo humana.

### Implementado (Prioridad Alta completada)

[x] **1. Token local anti-CSRF en interfaz**
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
- Probado previamente con datos sinteticos; esas pruebas antiguas ya fueron retiradas del repo.

[x] **3. Endurecimiento de lectura de archivos de alumnos**
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

[ ] **2. Guardar credenciales CARM con Windows DPAPI**
- Descifra credenciales desde `.env` con `dpapi` de Windows
- Evita guardarlas en texto plano
- Requiere: investigar integración con `ctypes` de Python
- Impacto: credenciales cifradas con usuario Windows

[ ] **5. Redacción/limpieza de logs sensibles**
- Logs actualmente contienen: nombres de alumnos, actividades, estado de subida
- Propuesta: ofuscar nombres, emails, URLs sensibles
- Mantener solo: timestamps, códigos de error, estadísticas
- Archivos: `logs_correcciones/*.log`

### Próximas medidas recomendadas (Prioridad Media)

[ ] **6. Auditoría local de acciones sensibles**
- Registro de: quién (sesión), cuándo, qué acción (descarga, corrección, publicación)
- Almacenar en: `respuestas_extraidas/auditoria.json`
- Información: timestamps, flags utilizados, resultado

[ ] **7. Separación de datos didácticos vs personales**
- Cache didáctica (contenido/enunciados): en `cache_carm/`
- Entregas/notas/alumnos: en carpetas temporales con purga clara
- Flag: `--purgar-datos-temporales-al-finalizar-curso`

[ ] **8. Confirmación fuerte para publicar**
- Botón bloqueado hasta completar revisión limpia
- Confirmación explícita tipo "PUBLICAR SI, ENTIENDO RIESGOS"
- Interfaz: `interfaz_app.py`

### Validación en ejecución

Probado entre el 2026-05-07 y el 2026-05-08:

- `py_compile`: OK
- Verificador local: OK
- `pip check`: OK
- Interfaz web: responde en `http://127.0.0.1:8765`
- `/api/auth`: `configured: true`
- Anti-CSRF: funcional
- Flujo sin API validado mediante prompts externos e importacion de JSON.
- Prompts actuales limpiados para descartar mapa/navegación de Moodle.

## Codex externo / modo sin API

**Situacion actual**: la app no depende de Codex CLI integrado. Genera prompts, el usuario los resuelve fuera con `$C`/Codex/ChatGPT y despues importa uno o todos los `*_correccion.json` a `revision_pendiente.csv`.

Los flags antiguos de Codex CLI quedan como legado desactivado para evitar bloqueos por PATH, sesion o limites externos.

## Prompts

`prompts_correccion.json` es la fuente normal.

Los prompts internos en `corrector_agente.py` quedan como fallback.

El prompt `default` es general. El enunciado real viene de CARM y se inyecta aparte.

Las claves de ejemplo deben llevar prefijo `_ejemplo_` para no aplicarse por error.

## Próximos pasos recomendados

### Corto plazo (esta semana)

1. **Probar subida asistida real en lote controlado**
   - Usar `revision_pendiente.csv` actual tras revisión.
   - Confirmar que abre el formulario `Calificar`, limpia campos previos y rellena nota/feedback.
   - El usuario debe pulsar guardar manualmente para cumplir revisión humana.

2. **Mejorar cache didáctica real**
   - Detectar enlaces a PDF de "Contenido imprimible".
   - Descargar/leer el PDF con dependencias opcionales.
   - Guardar texto didáctico limpio en SQLite, no el mapa de Moodle.

3. **Revisar y publicar solo correcciones limpias**
   - Validar `revision_pendiente.csv`.
   - Comprobar incidencias como alumnos sin archivo.
   - Usar subida asistida antes de cualquier publicación totalmente automática.

4. **Decidir sobre DPAPI para credenciales**
   - ¿Guardar CARM con cifrado Windows
   - ¿Mantener `.env` en texto plano
   - Recomendación: DPAPI si /.env se comparte o se guarda en USB

### Mediano plazo (próximas 2-3 semanas)

5. **Refinar confirmación fuerte para publicar**
   - Botón bloqueado hasta revisión limpia
   - Confirmación modal explícita
   - Interfaz: `interfaz_app.py`

6. **Preparar para escalar a más unidades**
   - UD02, UD03, etc.
   - Validar cache con `--refrescar-cache`
   - Probar filtros por actividad específica

7. **Mantener limpieza de rutas obsoletas**
   - Evitar reintroducir scripts de prueba antiguos como rutas activas.
   - Documentar solo flujos usados por la interfaz actual.

### Largo plazo (mes siguiente)

8. **Documentación de operador**
   - Guía paso a paso: extracción → corrección → publicación
   - Troubleshooting de errores comunes
   - Video tutorial si es viable

9. **Mantener alternativa API o modelo local**
   - Si el flujo manual externo tiene limites de uso
   - Evaluar costo-beneficio
   - Adaptar prompts si cambia el modelo

## Resumen de estado para alguien nuevo

Este proyecto automatiza corrección de casos prácticos en CARM Formación:

- **¿Qué**: Descarga entregas de CARM, genera prompts/correcciones revisables, y ayuda a subir notas y feedback
- **¿Dónde**: `corrector_agente.py` es el motor principal; `interfaz_app.py` es la UI web
- **¿Cuándo**: Operacional, última revisión de proyecto el 2026-05-08
- **¿Seguridad**: Token anti-CSRF, bloqueo de publicación sin revisión, subida asistida con revisión humana, endurecimiento de ZIP, documentación ASVS/CVSS/RGPD
- **¿Próximos**: Probar subida asistida real en lote → mejorar cache didáctica con PDFs reales → revisar/publicar correcciones limpias

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
.\.venv\Scripts\python.exe -m py_compile corrector_agente.py interfaz_app.py verificar_app.py preparar_release.py
.\.venv\Scripts\python.exe corrector_agente.py --help
.\.venv\Scripts\python.exe interfaz_app.py --help
```

Tambien se probo:

- Extraccion CARM real.
- Generacion de prompts.
- Resolucion externa/importacion JSON con `prompt_ud01cp02.md`.
- Importacion de JSON de Codex.
- Previsualizacion de subida a CARM.
- Servidor local de interfaz en `/api/status`.

## Pendiente / proximos pasos

Prioridad alta:

- Validar una subida asistida real completa en un lote controlado, revisando cada guardado manual.
- Seguir probando subida asistida en lotes completos y casos ya gestionados por CARM.
- Mejorar cache didáctica: descargar/leer el PDF real de contenido imprimible en vez de guardar páginas índice de Moodle.
- Mejorar la interfaz local: vista de revision por alumno antes de subir.

Prioridad media:

- Añadir aviso visual cuando el contexto didáctico se descarta por ser índice/mapa de Moodle.
- Revisar notas generadas por Codex para calibrar severidad.
- Consolidar logs de subida con alumno, actividad, nota, boton usado y resultado.
- Anadir pantalla de incidencias: alumnos sin archivo, formatos no legibles, errores de descarga.

Prioridad baja:

- Probar OCR con Tesseract en instalacion limpia.
- Evaluar soporte `.doc` antiguo con LibreOffice o Word.
- Mantener fuera del repo datos de prueba locales y scripts obsoletos.

## Nota de continuidad

Para retomar el proyecto:

1. Leer `ESTADO_PROYECTO.md`.
2. Leer `QUICKSTART.md`.
3. Ejecutar:

```powershell
.\.venv\Scripts\python.exe -m py_compile corrector_agente.py interfaz_app.py verificar_app.py preparar_release.py
```

4. Abrir la interfaz:

```powershell
.\.venv\Scripts\python.exe interfaz_app.py
```
