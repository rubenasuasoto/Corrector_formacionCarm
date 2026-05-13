# Roadmap de descarga segura y despliegue por fases

Este documento aterriza el material de despliegue seguro al estado real del Corrector CARM. No se aplicara todo a la vez: la prioridad es terminar una app local util, con una interfaz de descarga clara y controles suficientes para no poner en riesgo credenciales, entregas ni notas.

## Decision actual

Actualizacion 2026-05-12: la app ya ha avanzado hacia un flujo mas directo de autoprompteo y subida asistida. La interfaz de descarga clasica sigue siendo una referencia de seguridad y usabilidad, pero no bloquea el flujo actual si la app ya detecta, descarga y genera prompts de forma comprensible para el docente.

La siguiente fase del proyecto es completar la interfaz y logica de descarga desde CARM. Antes de invertir en Docker, Kubernetes, Terraform, CI/CD avanzada o despliegue cloud, conviene cerrar bien el flujo local:

1. Detectar curso, unidades y casos reales desde CARM.
2. Listar solo actividades existentes, obligatorias primero y opcionales despues.
3. Previsualizar que entregas se van a descargar.
4. Descargar en carpetas configurables y creadas automaticamente.
5. Registrar incidencias sin exponer credenciales ni datos sensibles de mas.
6. Generar prompts y correcciones sin reabrir Playwright innecesariamente.
7. Publicar solo tras revision humana.

## Fase 0: Base antes de la descarga

Objetivo: que la app sepa donde esta, que curso corrige y si tiene permisos para usar navegador.

- Mantener escucha solo en `127.0.0.1`.
- Crear carpetas de trabajo si no existen.
- Permitir elegir carpetas desde explorador de archivos.
- Detectar curso CARM y refrescar cache al iniciar o cada intervalo configurado.
- Reintentar escaneo cuando se resuelvan permisos de Windows/Chromium.
- No mostrar unidades/casos que no existan en CARM.
- Separar cache didactica de datos personales siempre que sea posible.

Estado: implementado en primera version; pendiente de pruebas reales repetidas con varios cursos y permisos Windows/Chromium.

## Fase 1: Interfaz de descarga CARM

Objetivo: que una persona pueda descargar sin conocer comandos.

- Nueva seccion "Descargas CARM" en el panel.
- Selector de curso detectado.
- Selector de unidad y actividad con etiquetas `obligatorio`/`opcional`.
- Opcion "Todos los pendientes" para generar lotes completos cuando convenga.
- Boton "Actualizar desde CARM".
- Boton "Listar entregas" antes de descargar.
- Tabla de previsualizacion con:
  - unidad
  - caso practico
  - tipo
  - alumno
  - estado
  - archivo detectado o incidencia
- Boton "Descargar seleccionadas".
- Resumen claro de archivos descargados, omitidos y casos sin envio.

Estado: parcialmente absorbida por el flujo de autoprompteo. Sigue pendiente si se quiere una tabla de descarga manual mas detallada, pero no debe duplicar el flujo principal ni obligar a reabrir Playwright para pasos separados.

## Fase 1.5: Multi-curso sin pisarse

Objetivo: permitir que un docente seleccione uno o varios cursos CARM y que la app prepare prompts por curso sin mezclar cache, entregas, CSV ni subidas.

Principios:

- No asumir un unico `CARM_COURSE_URL` global como verdad permanente.
- Detectar cursos disponibles desde la pagina CARM del docente siempre que sea posible.
- Dejar que el usuario elija uno o varios cursos desde la interfaz.
- Mostrar un selector de curso activo arriba a la derecha para cambiar la vista entre cursos.
- Separar datos locales por curso antes de activar autoprompteo multi-curso.
- Procesar varios cursos de forma secuencial y con logs claros, nunca en paralelo al principio.

Estructura local objetivo:

```text
C:\temp\vscodec\cursos\<course_id>\
  pendientes\
  pendientes\prompts_codex\
  temporal\
  temporal\revision_pendiente.csv
  archivados\
```

Cache:

- `cache_carm\curso_<course_id>.sqlite` sigue siendo cache didactica por curso.
- La cache no guarda entregas ni CSV.
- La interfaz debe mostrar si cada curso tiene cache didactica, unidades y casos detectados.

Autoprompteo multi-curso:

1. Leer lista de cursos seleccionados.
2. Para cada curso, cargar su URL y sus rutas propias.
3. Revisar CARM con filtro `Requiere calificacion`.
4. Generar prompts en la carpeta de ese curso.
5. Notificar resumen: curso, actividades y numero de prompts.
6. No llamar a API automaticamente.

Subida:

- El curso activo en la interfaz determina que `revision_pendiente.csv` se muestra y se sube.
- El boton de subida debe mostrar curso + actividad + numero de filas pendientes.
- No se debe permitir subir un CSV de un curso mientras la interfaz muestra otro curso.

Implementacion por pasos:

1. Detectar y listar cursos disponibles desde CARM, sin cambiar todavia las rutas. Estado: implementado como primera version con `--listar-cursos-carm` y `respuestas_extraidas/cursos_detectados.json`.
2. Guardar seleccion de cursos en `.corrector_app.json`. Estado: implementado desde la configuracion de la interfaz.
3. Mostrar selector de curso activo en la cabecera. Estado: implementado para cambiar el curso visible desde la interfaz.
4. Separar cache/opciones visibles por curso.
5. Migrar rutas de trabajo a `cursos/<course_id>/`. Estado: implementado como opcion activable "Separar carpetas por curso"; por defecto se mantienen las rutas globales para no romper instalaciones existentes.
6. Activar autoprompteo secuencial para cursos seleccionados. Estado: primera version implementada; solo se activa de forma segura cuando hay varios cursos seleccionados y carpetas por curso activadas.
7. Hacer que el arranque sin curso activo detecte cursos desde el area personal. Estado: implementado.
8. Mostrar estado por curso en la interfaz. Estado: implementado con cache, fecha de cache, prompts, JSON, filas CSV, actividades e incidencias bloqueantes.
9. Filtrar enlaces auxiliares detectados como cursos. Estado: implementado para `FAQS` y `CARM - Curso CARM`.
10. Evitar que el refresco automatico de la interfaz pise cambios no guardados en la configuracion de cursos. Estado: implementado.

Esta fase debe hacerse con cambios pequenos y verificables. La primera cola multi-curso y el resumen por curso ya existen, pero falta prueba real con varios cursos CARM antes de considerarlo terminado. Tambien se debe verificar que cambiar curso recalcula rutas y que ningun CSV de un curso se muestra como si perteneciera a otro.

## Fase 2: Seguridad operativa local

Objetivo: controles sencillos con impacto real.

- Auditoria local en JSONL para acciones sensibles:
  - iniciar sesion
  - refrescar cache
  - listar entregas
  - descargar
  - generar prompts
  - importar correcciones
  - previsualizar subida
  - publicar en CARM
- Redaccion de logs para evitar credenciales, cookies, tokens, emails y HTML sensible.
- Confirmacion fuerte antes de publicar en CARM.
- Bloqueo de publicacion si hay incidencias o revision manual pendiente.
- Limpieza configurable de logs y datos personales antiguos.
- Sanitizado de feedback antes de insertarlo en Moodle/CARM.

## Fase 3: Calidad y despliegue ligero

Objetivo: que cada version local sea reproducible sin montar infraestructura grande.

- Checklist de release local.
- Chequeo local desde interfaz para dependencias, Chromium, carpetas, credenciales, curso activo y artefactos sensibles en Git. Estado: implementado.
- Comando unico de verificacion:
  - compilacion Python
  - pruebas offline
  - validacion de configuracion
  - comprobacion de endpoints locales
- Estado: implementado como `verificar_app.py` y lanzadores `verificar_app_windows.cmd` / `verificar_app_windows.ps1`.
- Versionado semantico sencillo. Estado: implementado con `VERSION`, cabecera de interfaz y salida de `verificar_app.py`.
- Etiquetas Git para versiones que funcionen. Estado: flujo preparado con `preparar_release.py`; creada etiqueta local `v0.3.0-local` tras verificacion correcta.
- Documentar cambios relevantes en `ESTADO_PROYECTO.md`.
- Mantener `.env.example` actualizado sin secretos. Estado: actualizado con variables CARM, OpenAI, Codex, retencion y limites de tokens.

Esta fase aplica las ideas de Git, build reproducible y pruebas del documento, pero en escala local.

## Fase 4: Instalacion de la app

Objetivo: facilitar uso en Windows sin depender de conocimientos tecnicos.

- Script de instalacion guiado.
- Comprobacion de Python, dependencias y Playwright. Estado: instalador valida Python 3.12+, revisa codigos de salida, instala dependencias y ejecuta `verificar_app.py --instalacion --sin-prueba-offline`.
- Instalacion de Chromium para Playwright. Estado: implementado; si Chromium ya existe, no lo reinstala para evitar locks de Windows.
- Acceso directo de escritorio o menu inicio. Estado: acceso directo opcional con `-CrearAccesoDirecto`.
- Arranque opcional del panel local. Estado: implementado; inicio manual usa `iniciar_app_windows.ps1` con comprobacion rapida y opciones `-AbrirNavegador`, `-AutoPreparar`, `-SinEscaneoInicial`.
- Reparacion de dependencias. Estado: `reparar_dependencias_windows.cmd` usa flujo propio, puede reinstalar dependencias, reinstalar Chromium y limpiar `ms-playwright\__dirlock`.
- Mensajes claros cuando Windows bloquee permisos. Estado: implementado en primera version con chequeo de lock Playwright, reparador dedicado y `SOLUCION_PROBLEMAS_WINDOWS.md`.

PyInstaller o instalador completo pueden esperar hasta que el flujo de descarga/publicacion sea estable.

Estado: fase local implementada en primera version. Antes de abrir Fase 5 hay que cerrar la puerta `CIERRE_APP_LOCAL.md`, centrada en pruebas CARM reales, calidad de correcciones y revision humana.

## Puerta antes de Fase 5: terminar app local

Objetivo: no saltar a infraestructura futura antes de que la herramienta local sea estable.

- Ejecutar `verificar_app_windows.cmd` en verde.
- Ejecutar prueba CARM real de deteccion, prompts, importacion CSV y previsualizacion.
- Probar cambio de curso y carpetas por curso si hay varios cursos reales.
- Confirmar que la subida asistida mantiene guardado humano.
- Confirmar que no se duplican prompts, pendientes ni CSV al repetir ejecuciones.
- Revisar `CIERRE_APP_LOCAL.md` y aceptar explicitamente cualquier punto pendiente.

Estado: abierto. Es el punto actual del proyecto.

## Fase 5: Pospuesto de forma consciente

Estas practicas del documento son valiosas, pero no rentan antes de terminar la app local:

- Docker de produccion.
- Kubernetes.
- Terraform/Ansible.
- GitOps con ArgoCD.
- Blue/green, canary y rolling deploy.
- Chaos engineering.
- SAST/DAST pesado.
- Registro centralizado de artefactos.
- Despliegue cloud.

Se reabriran si la app deja de ser una herramienta local y pasa a ejecutarse en servidor, multiusuario o con varios docentes.

## Criterio de prioridad

Una mejora sube de prioridad si protege:

- credenciales CARM
- sesion recordada
- entregas de alumnos
- nombres, emails, notas y feedback
- integridad de las publicaciones en CARM
- estabilidad del flujo de descarga/correccion/subida

Una mejora baja de prioridad si solo sirve para infraestructura futura y no desbloquea la interfaz actual.
