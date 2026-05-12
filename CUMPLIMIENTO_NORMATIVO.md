# Cumplimiento normativo y estandares aplicables

Este documento no sustituye asesoramiento legal ni la politica del centro/administracion. Sirve como guia tecnica para que el Corrector CARM avance de forma compatible con normativa europea y espanola, sin sobredimensionar una app local.

## Alcance de la app

El Corrector CARM es una herramienta local en Windows, escuchando en `127.0.0.1`, que ayuda a:

- acceder a CARM/Moodle con credenciales del docente;
- detectar entregas que requieren calificacion;
- descargar archivos de alumnos;
- generar prompts y correcciones revisables;
- preparar subida asistida y, solo con guardado humano confirmado, registrar nota y feedback en CARM.

Datos tratados:

- identificadores de alumnos;
- entregas y archivos adjuntos;
- notas;
- retroalimentacion;
- credenciales y sesion CARM;
- cache didactica del curso;
- logs y auditoria local.

## Normativa y referencias principales

- RGPD, Reglamento (UE) 2016/679: proteccion de datos personales, privacidad desde el diseno, minimizacion, seguridad, limitacion de conservacion y responsabilidad proactiva.
- LOPDGDD, Ley Organica 3/2018: adaptacion espanola del RGPD y garantia de derechos digitales.
- ENS, Real Decreto 311/2022: referencia espanola para seguridad en sistemas vinculados al sector publico, especialmente principios de gestion de riesgos, minimo privilegio, trazabilidad, continuidad y mejora continua.
- Reglamento (UE) 2024/1689 de IA: relevante por el uso de IA en contexto educativo. La app debe conservar revision humana y no tomar decisiones academicas finales sin validacion.
- Guias AEPD sobre gestion de riesgos, evaluacion de impacto y auditoria de tratamientos con IA: referencia practica para transparencia, control humano, calidad, auditoria y proporcionalidad.
- OWASP ASVS: usado de forma adaptada en `SEGURIDAD_ASVS.md`.
- CVSS v4.0: usado para priorizar riesgos en `SEGURIDAD_CVSS.md`.

Fuentes oficiales consultadas:

- RGPD: https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:32016R0679
- LOPDGDD: https://www.boe.es/buscar/act.php?id=BOE-A-2018-16673
- ENS: https://www.boe.es/buscar/act.php?id=BOE-A-2022-7191
- Reglamento (UE) 2024/1689 de IA: https://eur-lex.europa.eu/eli/reg/2024/1689/oj
- AEPD, innovacion y tecnologia: https://www.aepd.es/areas-de-actuacion/innovacion-y-tecnologia
- AEPD, auditorias de tratamientos con IA: https://www.aepd.es/guias/requisitos-auditorias-tratamientos-incluyan-ia.pdf

## Principios que se aplican al proyecto

### Minimizacion

- La cache del curso debe guardar recursos estables: unidades, actividades, enunciados, rubricas y contenido imprimible.
- La cache didactica no debe guardar entregas, emails, cookies ni tablas completas de alumnos.
- La interfaz debe mostrar solo unidades y casos detectados realmente en CARM.
- Los diagnósticos deben generarse redactados por defecto.

### Limitacion de finalidad

- Los datos se usan solo para correccion, revision y publicacion en CARM.
- No se reutilizan entregas de alumnos para entrenar modelos.
- No se envia automaticamente nada a terceros salvo que el usuario ejecute conscientemente Codex, una IA externa o la accion `Corregir prompts con API`.

### Revision humana

- La IA no publica por si sola.
- La publicacion se bloquea si hay errores o revision manual pendiente.
- El docente debe revisar `revision_pendiente.csv`, JSON o resumenes antes de subir.
- El modo de subida asistida rellena campos, pero espera a que el docente pulse guardar en CARM y comprueba que el guardado se haya producido antes de avanzar.
- La app avisa cuando detecta correcciones preparadas que aun no constan como publicadas.

### Seguridad y confidencialidad

- `.env`, caches, logs y salidas sensibles estan fuera de git.
- La interfaz local usa token anti-CSRF para endpoints.
- El servidor escucha en `127.0.0.1`.
- Los endpoints aceptan acciones cerradas, no comandos arbitrarios.
- El feedback se sanitiza antes de insertarlo en CARM.
- Los logs y auditoria aplican redaccion basica de secretos, emails, tokens y cookies.

### Trazabilidad

- Las acciones sensibles quedan registradas en `respuestas_extraidas/auditoria.jsonl`.
- La auditoria usa referencias seudonimizadas para alumnos/usuarios cuando procede.
- Se registran acciones como configurar curso, guardar credenciales, listar/descargar/preparar, importar, subir de forma asistida y purgar.

### Conservacion y purga

- La cache didactica se puede borrar con `--borrar-cache-curso`.
- Si `CARM_COURSE_END_DATE=YYYY-MM-DD` y la fecha ya paso, la cache didactica se purga al iniciar.
- Los logs antiguos y auditoria antigua tienen retencion configurable:
  - `LOG_RETENTION_DAYS` por defecto 90.
  - `AUDIT_RETENTION_DAYS` por defecto 365.
- Los datos personales locales se purgan manualmente con:

```powershell
.\.venv\Scripts\python.exe corrector_agente.py --purgar-datos-personales-locales --confirmar-purga-datos
```

Esta purga es manual para evitar perdidas accidentales antes de cerrar una evaluacion.

## Controles implementados

- Token local obligatorio en endpoints `/api/*`.
- Recuperacion de token caducado en la interfaz.
- Fallback de puerto local si `8765` esta ocupado.
- Separacion entre arranque automatico de la app y autoprompteo al inicio: el autoprompteo requiere configuracion explicita.
- Auditoria local JSONL.
- Redaccion basica de logs y eventos.
- Sanitizado de feedback.
- Bloqueo de publicacion con incidencias.
- Autoprompteo al inicio sin gasto automatico de API.
- Archivado de prompts, correcciones y resumenes usados para evitar duplicidades.
- Purga manual fuerte de salidas con datos personales.
- Retencion automatica de logs/auditoria antiguos.

## Pendientes por fase

### Antes de distribuir a otros usuarios

- Confirmar con `git ls-files` que `.env`, logs, caches, salidas y correcciones generadas no estan versionados.
- Revisar con el Delegado de Proteccion de Datos o responsable del centro.
- Definir base juridica y rol: responsable/encargado, uso personal docente o herramienta institucional.
- Decidir si se requiere Evaluacion de Impacto de Proteccion de Datos.
- Documentar informacion al usuario/docente: que datos se tratan, donde se guardan y como se purgan.
- Valorar cifrado/DPAPI para credenciales locales.

### Antes de uso institucional amplio

- Politica de retencion aprobada.
- Procedimiento de incidentes.
- Registro de actividades de tratamiento.
- Pruebas de seguridad de endpoints locales.
- Revision de proveedores de IA/CLI usados.
- Control de versiones y checklist de release.

### Si pasa a servidor o multiusuario

- Autenticacion propia.
- Control de acceso por usuario.
- Separacion estricta de datos por curso/docente.
- ENS con categoria y medidas formales.
- Auditoria y monitorizacion centralizada.
- Evaluacion formal del sistema de IA segun el Reglamento (UE) 2024/1689.
