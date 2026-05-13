# Cierre de app local antes de Fase 5

Este documento marca la puerta de entrada a Fase 5. No se debe avanzar a cloud, servidor, multiusuario ni despliegue pesado hasta cerrar o aceptar conscientemente estos puntos.

## Estado objetivo

La app local debe poder usarse en Windows por un docente con:

- instalacion guiada;
- arranque y reparacion claros;
- verificacion local verde;
- flujo CARM probado;
- revision humana antes de subir notas;
- datos sensibles fuera de Git;
- documentacion suficiente para operar sin tocar codigo.

## Checklist obligatoria

### Instalacion y arranque

- [x] `instalar_windows.cmd` instala `.venv`, dependencias y Chromium.
- [x] `iniciar_app_windows.cmd` arranca la app con comprobacion rapida.
- [x] `reparar_dependencias_windows.cmd` repara dependencias, Chromium y lock de Playwright.
- [x] `verificar_app_windows.cmd` valida equipo, endpoints y prueba offline.
- [x] `SOLUCION_PROBLEMAS_WINDOWS.md` cubre incidencias comunes.

### Seguridad local

- [x] `.env`, logs, caches, respuestas y correcciones generadas quedan fuera de Git.
- [x] La interfaz local escucha en `127.0.0.1`.
- [x] Endpoints `/api/*` requieren token local.
- [x] Publicacion automatica no es flujo normal.
- [x] Subida a CARM mantiene guardado humano.
- [x] Revisar una vez mas `SEGURIDAD_ASVS.md` antes de la siguiente sesion real.

### Flujo CARM real

- [ ] Ejecutar deteccion de cursos en CARM real.
- [x] Probar por codigo que el selector de curso activo recalcula rutas y no reutiliza cursos de otra cuenta.
- [ ] Probar carpetas por curso con al menos dos cursos reales si el docente los tiene.
- [ ] Confirmar que unidades/casos visibles son solo los existentes en CARM.
- [ ] Confirmar obligatorios antes que opcionales.
- [ ] Preparar prompts de una actividad pequena.
- [ ] Corregir con API o Codex sin duplicar prompts ni pendientes.
- [ ] Importar correcciones a `revision_pendiente.csv`.
- [ ] Previsualizar subida asistida sin guardar nada.
- [ ] Subir una actividad real solo tras revision humana.
- [ ] Confirmar en CARM real que "Ya he guardado" detecta el guardado; si Moodle no lo expone, usar "Confirmar guardado manual" y verificar que el CSV se limpia.

### Calidad de correcciones

- [ ] Revisar que prompts no incluyen mapas/ruido de Moodle.
- [x] Comprobar que varios prompts de distintas unidades importan bien al CSV mediante verificacion offline.
- [ ] Comprobar que reenvios de alumnos sustituyen nota/feedback anterior en previsualizacion.
- [ ] Confirmar que entregas sin archivo quedan como incidencia y no se inventa correccion.
- [ ] Confirmar que al completar el ultimo alumno la subida asistida termina y actualiza `revision_pendiente.csv` sin tener que cerrar la pestana manualmente.

### Documentacion y release

- [x] `VERSION` existe y se muestra en interfaz/verificador.
- [x] `RELEASE_CHECKLIST.md` existe.
- [x] `preparar_release_windows.cmd` genera manifiesto.
- [x] Etiqueta local `v0.3.0-local` creada.
- [ ] Limpiar o archivar notas historicas con codificacion rota si molestan al mantenimiento.
- [ ] Ejecutar `preparar_release_windows.cmd` completo tras cerrar esta checklist.

## Criterio para abrir Fase 5

Solo abrir Fase 5 si se cumple una de estas condiciones:

- la app local ya corrige y sube asistidamente con estabilidad suficiente;
- se necesita usarla por varios docentes o en varios equipos de forma coordinada;
- hay requisito institucional de despliegue, auditoria centralizada o multiusuario;
- la instalacion manual en Windows ya no es suficiente.

Mientras no ocurra eso, todo esfuerzo debe seguir centrado en robustecer la app local.
