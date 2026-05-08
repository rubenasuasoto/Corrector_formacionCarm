# Roadmap de descarga segura y despliegue por fases

Este documento aterriza el material de despliegue seguro al estado real del Corrector CARM. No se aplicara todo a la vez: la prioridad es terminar una app local util, con una interfaz de descarga clara y controles suficientes para no poner en riesgo credenciales, entregas ni notas.

## Decision actual

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

Estado: en marcha.

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

Esta fase es prioritaria porque reduce errores humanos y evita relanzar Playwright para pasos separados.

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
- Comando unico de verificacion:
  - compilacion Python
  - pruebas offline
  - validacion de configuracion
  - comprobacion de endpoints locales
- Versionado semantico sencillo.
- Etiquetas Git para versiones que funcionen.
- Documentar cambios relevantes en `ESTADO_PROYECTO.md`.
- Mantener `.env.example` actualizado sin secretos.

Esta fase aplica las ideas de Git, build reproducible y pruebas del documento, pero en escala local.

## Fase 4: Instalacion de la app

Objetivo: facilitar uso en Windows sin depender de conocimientos tecnicos.

- Script de instalacion guiado.
- Comprobacion de Python, dependencias y Playwright.
- Instalacion de Chromium para Playwright.
- Acceso directo de escritorio o menu inicio.
- Arranque opcional del panel local.
- Mensajes claros cuando Windows bloquee permisos.

PyInstaller o instalador completo pueden esperar hasta que el flujo de descarga/publicacion sea estable.

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
