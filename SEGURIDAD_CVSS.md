# Priorizacion CVSS para el Corrector CARM

Referencia de trabajo: CVSS v4.0 User Guide.

CVSS se usara en este proyecto para priorizar fallos de seguridad y decidir que arreglar primero. No sustituye a `SEGURIDAD_ASVS.md`: ASVS define controles y buenas practicas; CVSS ayuda a clasificar la gravedad de hallazgos concretos.

## Como Usarlo Aqui

Para cada hallazgo relevante de seguridad se registrara:

- Descripcion breve.
- Activo afectado: credenciales, sesion CARM, entregas, notas, logs, cache, endpoints locales.
- Vector CVSS v4.0 si merece la pena.
- Severidad estimada: critica, alta, media, baja o informativa.
- Decision: arreglar ahora, planificar, aceptar temporalmente o descartar.
- Mitigacion aplicada.

No hace falta calcular CVSS para pequenos detalles internos sin impacto real. Si afecta credenciales, datos de alumnos, publicacion en CARM, ejecucion de comandos, lectura de archivos o exposicion de endpoints, si debe clasificarse.

## Criterios Locales

En esta app se subira prioridad cuando el fallo permita:

- Leer o modificar credenciales CARM.
- Reutilizar o robar la sesion recordada de CARM.
- Publicar notas o feedback sin revision humana.
- Ejecutar comandos desde la interfaz local.
- Leer archivos fuera de las carpetas permitidas.
- Procesar entregas maliciosas con impacto en el equipo local.
- Exponer nombres de alumnos, notas, entregas o feedback en logs/diagnosticos.

Se bajara prioridad cuando:

- Requiera acceso fisico o control previo del usuario Windows.
- Solo afecte datos de prueba.
- No suponga perdida de confidencialidad, integridad o disponibilidad real.
- Este mitigado por `127.0.0.1`, allowlists, revision humana o ausencia de publicacion automatica.

## Ejemplos Para Esta App

| Hallazgo | Prioridad Inicial | Motivo |
| --- | --- | --- |
| Endpoint local acepta comandos arbitrarios | Alta/Critica | Podria ejecutar acciones no previstas desde el navegador local. |
| Credenciales CARM en `.env` en texto plano | Alta | Riesgo directo sobre cuenta CARM si otro proceso lee el archivo. |
| Falta token local anti-CSRF para `/api/run` | Alta | Una web abierta en el navegador podria intentar llamar a `127.0.0.1`. |
| ZIP sin limites ni proteccion zip-slip | Alta | Una entrega podria escribir fuera del destino o agotar recursos. |
| Publicar aunque haya `revision_manual_necesaria` | Alta | Impacta integridad academica y datos del alumno. |
| Logs con nombres de alumnos | Media | Dato personal local; depende de exposicion/retencion. |
| Timeout de Playwright demasiado bajo | Baja/Media | Disponibilidad, no confidencialidad/integridad. |

## Plantilla de Hallazgo

```text
ID:
Fecha:
Descripcion:
Activo afectado:
Vector CVSS v4.0:
Severidad:
Decision:
Mitigacion:
Estado:
```

## Cola Inicial de Riesgos

- [x] Proteger endpoints locales con token de sesion local.
- [x] Endurecer lectura de ZIP y archivos de alumnos.
- [x] Bloquear publicacion si existen errores o revision manual.
- [ ] Revisar redaccion/retencion de logs con datos personales.

No priorizado ahora:

- [ ] Guardar credenciales CARM con Windows DPAPI. Riesgo aceptado temporalmente por modelo de app local y equipo de confianza.

## Regla Para Cambios Futuros

Cuando se detecte un riesgo nuevo, primero se anota en este documento o en `SEGURIDAD_ASVS.md`; despues se decide prioridad usando impacto real en credenciales, datos de alumnos, integridad de notas y ejecucion local.
