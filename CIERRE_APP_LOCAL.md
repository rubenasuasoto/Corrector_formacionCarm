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

## Estado 2026-05-14

La puerta pre-Fase 5 esta muy avanzada. Ya hay instalacion guiada, paquete ZIP local, carpetas por curso por defecto, cache didactica con resumenes por unidad y verificacion anti-mojibake. La prueba multi-curso real queda confirmada; antes de entrar en Fase 5 toca regenerar release/paquete con los ultimos cambios visuales y de verificacion.

Actualizacion 2026-05-15: el docente confirma que multi-curso funciona. Tambien queda corregido un bloqueo del panel local por JavaScript embebido roto y `verificar_app.py` ya comprueba ese caso. El icono propio de la app se valida como asset de release.

Prueba instalacion limpia 2026-05-15: el ZIP guiado se extrajo en una carpeta temporal, no contenia `.env`, `.venv`, logs, cache ni salidas generadas. El instalador creo entorno virtual, instalo dependencias base, creo `.env` desde plantilla y la verificacion de instalacion paso correctamente.

Decision DevOps 2026-05-15: el flujo de despliegue seguro se aplica como app local Windows. Docker, Compose y despliegue cloud quedan fuera de esta puerta y solo se abriran en Fase 5 si hay servidor, multiusuario o requisito institucional. Antes de eso, el siguiente paso de despliegue es `.exe` local con identidad propia de Windows.

Actualizacion 2026-05-15: se anade `crear_launcher_windows.cmd` / `.ps1` para generar `Corrector CARM.exe`, un lanzador local con icono propio que abre el panel usando el arranque existente. No empaqueta `.env`, cache, entregas ni credenciales; mantiene el instalador actual para preparar `.venv`, dependencias y Chromium.

Actualizacion instalador 2026-05-15: `INSTALAR_CORRECTOR_CARM.cmd` pasa a abrir un asistente visual. El asistente permite elegir carpeta de instalacion, carpeta de datos/descargas, accesos directos, inicio con Windows activado por defecto y apertura al finalizar. Despues copia la app a la ubicacion elegida y ejecuta el instalador tecnico.

Revision 2026-05-18: la puerta pre-Fase 5 sigue siendo local. El instalador y paquete ya apuntan a distribucion de usuario final: lista blanca de archivos, `LEEME_INSTALACION.txt`, desinstalador registrado y preparacion opcional de Codex CLI oficial. La verificacion local vuelve a pasar en verde; queda pendiente regenerar el ZIP final tras el ajuste de PATH de Node/Codex.

Actualizacion 2026-05-18: el instalador guiado reutiliza carpetas existentes y conserva configuracion compatible al reinstalar. El desinstalador permite elegir entre conservar datos, borrar todo o borrar solo pendientes, temporal o cursos/cache/proyectos Codex.

Actualizacion instalador 2026-05-18: la ventana guiada muestra icono propio, comprobacion previa de Python, dependencias que se prepararan, OCR opcional, carpetas existentes y estado de Node.js/npm/Codex. Tambien avisa claramente que el modo sin API necesita iniciar sesion con ChatGPT mediante `codex login`.

Actualizacion Codex 2026-05-18: el proyecto local por curso deja de ser solo un resumen. Mantiene `contexto_didactico.md` como indice, pero anade `unidades/*.md` con el contenido imprimible completo de cada unidad y sanea mojibake heredado de cache. La API sigue usando prompts recortados/optimizados para controlar coste; Codex puede apoyarse en el workspace del curso para consultar mas contexto sin subir entregas ni datos personales.

Actualizacion prompts 2026-05-18: las entregas legibles con señales de extraccion dudosa incorporan `calidad_extraccion` dentro del prompt. Codex debe revisar el archivo original si puede antes de penalizar por texto incompleto, caracteres raros u OCR, y no debe trasladar problemas tecnicos de extraccion al feedback del alumno salvo que se vean tambien en el archivo real.

Actualizacion revision manual 2026-05-18: el panel incorpora una bandeja para casos que deben apartarse antes de subir. Desde ahi se puede guardar una nota para Codex, marcar el caso como `revision_manual_necesaria` y generar un prompt de recorreccion sin entrar en CARM. Esos casos bloquean la subida asistida hasta que se resuelvan.

Revision profunda 2026-05-18: se comprueba el estado completo tras los cambios de instalador, OCR, interfaz y Codex. Pasan parseo PowerShell de scripts Windows, compilacion Python y `verificar_app.py --instalacion --sin-endpoints`. La configuracion queda organizada por secciones y la preferencia de tema se guarda en `.corrector_app.json`. El instalador/desinstalador ya no deben mostrar terminales al usuario final; la fase tecnica se ve como checklist/progreso dentro del asistente. No se regenera paquete ni `Setup.exe` en esta revision.

Actualizacion arranque 2026-05-25: el uso normal de la app tambien queda desacoplado de una consola visible. `Corrector CARM.exe` lanza directamente `pythonw.exe interfaz_app.py` en segundo plano y el inicio con Windows usa `Corrector CARM.vbs` oculto en vez del `.cmd` anterior. El `.cmd` queda como fallback para compatibilidad, pero los accesos directos deben apuntar al `.exe`.

## Checklist obligatoria

### Instalacion y arranque

- [x] `instalar_windows.cmd` instala `.venv`, dependencias y Chromium.
- [x] `INSTALAR_CORRECTOR_CARM.cmd` ofrece una entrada guiada para usuarios no tecnicos.
- [x] El instalador guiado copia la app a una carpeta de instalacion elegida y crea una carpeta de datos configurable.
- [x] Reinstalar sobre carpetas existentes actualiza app sin borrar `.env` ni datos locales.
- [x] `ABRIR_CORRECTOR_CARM.cmd` abre el panel sin obligar a elegir scripts internos.
- [x] `Corrector CARM.exe` puede generarse como lanzador visual de Windows encima del arranque actual.
- [x] `crear_paquete_windows.cmd` genera un ZIP guiado para otro Windows sin secretos ni artefactos generados.
- [x] `crear_instalador_setup_windows.cmd` genera un `Setup.exe` autoextraible que lanza el instalador guiado sin pedir descomprimir carpetas.
- [x] El desinstalador permite conservar datos, borrar todo o borrar solo partes concretas.
- [x] El instalador guiado detecta dependencias/carpetas y avisa de la necesidad de iniciar sesion en Codex.
- [x] El instalador guiado ofrece preparar integracion con Codex App sin API sin instalarlo automaticamente.
- [x] El instalador guiado oculta procesos tecnicos y muestra checklist/progreso integrado sin terminales visibles.
- [x] El instalador OCR no bloquea la instalacion si Tesseract o el idioma espanol no pueden instalarse.
- [x] La integracion sin API usa el Codex CLI oficial instalado con npm (`codex.cmd`) y bloquea el ejecutable de la extension de VS Code.
- [x] El flujo Codex comprueba version/login, reintenta fallos temporales y tolera archivos bloqueados en `codex_project` si Codex Desktop ya lo tiene abierto.
- [x] El proyecto Codex por curso exporta indice, actividades y contenido imprimible completo por unidad, separado de los prompts/API.
- [x] Los prompts avisan a Codex de posibles fallos de extraccion para que verifique el original y no culpe al alumno sin comprobar.
- [x] La interfaz permite apartar casos a revision manual y crear prompts de recorreccion para Codex.
- [x] La configuracion de la interfaz esta dividida por secciones y guarda tema automatico/claro/oscuro.
- [x] `iniciar_app_windows.cmd` arranca la app con comprobacion rapida.
- [x] `reparar_dependencias_windows.cmd` repara dependencias, Chromium y lock de Playwright.
- [x] `verificar_app_windows.cmd` valida equipo, endpoints y prueba offline.
- [x] `SOLUCION_PROBLEMAS_WINDOWS.md` cubre incidencias comunes.
- [x] La interfaz permite preparar un proyecto local de Codex por curso y marcar que se abra con Windows junto al Corrector.

### Seguridad local

- [x] `.env`, logs, caches, respuestas y correcciones generadas quedan fuera de Git.
- [x] La interfaz local escucha en `127.0.0.1`.
- [x] Endpoints `/api/*` requieren token local.
- [x] Publicacion automatica no es flujo normal.
- [x] Subida a CARM mantiene guardado humano.
- [x] Revisar una vez mas `SEGURIDAD_ASVS.md` antes de la siguiente sesion real.

### Flujo CARM real

- [x] Ejecutar deteccion de cursos en CARM real.
- [x] Probar por codigo que el selector de curso activo recalcula rutas y no reutiliza cursos de otra cuenta.
- [x] Probar carpetas por curso con al menos dos cursos reales si el docente los tiene.
- [x] Confirmar que unidades/casos visibles son solo los existentes en CARM.
- [x] Confirmar obligatorios antes que opcionales.
- [x] Preparar prompts de una actividad pequena.
- [x] Corregir con API o Codex sin duplicar prompts ni pendientes.
- [x] Importar correcciones a `revision_pendiente.csv`.
- [x] Previsualizar subida asistida sin guardar nada.
- [x] Subir una actividad real solo tras revision humana.
- [x] Confirmar en CARM real que "Ya he guardado" detecta el guardado; si Moodle no lo expone, usar "Confirmar guardado manual" y verificar que el CSV se limpia.

### Calidad de correcciones

- [x] Revisar que prompts no incluyen mapas/ruido de Moodle.
- [x] Comprobar que varios prompts de distintas unidades importan bien al CSV mediante verificacion offline.
- [x] Comprobar que reenvios de alumnos sustituyen nota/feedback anterior en previsualizacion.
- [x] Confirmar que entregas sin archivo quedan como incidencia y no se inventa correccion.
- [x] Confirmar que al completar el ultimo alumno la subida asistida termina y actualiza `revision_pendiente.csv` sin tener que cerrar la pestana manualmente.

### Documentacion y release

- [x] `VERSION` existe y se muestra en interfaz/verificador.
- [x] `RELEASE_CHECKLIST.md` existe.
- [x] Roadmap y arquitectura reflejan el flujo DevOps local y posponen Docker a Fase 5.
- [x] `preparar_release_windows.cmd` genera manifiesto.
- [x] Etiqueta local `v0.3.0-local` creada.
- [x] Verificacion anti-mojibake incorporada a `verificar_app.py`.
- [x] Verificacion de JavaScript embebido incorporada a `verificar_app.py`.
- [x] Verificacion de iconos propios incorporada a `verificar_app.py`.
- [x] Limpiar o archivar notas historicas con codificacion rota si molestan al mantenimiento.
- [x] Ejecutar `preparar_release_windows.cmd` completo tras los cambios de 2026-05-14.
- [x] Ejecutar `preparar_release_windows.cmd` y `crear_paquete_windows.cmd` tras los cambios de icono/verificacion de 2026-05-15.
- [ ] Regenerar paquete ZIP final y `Setup.exe` cuando se quiera distribuir los cambios de instalador sin terminal, OCR robusto, tema y configuracion por secciones.

## Criterio para abrir Fase 5

Solo abrir Fase 5 si se cumple una de estas condiciones:

- la app local ya corrige y sube asistidamente con estabilidad suficiente;
- se necesita usarla por varios docentes o en varios equipos de forma coordinada;
- hay requisito institucional de despliegue, auditoria centralizada o multiusuario;
- la instalacion manual en Windows ya no es suficiente.

Mientras no ocurra eso, todo esfuerzo debe seguir centrado en robustecer la app local.
