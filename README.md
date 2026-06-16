# Corrector CARM

Aplicación local para corregir casos prácticos descargados desde CARM Formación/Moodle. Prepara entregas, genera prompts o correcciones con OpenAI API/Codex y ayuda a subir notas y retroalimentación con revisión humana antes de guardar nada en CARM.

La idea principal es sencilla: el docente conserva el control. La app puede preparar, rellenar y organizar, pero la publicación final en CARM requiere una acción humana explícita.

## Para Usuarios

### Descargar

[Descargar instalador para Windows](https://github.com/rubenasuasoto/agente/releases/latest/download/Corrector_CARM_0.3.0-local_Setup_20260616_084646.exe)

Ejecuta el instalador y sigue el asistente. Si Windows SmartScreen avisa de editor desconocido, es normal mientras la app no esté firmada digitalmente.

El instalador público no incluye `.env`, `.venv`, caché, logs, entregas, correcciones, proyectos Codex ni datos personales.

### Aviso de Windows SmartScreen

Windows puede mostrar un aviso indicando que el archivo no se descarga habitualmente o que el editor es desconocido. Ese aviso aparece porque el instalador aún no está firmado digitalmente y todavía no tiene reputación suficiente en Microsoft Defender SmartScreen.

Para comprobar la descarga:

1. Descarga el archivo desde el release oficial del proyecto.
2. Verifica que el nombre coincide con el publicado.
3. Compara el SHA256 con el valor indicado abajo.
4. Si no confías en el origen o el hash no coincide, no ejecutes el instalador.


<details>
<summary>Verificación de la descarga</summary>

- Versión validada: `0.3.0-local`.
- Instalador: `Corrector_CARM_0.3.0-local_Setup_20260616_084646.exe`.
- SHA256: `4C642F3AE81F0333333EA1DAC326A11A6696C53A0BD9792838C31D766200B31A`.
- ZIP guiado alternativo: `Corrector_CARM_0.3.0-local_guiado_20260616_084716.zip`.
- SHA256 ZIP: `832E5E29042DD522E294BE6126A93AC5A2889E36D72E75E7BE358F7D8D859849`.

</details>

### Qué Hace

- Detecta cursos y actividades de CARM.
- Descarga entregas pendientes de calificación.
- Prepara prompts por curso, unidad o caso práctico.
- Corrige con OpenAI API o con Codex App sin API key.
- Importa respuestas JSON a un CSV revisable.
- Rellena CARM en modo asistido, esperando el guardado manual del docente.
- Aparta entregas ilegibles o dudosas para revisión manual.

### Flujo Recomendado

```text
1. Preparar   -> detectar curso, descargar entregas y generar prompts.
2. Revisar    -> resolver con API/Codex, importar JSON y revisar el CSV.
3. Subir      -> rellenar CARM con subida asistida y guardar manualmente.
```

### Vista de la Interfaz

Capturas generadas con datos de demostración, sin credenciales ni entregas reales.

![Panel principal del Corrector CARM](docs/img/panel-principal.png)

![Configuración del Corrector CARM](docs/img/configuracion.png)

### Instalación Guiada

Si has descargado el instalador EXE, solo tienes que ejecutarlo. Si estás usando el repositorio completo, la entrada recomendada es:

```powershell
.\INSTALAR_CORRECTOR_CARM.cmd
```

El asistente prepara Python, dependencias, Chromium de Playwright, accesos directos, inicio con Windows si lo eliges y carpetas de trabajo. También puede preparar Codex CLI si quieres corregir sin API key.

La primera vez, el panel pedirá credenciales CARM y modo de corrección. Puedes trabajar con:

- OpenAI API, guardando tu API key localmente.
- Solo prompts, para resolver fuera e importar después los JSON.
- Codex App, si has iniciado sesión con ChatGPT mediante `codex login`.

### Uso Diario

1. Abre `Corrector CARM` desde el acceso directo o con `ABRIR_CORRECTOR_CARM.cmd`.
2. Entra en configuración y detecta o selecciona el curso.
3. Pulsa `Preparar prompts`.
4. Corrige con API o Codex.
5. Importa las correcciones a revisión.
6. Revisa notas y retroalimentación.
7. Usa la subida asistida para rellenar CARM.
8. Guarda manualmente en CARM cuando hayas revisado cada alumno.

### Desinstalación

La instalación se registra para el usuario actual en **Aplicaciones instaladas** de Windows como `Corrector CARM`. Desde ahí se puede desinstalar.

También puedes usar:

```powershell
.\desinstalar_windows.cmd
```

Por defecto se quita la app, accesos, inicio automático y entrada de Windows, pero se conservan los datos locales. En modo gráfico puedes elegir si borrar pendientes, temporales, cursos, caché o proyectos Codex.

### Privacidad

- La interfaz escucha solo en `127.0.0.1`.
- El paquete público no trae credenciales ni datos reales.
- `.env`, cachés, entregas, logs y correcciones quedan fuera de Git y del paquete.
- La subida a CARM es asistida: el docente revisa y guarda.
- Las capturas de diagnóstico se consideran sensibles y solo se guardan si se piden expresamente.

## Para Técnicos y Desarrollo

### Estado del Proyecto

- Versión local validada: `0.3.0-local`.
- Release local validado el 16 de junio de 2026 con ZIP guiado e instalador EXE.
- Flujo principal implementado en `corrector_agente.py`.
- Panel local implementado en `interfaz_app.py`.
- Verificación de instalación y seguridad local en `verificar_app.py`.
- Herramientas de build y release en `tools/windows`.

Con carpetas por curso activadas, las rutas de trabajo siguen este patrón:

```text
C:\temp\vscodec\cursos\<course_id>\pendientes
C:\temp\vscodec\cursos\<course_id>\temporal
C:\temp\vscodec\cursos\<course_id>\codex_project
```

### Documentación

Lectura recomendada para mantenimiento:

1. `docs/README.md`: mapa de documentación.
2. `QUICKSTART.md`: comandos rápidos de instalación, prueba y uso.
3. `SECURITY.md`: guía pública de seguridad.
4. `SEGURIDAD_ASVS.md`: controles OWASP ASVS aplicables.
5. `SEGURIDAD_CVSS.md`: priorización de riesgos.
6. `ARQUITECTURA_PROYECTO.md`: estructura y decisiones de arquitectura.
7. `RELEASE_CHECKLIST.md`: comprobaciones antes de distribuir.
8. `docs/PUBLICACION.md`: checklist para publicar el repositorio.
9. `docs/PRUEBA_INSTALADOR.md`: prueba segura del instalador.
10. `docs/DEMO_LOCAL.md`: capturas públicas sin datos reales.
11. `SOLUCION_PROBLEMAS_WINDOWS.md`: ayuda para Windows, Playwright y dependencias.
12. `ESTADO_PROYECTO.md`: memoria viva del proyecto.

### Configuración Local

Copia `.env.example` a `.env` y rellena solo tu configuración local:

```env
CARM_USUARIO=tu_usuario_carm
CARM_CONTRASENA=
OPENAI_API_KEY=<tu_api_key_openai>
OPENAI_MODEL=gpt-5-mini
CARM_DASHBOARD_URL=https://formacion.carm.es/my/index.php
CARM_COURSE_URL=
```

No subas `.env` al repositorio. `OPENAI_API_KEY` es opcional si corriges con prompts y luego importas JSON.

### Comandos de Verificación

```powershell
.\verificar_app_windows.cmd
.\verificar_app_windows.cmd --instalacion
python verificar_app.py --sin-endpoints
```

### Herramientas de Release

Las herramientas técnicas viven en `tools/windows` para mantener limpia la raíz del repositorio.

Preparar release local con manifiesto:

```powershell
.\tools\windows\preparar_release_windows.cmd
```

Crear ZIP guiado:

```powershell
.\tools\windows\crear_paquete_windows.cmd
```

Crear instalador EXE autoextraíble:

```powershell
.\tools\windows\crear_instalador_setup_windows.cmd
```

Regenerar lanzador visual:

```powershell
.\tools\windows\crear_launcher_windows.cmd
```

### Uso Sin API

Preparar prompts desde CARM sin gastar API:

```powershell
python corrector_agente.py --preparar-carm-codex --unidad ud01 --max-entregas-por-prompt 6
```

Resolver prompts con Codex App desde la interfaz o con:

```powershell
python corrector_agente.py --pendientes C:\temp\vscodec\cursos\<course_id>\pendientes --temporal C:\temp\vscodec\cursos\<course_id>\temporal --corregir-prompts-codex-app --importar-tras-codex
```

El proyecto local de Codex por curso se crea en:

```text
C:\temp\vscodec\cursos\<course_id>\codex_project
```

Incluye contexto didáctico, actividades y unidades, pero no entregas ni datos personales.

### Uso Con API

Corregir prompts preparados con OpenAI API:

```powershell
python corrector_agente.py --pendientes C:\temp\vscodec\cursos\<course_id>\pendientes --temporal C:\temp\vscodec\cursos\<course_id>\temporal --corregir-prompts-openai
```

### Entregas Locales

Preparar prompts desde una carpeta local de pendientes:

```powershell
python corrector_agente.py --preparar-prompts-codex
```

Forzar actividad:

```powershell
python corrector_agente.py --preparar-prompts-codex --actividad-codigo ud02cp03
```

### Extracción y Diagnóstico CARM

Diagnóstico limpio sin HTML ni capturas:

```powershell
python corrector_agente.py --diagnosticar-carm
```

HTML redactado para depurar selectores:

```powershell
python corrector_agente.py --diagnosticar-carm --guardar-evidencias
```

Capturas PNG solo si se piden expresamente:

```powershell
python corrector_agente.py --diagnosticar-carm --guardar-evidencias --guardar-capturas-diagnostico
```

Listar pendientes sin descargar:

```powershell
python corrector_agente.py --solo-listar-carm --unidad ud01
```

Cachear contenido didáctico:

```powershell
python corrector_agente.py --cachear-curso --unidad ud01
```

### Importación y Subida Asistida

Importar JSON de correcciones:

```powershell
python corrector_agente.py --importar-correcciones-codex C:\ruta\correcciones.json
```

Subida asistida desde CSV revisado:

```powershell
python corrector_agente.py --subir-correcciones-carm C:\temp\vscodec\cursos\<course_id>\temporal\revision_pendiente.csv --subida-asistida-carm
```

La subida asistida rellena nota y feedback, pero el guardado en CARM lo hace el docente. Las filas confirmadas se eliminan del CSV.

### Salidas

En la carpeta temporal activa:

```text
C:\temp\vscodec\cursos\<course_id>\temporal
```

- `<alumno>\<actividad>.ext`: copia de la entrega.
- `<alumno>\<actividad>.txt`: corrección generada.
- `resumen.txt`: resumen global.
- `resumen_<actividad>.txt`: resumen por actividad.
- `revision_pendiente.csv`: hoja para revisar antes de publicar.

Todo queda en estado de borrador hasta que el docente lo revise.

### Próximos Pasos

- Mantener `docs/VALIDACION_RELEASE_0.3.0-local.md` actualizado si se regenera el instalador.
- Repetir validación en otro perfil o equipo Windows limpio antes de recomendarlo fuera del entorno de desarrollo.
- Seguir endureciendo pruebas para importación, prompts duplicados, subida asistida y desinstalación.
- Mejorar OCR y conversión de entregas difíciles con casos reales anonimizados o de prueba.
