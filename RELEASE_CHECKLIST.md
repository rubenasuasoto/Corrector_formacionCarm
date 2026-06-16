# Checklist de release local

Este checklist se usa antes de compartir una version, reinstalar en otro equipo o hacer una sesion real de correccion con impacto en alumnos.

## 1. Higiene del repositorio

- [ ] `VERSION` refleja la version local que se va a usar o compartir.
- [ ] `git status` no contiene cambios inesperados.
- [ ] El commit que se va a distribuir coincide con las notas de release.
- [ ] `.env`, logs, caches, salidas, entregas y correcciones generadas no aparecen en `git ls-files`.
- [ ] `.env.example` esta actualizado, no contiene secretos reales y cubre variables nuevas.
- [ ] `docs/PUBLICACION.md`, `SECURITY.md` y `CONTRIBUTING.md` estan actualizados si se va a publicar el repositorio.
- [ ] `ESTADO_PROYECTO.md`, `ROADMAP_DESCARGA_SEGURA.md` y `ARQUITECTURA_PROYECTO.md` reflejan el estado real.
- [ ] `docs/VALIDACION_RELEASE_0.3.0-local.md` y las release notes reflejan la ultima validacion completa si se comparte el instalador.
- [ ] `assets/corrector_carm.ico` y `assets/corrector_carm.png` estan incluidos para panel, bandeja, accesos directos y paquete Windows.
- [ ] Si se distribuye como app guiada, `Corrector CARM.exe` se ha regenerado con `tools\windows\crear_launcher_windows.cmd` y no contiene secretos.
- [ ] `INSTALAR_CORRECTOR_CARM.cmd` abre el asistente visual y permite elegir carpeta de instalacion, carpeta de datos, accesos e inicio con Windows.
- [ ] La instalacion registra `Corrector CARM` en Aplicaciones instaladas y `desinstalar_windows.cmd` / `.ps1` estan incluidos en el paquete.
- [ ] Si se comparte con usuarios finales, `tools\windows\crear_instalador_setup_windows.cmd` genera un `Corrector_CARM_*_Setup_*.exe` probado sin ejecutar la instalacion.
- [ ] `docs/PRUEBA_INSTALADOR.md` se ha seguido en una carpeta de laboratorio antes de publicar el EXE.
- [ ] El desinstalador solo borra accesos que apuntan a la carpeta instalada y conserva accesos de otras copias.
- [ ] Reinstalar sobre carpetas existentes conserva `.env` y reutiliza datos compatibles.
- [ ] Desinstalar permite conservar datos o borrar selectivamente pendientes, temporal y cursos/cache/proyectos Codex.
- [ ] La ventana de instalacion muestra comprobacion previa de dependencias, carpetas existentes y estado/login de Codex CLI.
- [ ] La fase tecnica del instalador y el desinstalador no muestran terminales; el usuario ve progreso/checklist dentro de la ventana grafica.
- [ ] OCR/Tesseract se trata como dependencia opcional: si falla, la instalacion continua y las entregas escaneadas quedan en revision manual.
- [ ] El proyecto Codex por curso contiene `contexto_didactico.md`, `actividades.json`, `AGENTS.md` y `unidades/*.md` sin entregas ni datos personales.

## 2. Verificacion tecnica

Ejecutar:

```powershell
.\verificar_app_windows.cmd
```

Debe validar:

- compilacion Python;
- dependencias base;
- Chromium de Playwright;
- dependencias opcionales si se van a leer PDF, PPTX, XLSX u OCR;
- importacion offline de JSON de varias unidades a `revision_pendiente.csv` sin duplicados;
- aislamiento offline de cursos seleccionados cuando cambia la cuenta CARM;
- endpoints locales con token;
- assets del icono servidos por el panel local;
- pruebas offline de importacion y contexto cuenta/curso;
- bloqueo offline de publicacion directa y preparacion de curso completo sin filtro de unidad;
- menu de configuracion por secciones y tema automatico/claro/oscuro;
- preferencias de pantalla: tamaño de letra, altura del registro, alto contraste y ultima seccion abierta;
- horario de autoprompt guardado con formato `HH:MM`;
- credenciales CARM, curso activo y carpetas de trabajo.

Para una instalacion nueva sin credenciales:

```powershell
.\verificar_app_windows.cmd --instalacion
```

Para preparar un release local y guardar manifiesto:

```powershell
.\tools\windows\preparar_release_windows.cmd
```

Para crear etiqueta Git despues de hacer commit y tener el arbol limpio:

```powershell
.\tools\windows\preparar_release_windows.cmd --crear-tag
```

Para el release validado del 15 de junio de 2026, usar como referencia:

```text
docs/VALIDACION_RELEASE_0.3.0-local.md
docs/RELEASE_NOTES_0.3.0-local_20260615.md
docs/GITHUB_RELEASE_0.3.0-local_20260615.md
```

Para regenerar el lanzador local con icono propio:

```powershell
.\tools\windows\crear_launcher_windows.cmd
```

## 3. Seguridad operativa

- [ ] La interfaz escucha solo en `127.0.0.1`.
- [ ] El panel exige token local para `/api/*`.
- [ ] El arranque de Windows y el autoprompteo estan configurados de forma explicita.
- [ ] Si hay varios cursos seleccionados, cada curso tiene carpetas propias en `cursos\<course_id>` y no comparte CSV/prompts con otro curso.
- [ ] La subida a CARM sigue siendo asistida con guardado humano.
- [ ] No hay publicacion automatica como flujo normal.

## 4. Prueba CARM antes de uso real

- [ ] Detectar cursos desde CARM.
- [ ] Seleccionar curso activo correcto.
- [ ] Si hay varios cursos, activar carpetas por curso antes de autopromptear.
- [ ] Cachear curso y comprobar que unidades/casos coinciden con CARM.
- [ ] Generar prompts de una actividad pequeña.
- [ ] Revisar que `revision_pendiente.csv` agrupa alumno, actividad, nota y feedback correctamente.

## 5. Cierre de sesion o fin de curso

- [ ] Archivar prompts/correcciones ya usados.
- [ ] Purgar datos personales locales cuando ya no sean necesarios.
- [ ] Borrar cache didactica al finalizar el curso si procede.
- [ ] Revisar auditoria local si hubo incidencias.

## 6. Puerta pre-Fase 5

- [ ] Revisar `CIERRE_APP_LOCAL.md`.
- [ ] Confirmar que la app local ya cubre el flujo real necesario.
- [ ] Aceptar explicitamente cualquier punto pendiente antes de abrir Fase 5.
