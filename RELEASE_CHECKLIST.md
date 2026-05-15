# Checklist de release local

Este checklist se usa antes de compartir una version, reinstalar en otro equipo o hacer una sesion real de correccion con impacto en alumnos.

## 1. Higiene del repositorio

- [ ] `VERSION` refleja la version local que se va a usar o compartir.
- [ ] `git status` no contiene cambios inesperados.
- [ ] `.env`, logs, caches, salidas, entregas y correcciones generadas no aparecen en `git ls-files`.
- [ ] `.env.example` esta actualizado, no contiene secretos reales y cubre variables nuevas.
- [ ] `ESTADO_PROYECTO.md`, `ROADMAP_DESCARGA_SEGURA.md` y `ARQUITECTURA_PROYECTO.md` reflejan el estado real.
- [ ] `assets/corrector_carm.ico` y `assets/corrector_carm.png` estan incluidos para panel, bandeja, accesos directos y paquete Windows.

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
- credenciales CARM, curso activo y carpetas de trabajo.

Para una instalacion nueva sin credenciales:

```powershell
.\verificar_app_windows.cmd --instalacion
```

Para preparar un release local y guardar manifiesto:

```powershell
.\preparar_release_windows.cmd
```

Para crear etiqueta Git despues de hacer commit y tener el arbol limpio:

```powershell
.\preparar_release_windows.cmd --crear-tag
```

## 3. Seguridad operativa

- [ ] La interfaz escucha solo en `127.0.0.1`.
- [ ] El panel exige token local para `/api/*`.
- [ ] El arranque de Windows y el autoprompteo estan configurados de forma explicita.
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
